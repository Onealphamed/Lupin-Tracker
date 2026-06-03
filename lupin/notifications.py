"""Notification orchestrator: /api/sheet-edit and /api/weekly.

Builds the Telegram body and the email body, fans Telegram DMs to
recipients with chat IDs, and hands the email payload (+ failed-targets
list) back to Apps Script which delivers via MailApp. Recipients with
only an email address still get the email; recipients with only a chat
ID still get the Telegram message.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from . import config
from .analytics import analyze
from .email_client import format_edit_email, format_weekly_email, send as email_send
from .recipients import list_recipients
from .sheets import gviz_csv
from .telegram_client import html_escape, tg

notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/api/sheet-edit", methods=["POST"])
def sheet_edit():
    """Apps Script onEdit / onChange calls this. Fans Telegram + email to
    recipients with notify_on_edit=Yes."""
    body = request.get_json(force=True, silent=True) or {}
    if body.get("password") != config.TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401

    month = body.get("month", "")
    therapy = body.get("therapy", "")
    stage = body.get("stage", "") or body.get("header", "")
    old = body.get("old_value", "")
    new = body.get("new_value", "")
    is_done = bool(body.get("is_done"))
    editor = body.get("editor", "")

    # Telegram body (HTML parse mode)
    lines = ["<b>✏️ Lupin Tracker update</b>", ""]
    if month:
        lines.append(f"🗓 <b>{html_escape(month)}</b>")
    if therapy:
        lines.append(f"💊 <b>{html_escape(therapy)}</b>")
    if stage:
        state = "✅ Completed" if is_done else "⬜ Pending"
        lines.append(f"🏷 <i>{html_escape(stage)}</i> → {state}")
    if old or new:
        lines.append("")
        if old:
            lines.append(f"<i>was</i>: <code>{html_escape(old)}</code>")
        if new:
            lines.append(f"<i>now</i>: <b>{html_escape(new)}</b>")
    if editor:
        lines.append("")
        lines.append(f"👤 <i>{html_escape(editor)}</i>")
    tg_text = "\n".join(lines)

    # Email body
    email_subject, email_html = format_edit_email(
        month, therapy, stage, old, new, is_done, editor,
    )

    recips = list_recipients()
    notify_list = [r for r in recips if r["notify_on_edit"]]

    sent_tg = 0
    tg_error = ""
    for r in notify_list:
        if not r["chat_id"] or not config.TELEGRAM_BOT_TOKEN:
            continue
        resp = tg("sendMessage", chat_id=r["chat_id"], text=tg_text, parse_mode="HTML")
        if resp.get("ok"):
            sent_tg += 1
        elif not tg_error:
            tg_error = str(resp.get("description") or resp.get("error_code") or resp)[:160]

    email_targets = [r["email"] for r in notify_list if r["email"]]
    sent_email, failed_email = email_send(email_targets, email_subject, email_html) \
        if email_targets else (0, [])

    # Diagnostic block — visible in the Apps Script execution log. Cheap
    # and very handy when "I'm not getting alerts" happens again.
    raw = gviz_csv(config.TAB_RECIPIENTS)
    headers_seen = raw[0] if raw else []
    recip_dump = [
        {
            "name": r["name"],
            "chat_id_len": len(r["chat_id"]),
            "chat_id_digits": r["chat_id"].lstrip("-").isdigit() if r["chat_id"] else False,
            "has_email": bool(r["email"]),
            "notify": r["notify_on_edit"],
        }
        for r in recips
    ]
    return jsonify({
        "ok": True,
        "sent_telegram": sent_tg,
        "sent_email": sent_email,
        "email_failed_targets": failed_email,
        "email_subject": email_subject,
        "email_html": email_html,
        "recipients_total": len(recips),
        "recipients_notify": len(notify_list),
        "headers_seen": headers_seen,
        "recipients": recip_dump,
        "rows_in_tab": max(0, len(raw) - 1) if raw else 0,
        "tg_error": tg_error,
    })


@notifications_bp.route("/api/weekly", methods=["POST", "GET"])
def weekly():
    pw = (request.get_json(silent=True) or {}).get("password") or request.args.get("password")
    if pw != config.TICK_PASSWORD:
        return jsonify({"ok": False, "error": "bad password"}), 401

    d = analyze()
    k = d["kpi"]

    # Telegram digest (HTML parse mode)
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
        lines.append(f"• {html_escape(mb['month'])}: <b>{mb['pct']}%</b> "
                     f"({mb['done']}/{mb['total']})")
    lines.append("")
    lines.append("<b>Stage-wise progress</b>")
    for st in d["per_stage"]:
        lines.append(f"• {html_escape(st['name'])}: <b>{st['pct']}%</b> "
                     f"({st['done']}/{st['total']})")
    tg_text = "\n".join(lines)

    email_subject, email_html = format_weekly_email(d)

    recips = list_recipients()
    digest_list = [r for r in recips if r["weekly_digest"]]

    sent_tg = 0
    for r in digest_list:
        if not r["chat_id"] or not config.TELEGRAM_BOT_TOKEN:
            continue
        if tg("sendMessage", chat_id=r["chat_id"], text=tg_text, parse_mode="HTML").get("ok"):
            sent_tg += 1

    email_targets = [r["email"] for r in digest_list if r["email"]]
    sent_email, failed_email = email_send(email_targets, email_subject, email_html) \
        if email_targets else (0, [])

    return jsonify({
        "ok": True,
        "sent_telegram": sent_tg,
        "sent_email": sent_email,
        "email_failed_targets": failed_email,
        "email_subject": email_subject,
        "email_html": email_html,
    })
