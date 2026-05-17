"""
Lupin Tracker — Flask backend.

Live dashboard on top of a single Google Sheet. The sheet is the source of
truth. Unlike the Zydus tracker there is **no Status column**: a stage is
"done" only when its cell is filled green; an empty/uncoloured cell is
"pending". There are exactly two states.

Sheet shape (one tab)
---------------------
    Months | (blank) | Therapies | TOC Shared | TOC Approved | Design Plan | CRD Upload | Comments

- "Months" only appears on the first row of each month block (forward-filled).
- Each month repeats the same list of therapy areas.
- The four middle columns are *stages*. Their text (a date / "Yes" / blank)
  is informational only — completion is the **green background**.
- "Comments" is free text per therapy row.

Because the public gviz CSV export cannot see cell colours, the real
completion signal is read through the Apps Script Web App (action=read_grid,
which returns values AND backgrounds). If Apps Script is not yet wired the
backend degrades to a value-based estimate and flags it.

Routes
------
/                 -> dashboard (login required)
/login            -> password gate
/api/analytics    -> JSON: KPIs + month-wise + therapy-wise + grid
/api/tick         -> POST: toggle a stage cell green/clear (proxies Apps Script)
/api/sheet-edit   -> POST: Apps Script onEdit webhook; fans Telegram alerts
/api/weekly       -> POST: weekly digest webhook
/api/telegram     -> POST: Telegram webhook; captures chat IDs on /start
/iframe/<tab>     -> HTML mirror of the tab (full colour) for the iframe
/healthz /api/diag
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from functools import wraps
from typing import Any
from urllib.parse import urlencode

import requests
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# ───────────────────────────── config ─────────────────────────────

# `os.environ.get(key, default)` only falls back when the key is ABSENT.
# On Render an env var declared in render.yaml (e.g. SECRET_KEY with
# generateValue) can exist but be an empty string if the service wasn't
# created from the Blueprint — an empty secret key makes Flask refuse all
# sessions and 500 every login. `_env` treats blank as missing so a sane
# default always applies. The SECRET_KEY fallback is a fixed string (not
# random) on purpose: with --workers 2 a random per-process key would
# differ between workers and logins wouldn't persist.
def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key)
    return v.strip() if v and v.strip() else default


SHEET_ID = _env("TRACKER_SHEET_ID")
APPS_SCRIPT_URL = _env("APPS_SCRIPT_URL")
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
DASHBOARD_PASSWORD = _env("DASHBOARD_PASSWORD", "Alphamed@4321")
TICK_PASSWORD = _env("TICK_PASSWORD", DASHBOARD_PASSWORD)
SECRET_KEY = _env("SECRET_KEY", "lupin-tracker-stable-secret-change-me")

# Main data tab. The Lupin sheet keeps everything on one tab; if the user
# renames it, override with TRACKER_TAB.
TAB_DATA = os.environ.get("TRACKER_TAB", "Tracker")
TAB_RECIPIENTS = "Recipients"

# Header detection is fuzzy so the sheet owner can tweak labels without
# breaking the dashboard.
def _is_month_header(h: str) -> bool:
    return "month" in h.lower()


def _is_therapy_header(h: str) -> bool:
    return "therap" in h.lower()


def _is_comment_header(h: str) -> bool:
    return "comment" in h.lower() or "remark" in h.lower() or "note" in h.lower()


# Fallback stage list — only used to render a header skeleton before the
# first /api/analytics fetch lands. Real stages are discovered from the
# sheet header row at request time.
FALLBACK_STAGES = ["TOC Shared", "TOC Approved", "Design Plan", "CRD Upload"]

app = Flask(__name__)
app.secret_key = SECRET_KEY


# ───────────────────────────── auth ─────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password", "") == DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        return render_template("login.html", error="Wrong password"), 401
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─────────────────────── colour helpers ───────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    if not h:
        return None
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def _is_green(bg: str) -> bool:
    """True if a cell background reads as 'green' (the done signal).

    Tolerant of every common Google Sheets green: pale (#d9ead3),
    light (#b6d7a8), medium (#93c47d / #6aa84f), and pure (#00ff00 /
    #34a853). Rejects white/no-fill, greys, and non-green hues.
    """
    rgb = _hex_to_rgb(bg)
    if rgb is None:
        return False
    r, g, b = rgb
    # No fill / white / near-white
    if r > 235 and g > 235 and b > 235:
        return False
    # Green must dominate both other channels by a clear margin and not
    # be too dark to read.
    return g >= 60 and (g - r) >= 8 and (g - b) >= 8


# ─────────────────────── sheet reading ───────────────────────

def _apps_script_post(payload: dict, max_redirects: int = 5) -> tuple[int, str]:
    """POST to the Apps Script Web App, following its 302 with a GET to
    retrieve the body (standard Apps Script Web App behaviour)."""
    if not APPS_SCRIPT_URL:
        return (-1, "APPS_SCRIPT_URL not configured")
    url, method, last = APPS_SCRIPT_URL, "POST", None
    try:
        for _ in range(max_redirects):
            if method == "POST":
                r = requests.post(url, json=payload, timeout=20, allow_redirects=False)
            else:
                r = requests.get(url, timeout=20, allow_redirects=False)
            last = r
            if r.status_code in (301, 302, 303):
                loc = r.headers.get("Location") or ""
                if not loc:
                    break
                url, method = loc, "GET"
                continue
            if r.status_code in (307, 308):
                loc = r.headers.get("Location") or ""
                if not loc:
                    break
                url = loc
                continue
            return (r.status_code, r.text)
        return (last.status_code if last is not None else -1,
                last.text if last is not None else "no response")
    except Exception as e:
        return (-1, f"exception: {e}")


def _read_grid() -> dict[str, Any]:
    """Return {headers, rows, backgrounds, color_source}.

    Primary path: Apps Script read_grid (values + backgrounds). This is
    the only path that can see green = done.

    Fallback: gviz CSV (values only). We then treat any non-empty stage
    cell as done so the dashboard still shows something, and set
    color_source=False so the UI can warn that this is an estimate.
    """
    # Primary: Apps Script with colours.
    if APPS_SCRIPT_URL:
        status, text = _apps_script_post({
            "password": TICK_PASSWORD,
            "action": "read_grid",
            "tab": TAB_DATA,
        })
        if status == 200:
            try:
                data = json.loads(text)
                if data.get("ok") and data.get("headers"):
                    return {
                        "headers": [str(h) for h in data["headers"]],
                        "rows": [[("" if v is None else str(v)) for v in r]
                                 for r in data.get("rows", [])],
                        "backgrounds": data.get("backgrounds", []),
                        "color_source": True,
                    }
            except Exception:
                pass

    # Fallback: gviz CSV, no colours.
    if SHEET_ID:
        qs = urlencode({"tqx": "out:csv", "sheet": TAB_DATA})
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{qs}"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                rows = list(csv.reader(io.StringIO(r.content.decode("utf-8", "replace"))))
                if rows:
                    return {
                        "headers": [str(h) for h in rows[0]],
                        "rows": [[str(c) for c in row] for row in rows[1:]],
                        "backgrounds": [],
                        "color_source": False,
                    }
        except Exception:
            pass

    return {"headers": [], "rows": [], "backgrounds": [], "color_source": False}


def _gviz_csv(tab_name: str) -> list[list[str]]:
    if not SHEET_ID:
        return []
    qs = urlencode({"tqx": "out:csv", "sheet": tab_name})
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?{qs}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return list(csv.reader(io.StringIO(r.content.decode("utf-8", "replace"))))
    except Exception:
        pass
    # Apps Script fallback for a private sheet
    if APPS_SCRIPT_URL:
        status, text = _apps_script_post({
            "password": TICK_PASSWORD, "action": "read_grid", "tab": tab_name,
        })
        if status == 200:
            try:
                d = json.loads(text)
                if d.get("ok") and d.get("headers"):
                    return [d["headers"]] + [
                        [("" if v is None else str(v)) for v in r]
                        for r in d.get("rows", [])
                    ]
            except Exception:
                pass
    return []


def _rows_as_dicts(rows: list[list[str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    headers = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any((c or "").strip() for c in r):
            continue
        out.append({h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(headers)})
    return out


# ─────────────────────────── analytics ───────────────────────────

def _analyze() -> dict[str, Any]:
    grid = _read_grid()
    headers = grid["headers"]
    rows = grid["rows"]
    bgs = grid["backgrounds"]
    color_source = grid["color_source"]

    # Locate columns by fuzzy header match.
    month_col = therapy_col = comment_col = None
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if month_col is None and _is_month_header(hs):
            month_col = i
        elif therapy_col is None and _is_therapy_header(hs):
            therapy_col = i
        elif _is_comment_header(hs):
            comment_col = i

    # Stage columns = everything between Therapies and Comments that has
    # a non-empty header (skips the blank spacer column).
    stage_cols: list[int] = []
    stage_names: list[str] = []
    if therapy_col is not None:
        end = comment_col if comment_col is not None else len(headers)
        for i in range(therapy_col + 1, end):
            name = (headers[i] or "").strip()
            if name:
                stage_cols.append(i)
                stage_names.append(name)
    if not stage_names:
        stage_names = FALLBACK_STAGES

    def cell_done(row_idx: int, col_idx: int, value: str) -> bool:
        if color_source and row_idx < len(bgs) and col_idx < len(bgs[row_idx]):
            return _is_green(bgs[row_idx][col_idx])
        # Value-based estimate when colours aren't available yet.
        return bool((value or "").strip())

    # Walk rows; forward-fill the month label.
    months_order: list[str] = []
    therapies_order: list[str] = []
    grid_rows: list[dict[str, Any]] = []
    current_month = ""

    for ri, raw in enumerate(rows):
        def g(idx):
            return (raw[idx].strip() if idx is not None and idx < len(raw) else "")

        m = g(month_col)
        if m:
            current_month = m
        therapy = g(therapy_col)
        if not therapy and not any(g(c) for c in stage_cols):
            continue  # fully blank row
        if not therapy:
            continue
        if current_month and current_month not in months_order:
            months_order.append(current_month)
        if therapy not in therapies_order:
            therapies_order.append(therapy)

        stages = []
        for sidx, col in enumerate(stage_cols):
            val = g(col)
            done = cell_done(ri, col, val)
            stages.append({
                "name": stage_names[sidx],
                "value": val,
                "done": done,
                "_col": col + 1,  # 1-based sheet column for the tick proxy
            })
        grid_rows.append({
            "month": current_month,
            "therapy": therapy,
            "stages": stages,
            "comment": g(comment_col),
            "done_count": sum(1 for s in stages if s["done"]),
            "total": len(stages),
            "_row": ri + 1,  # 1-based data-row index (sheet row = _row + 1)
        })

    # ── aggregate month-wise ──
    def _blank_stage_tally():
        return {n: {"done": 0, "total": 0} for n in stage_names}

    months: dict[str, dict[str, Any]] = {}
    therapies: dict[str, dict[str, Any]] = {}
    total_cells = done_cells = 0
    per_stage = {n: {"done": 0, "total": 0} for n in stage_names}

    for gr in grid_rows:
        mth = gr["month"] or "(no month)"
        thp = gr["therapy"]
        mb = months.setdefault(mth, {
            "month": mth, "done": 0, "total": 0,
            "stages": _blank_stage_tally(), "therapies": {},
        })
        tb = therapies.setdefault(thp, {
            "therapy": thp, "done": 0, "total": 0,
            "stages": _blank_stage_tally(), "months": {},
        })
        mt = mb["therapies"].setdefault(thp, {"done": 0, "total": 0, "comment": gr["comment"]})
        tm = tb["months"].setdefault(mth, {"done": 0, "total": 0, "comment": gr["comment"]})

        for s in gr["stages"]:
            total_cells += 1
            mb["total"] += 1
            tb["total"] += 1
            mt["total"] += 1
            tm["total"] += 1
            mb["stages"][s["name"]]["total"] += 1
            tb["stages"][s["name"]]["total"] += 1
            per_stage[s["name"]]["total"] += 1
            if s["done"]:
                done_cells += 1
                mb["done"] += 1
                tb["done"] += 1
                mt["done"] += 1
                tm["done"] += 1
                mb["stages"][s["name"]]["done"] += 1
                tb["stages"][s["name"]]["done"] += 1
                per_stage[s["name"]]["done"] += 1

    def pct(d, t):
        return round(100 * d / t) if t else 0

    for mb in months.values():
        mb["pct"] = pct(mb["done"], mb["total"])
    for tb in therapies.values():
        tb["pct"] = pct(tb["done"], tb["total"])

    fully_done_rows = sum(1 for gr in grid_rows if gr["total"] and gr["done_count"] == gr["total"])
    pending_rows = len(grid_rows) - fully_done_rows

    return {
        "kpi": {
            "total_cells": total_cells,
            "done_cells": done_cells,
            "pending_cells": total_cells - done_cells,
            "progress_pct": pct(done_cells, total_cells),
            "total_rows": len(grid_rows),
            "fully_done_rows": fully_done_rows,
            "pending_rows": pending_rows,
            "months": len(months_order),
            "therapies": len(therapies_order),
        },
        "stages": stage_names,
        "per_stage": [
            {"name": n, "done": per_stage[n]["done"], "total": per_stage[n]["total"],
             "pct": pct(per_stage[n]["done"], per_stage[n]["total"])}
            for n in stage_names
        ],
        "months_order": months_order,
        "therapies_order": therapies_order,
        "months": [months[m] for m in months_order if m in months]
                  + [v for k, v in months.items() if k not in months_order],
        "therapies": [therapies[t] for t in therapies_order if t in therapies],
        "grid": grid_rows,
        "color_source": color_source,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }


@app.route("/api/analytics")
@login_required
def analytics():
    return jsonify(_analyze())


# ─────────────────────────── tick proxy ───────────────────────────

@app.route("/api/tick", methods=["POST"])
@login_required
def tick():
    """Toggle a stage cell's completion. Proxies to Apps Script which
    flips the cell background green / clears it (and writes today's date
    when marking done, blank when clearing)."""
    if not APPS_SCRIPT_URL:
        return jsonify({"ok": False, "error": "APPS_SCRIPT_URL not configured"}), 503
    body = request.get_json(force=True, silent=True) or {}
    row = body.get("row")
    col = body.get("col")
    done = bool(body.get("done"))
    if row is None or col is None:
        return jsonify({"ok": False, "error": "row/col missing"}), 400
    status, text = _apps_script_post({
        "password": TICK_PASSWORD,
        "action": "set_cell_done",
        "tab": TAB_DATA,
        "row": int(row),
        "col": int(col),
        "done": done,
    })
    try:
        data = json.loads(text)
    except Exception:
        data = {"ok": False, "error": f"non-JSON (status={status}): {text[:200]}"}
    return jsonify(data), (200 if data.get("ok") else 502)


# ─────────────────────────── Telegram ───────────────────────────

def _tg(method: str, **payload) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        return {}


def _html_escape(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _recipients() -> list[dict[str, str]]:
    rows = _rows_as_dicts(_gviz_csv(TAB_RECIPIENTS))
    out = []
    for r in rows:
        # Match columns fuzzily so hand-made tabs / header typos / trailing
        # spaces don't silently drop everyone. First header containing the
        # keyword wins.
        def col(*keywords: str) -> str:
            for k, v in r.items():
                kl = k.strip().lower()
                if any(kw in kl for kw in keywords):
                    return (v or "").strip()
            return ""

        chat_id = col("chat")
        if not chat_id:
            continue

        # Explicit No/false/0 suppresses; ANYTHING else (incl. blank) is
        # treated as opted-in. Reason: people who registered but left the
        # cell empty still expect alerts — silent opt-out caused exactly
        # the "I registered but get nothing" failure.
        def opted_in(v: str) -> bool:
            return v.strip().lower() not in ("no", "n", "false", "0", "✘", "✗", "x")

        notify_raw = col("notify", "on edit", "edit")
        weekly_raw = col("weekly", "digest")
        out.append({
            "name": col("name") or "Unnamed",
            "role": col("role"),
            "chat_id": chat_id,
            "notify_on_edit": opted_in(notify_raw),
            "weekly_digest": opted_in(weekly_raw),
        })
    return out


@app.route("/api/sheet-edit", methods=["POST"])
def sheet_edit():
    """Apps Script onEdit calls this. Fans an alert to recipients with
    notify_on_edit=Yes. Payload carries month/therapy/stage context."""
    body = request.get_json(force=True, silent=True) or {}
    if body.get("password") != TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"ok": True, "note": "telegram disabled"}), 200

    month = body.get("month", "")
    therapy = body.get("therapy", "")
    stage = body.get("stage", "") or body.get("header", "")
    old = body.get("old_value", "")
    new = body.get("new_value", "")
    is_done = bool(body.get("is_done"))
    editor = body.get("editor", "")

    lines = ["<b>✏️ Lupin Tracker update</b>", ""]
    if month:
        lines.append(f"🗓 <b>{_html_escape(month)}</b>")
    if therapy:
        lines.append(f"💊 <b>{_html_escape(therapy)}</b>")
    if stage:
        state = "✅ Completed" if is_done else "⬜ Pending"
        lines.append(f"🏷 <i>{_html_escape(stage)}</i> → {state}")
    if old or new:
        lines.append("")
        if old:
            lines.append(f"<i>was</i>: <code>{_html_escape(old)}</code>")
        if new:
            lines.append(f"<i>now</i>: <b>{_html_escape(new)}</b>")
    if editor:
        lines.append("")
        lines.append(f"👤 <i>{_html_escape(editor)}</i>")

    text = "\n".join(lines)
    recips = _recipients()
    notify_list = [r for r in recips if r["notify_on_edit"]]
    sent = 0
    tg_error = ""
    for r in notify_list:
        resp = _tg("sendMessage", chat_id=r["chat_id"], text=text, parse_mode="HTML")
        if resp.get("ok"):
            sent += 1
        elif not tg_error:
            # Surface why Telegram refused (e.g. 403 = user never /started
            # this bot, 400 = bad chat id). Truncated, no secrets.
            tg_error = str(resp.get("description") or resp.get("error_code") or resp)[:160]
    # Full transparency block so the Apps Script log shows exactly what
    # the Recipients tab looks like to the server — no more guessing.
    raw = _gviz_csv(TAB_RECIPIENTS)
    headers_seen = raw[0] if raw else []
    recip_dump = [
        {
            "name": r["name"],
            "chat_id_len": len(r["chat_id"]),
            "chat_id_digits": r["chat_id"].lstrip("-").isdigit(),
            "notify": r["notify_on_edit"],
        }
        for r in recips
    ]
    return jsonify({
        "ok": True,
        "sent": sent,
        "recipients_total": len(recips),
        "recipients_notify": len(notify_list),
        "headers_seen": headers_seen,
        "recipients": recip_dump,
        "rows_in_tab": max(0, len(raw) - 1) if raw else 0,
        "tg_error": tg_error,
    })


@app.route("/api/weekly", methods=["POST", "GET"])
def weekly():
    pw = (request.get_json(silent=True) or {}).get("password") or request.args.get("password")
    if pw != TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"ok": True, "note": "telegram disabled"}), 200

    d = _analyze()
    k = d["kpi"]
    lines = [
        "<b>📊 Lupin Tracker — Weekly Digest</b>",
        "",
        f"📈 Overall: <b>{k['progress_pct']}%</b> "
        f"({k['done_cells']}/{k['total_cells']} stages done)",
        f"💊 {k['therapies']} therapies · 🗓 {k['months']} months · "
        f"✅ {k['fully_done_rows']} rows fully done · ⬜ {k['pending_rows']} pending",
        "",
        "<b>Month-wise progress</b>",
    ]
    for mb in d["months"]:
        lines.append(f"• {_html_escape(mb['month'])}: <b>{mb['pct']}%</b> "
                     f"({mb['done']}/{mb['total']})")
    lines.append("")
    lines.append("<b>Stage-wise progress</b>")
    for st in d["per_stage"]:
        lines.append(f"• {_html_escape(st['name'])}: <b>{st['pct']}%</b> "
                     f"({st['done']}/{st['total']})")

    text = "\n".join(lines)
    sent = 0
    for r in _recipients():
        if not r["weekly_digest"]:
            continue
        if _tg("sendMessage", chat_id=r["chat_id"], text=text, parse_mode="HTML").get("ok"):
            sent += 1
    return jsonify({"ok": True, "sent": sent})


@app.route("/api/telegram", methods=["POST"])
def telegram_webhook():
    body = request.get_json(silent=True) or {}
    msg = body.get("message") or body.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", "")).strip()
    if not chat_id:
        return jsonify({"ok": True})
    user = msg.get("from", {}) or {}
    name = " ".join(filter(None, [user.get("first_name", ""), user.get("last_name", "")])).strip() \
        or user.get("username", "Unknown")
    text = (msg.get("text") or "").strip().lower()

    if text.startswith("/start") or text.startswith("/register"):
        status, resp = _apps_script_post({
            "password": TICK_PASSWORD, "action": "register_recipient",
            "name": name, "chat_id": chat_id,
        })
        ok = status == 200 and '"ok":true' in resp
        reg = "✅ Added you to the Recipients tab." if ok else \
            f"⚠️ Could not auto-add you (status={status}). Add a row with chat ID {chat_id} manually."
        _tg("sendMessage", chat_id=chat_id, text=(
            f"Hi {name}! You're registered for Lupin Tracker reminders.\n"
            f"Your chat ID: {chat_id}\n\n{reg}"
        ))
    elif text.startswith("/status"):
        _tg("sendMessage", chat_id=chat_id, text=f"Registered. Chat ID: {chat_id}")
    elif text.startswith("/help"):
        _tg("sendMessage", chat_id=chat_id, text=(
            "Commands:\n/start – register for reminders\n"
            "/status – show your chat ID\n/help – this message"
        ))
    return jsonify({"ok": True})


# ─────────────────────────── iframe mirror ───────────────────────────

@app.route("/iframe/<path:tab_name>")
@login_required
def iframe(tab_name: str):
    if not APPS_SCRIPT_URL:
        return "<div style='padding:40px;font-family:Arial'>APPS_SCRIPT_URL not configured</div>", 503
    try:
        r = requests.get(APPS_SCRIPT_URL, params={"tab": tab_name}, timeout=20)
        return r.text, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        return f"<div style='padding:40px;font-family:Arial'>Iframe error: {e}</div>", 502


# ─────────────────────────── dashboard ───────────────────────────

@app.route("/")
@login_required
def dashboard():
    return render_template(
        "index.html",
        sheet_id=SHEET_ID,
        stages=FALLBACK_STAGES,
        sheet_url=f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit" if SHEET_ID else "#",
        apps_script_url=APPS_SCRIPT_URL,
        data_tab=TAB_DATA,
    )


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/healthz")
def healthz():
    return {"ok": True, "service": "lupin-tracker"}, 200


@app.route("/api/diag", methods=["GET"])
def diag():
    if request.args.get("password") != TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401
    out = {
        "sheet_id_set": bool(SHEET_ID),
        "apps_script_url_set": bool(APPS_SCRIPT_URL),
        "apps_script_url_host": (APPS_SCRIPT_URL.split("/")[2] if APPS_SCRIPT_URL.startswith("http") else ""),
        "telegram_token_set": bool(TELEGRAM_BOT_TOKEN),
        "data_tab": TAB_DATA,
    }
    if APPS_SCRIPT_URL:
        status, text = _apps_script_post({
            "password": TICK_PASSWORD, "action": "read_grid", "tab": TAB_DATA,
        })
        out["probe_status"] = status
        try:
            d = json.loads(text)
            out["probe_ok"] = bool(d.get("ok"))
            out["probe_rows"] = len(d.get("rows", []))
            out["probe_has_backgrounds"] = bool(d.get("backgrounds"))
        except Exception:
            out["probe_response_first_300"] = text[:300] if text else ""
    return jsonify(out)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5003")), debug=True)
