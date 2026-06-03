"""Telegram bot client.

`tg()` calls the Bot API. The /api/telegram webhook auto-registers users
who DM the bot `/start`, by asking the Apps Script to append a row to
the Recipients tab (the script runs as the sheet owner so it can write
even when the sheet is private).
"""
from __future__ import annotations

import json
from typing import Any

import requests
from flask import Blueprint, jsonify, request

from . import config
from .sheets import apps_script_post

telegram_bp = Blueprint("telegram", __name__)


def tg(method: str, **payload) -> dict:
    """Call a Telegram Bot API method. Returns {} when no token is set."""
    if not config.TELEGRAM_BOT_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=15)
        ct = r.headers.get("content-type", "")
        return r.json() if ct.startswith("application/json") else {}
    except Exception:
        return {}


@telegram_bp.route("/api/telegram", methods=["POST"])
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
        status, resp = apps_script_post({
            "password": config.TICK_PASSWORD,
            "action": "register_recipient",
            "name": name, "chat_id": chat_id,
        })
        ok = status == 200 and '"ok":true' in resp
        reg = "✅ Added you to the Recipients tab." if ok else \
            f"⚠️ Could not auto-add you (status={status}). Add a row with chat ID {chat_id} manually."
        tg("sendMessage", chat_id=chat_id, text=(
            f"Hi {name}! You're registered for Lupin Tracker reminders.\n"
            f"Your chat ID: {chat_id}\n\n{reg}"
        ))
    elif text.startswith("/status"):
        tg("sendMessage", chat_id=chat_id, text=f"Registered. Chat ID: {chat_id}")
    elif text.startswith("/help"):
        tg("sendMessage", chat_id=chat_id, text=(
            "Commands:\n/start – register for reminders\n"
            "/status – show your chat ID\n/help – this message"
        ))
    return jsonify({"ok": True})


def html_escape(s: Any) -> str:
    """HTML escape suitable for Telegram parse_mode=HTML. Kept here so
    other modules can compose Telegram bodies without re-defining it."""
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
