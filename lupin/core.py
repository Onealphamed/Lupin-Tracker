"""Core routes — anything that doesn't belong to a feature blueprint:

- /                  dashboard HTML
- /healthz           liveness probe
- /favicon.ico       silence the 404
- /api/tick          toggle a stage cell (proxy to Apps Script)
- /iframe/<tab>      pass-through to the Apps Script HTML mirror
- /api/diag          diagnostic JSON (password-gated)
"""
from __future__ import annotations

import json
from datetime import datetime

import requests
from flask import Blueprint, jsonify, render_template, request

from . import config
from .auth import login_required
from .sheets import apps_script_post

core_bp = Blueprint("core", __name__)


@core_bp.route("/")
@login_required
def dashboard():
    return render_template(
        "index.html",
        sheet_id=config.SHEET_ID,
        stages=["TOC Shared", "TOC Approved", "Design Plan", "CRD Upload"],
        sheet_url=f"https://docs.google.com/spreadsheets/d/{config.SHEET_ID}/edit" if config.SHEET_ID else "#",
        apps_script_url=config.APPS_SCRIPT_URL,
        data_tab=config.TAB_DATA,
    )


@core_bp.route("/favicon.ico")
def favicon():
    return ("", 204)


@core_bp.route("/healthz")
def healthz():
    return {"ok": True, "service": "lupin-tracker"}, 200


@core_bp.route("/api/tick", methods=["POST"])
@login_required
def tick():
    """Toggle a stage cell green / clear via Apps Script."""
    if not config.APPS_SCRIPT_URL:
        return jsonify({"ok": False, "error": "APPS_SCRIPT_URL not configured"}), 503
    body = request.get_json(force=True, silent=True) or {}
    row = body.get("row")
    col = body.get("col")
    done = bool(body.get("done"))
    if row is None or col is None:
        return jsonify({"ok": False, "error": "row/col missing"}), 400
    status, text = apps_script_post({
        "password": config.TICK_PASSWORD,
        "action": "set_cell_done",
        "tab": config.TAB_DATA,
        "row": int(row),
        "col": int(col),
        "done": done,
    })
    try:
        data = json.loads(text)
    except Exception:
        data = {"ok": False, "error": f"non-JSON (status={status}): {text[:200]}"}
    return jsonify(data), (200 if data.get("ok") else 502)


@core_bp.route("/iframe/<path:tab_name>")
@login_required
def iframe(tab_name: str):
    if not config.APPS_SCRIPT_URL:
        return "<div style='padding:40px;font-family:Arial'>APPS_SCRIPT_URL not configured</div>", 503
    try:
        r = requests.get(config.APPS_SCRIPT_URL, params={"tab": tab_name}, timeout=20)
        return r.text, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        return f"<div style='padding:40px;font-family:Arial'>Iframe error: {e}</div>", 502


@core_bp.route("/api/diag", methods=["GET"])
def diag():
    """Diagnostic dump for setup verification. Password-gated so it
    doesn't leak whether APPS_SCRIPT_URL / TELEGRAM_BOT_TOKEN are set to
    a casual passerby."""
    if request.args.get("password") != config.TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401
    out: dict = {
        "sheet_id_set": bool(config.SHEET_ID),
        "apps_script_url_set": bool(config.APPS_SCRIPT_URL),
        "apps_script_url_host": (
            config.APPS_SCRIPT_URL.split("/")[2]
            if config.APPS_SCRIPT_URL.startswith("http")
            else ""
        ),
        "telegram_token_set": bool(config.TELEGRAM_BOT_TOKEN),
        "data_tab": config.TAB_DATA,
    }
    if config.APPS_SCRIPT_URL:
        status, text = apps_script_post({
            "password": config.TICK_PASSWORD,
            "action": "read_grid",
            "tab": config.TAB_DATA,
        })
        out["probe_status"] = status
        try:
            d = json.loads(text)
            out["probe_ok"] = bool(d.get("ok"))
            out["probe_rows"] = len(d.get("rows", []))
            out["probe_has_backgrounds"] = bool(d.get("backgrounds"))
        except Exception:
            out["probe_response_first_300"] = text[:300] if text else ""
    out["server_time_utc"] = datetime.utcnow().isoformat() + "Z"
    return jsonify(out)
