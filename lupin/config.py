"""Environment-variable configuration.

Every setting comes from `os.environ`. `_env()` treats blank values as
missing — Render's render.yaml can declare a var with `generateValue` or
leave it `sync:false` and the cell ends up an empty string if the service
wasn't created from the Blueprint. The old `os.environ.get(k, default)`
returned `""` in that case and broke login (Flask refuses a blank
secret_key); `_env` returns the default instead.
"""
from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    v = os.environ.get(key)
    return v.strip() if v and v.strip() else default


# ──────────── Sheet ────────────
SHEET_ID = _env("TRACKER_SHEET_ID")
APPS_SCRIPT_URL = _env("APPS_SCRIPT_URL")

# Main data tab name. The Apps Script falls back to the first non-
# Recipients sheet if this exact name isn't found, so the dashboard works
# even when the user's tab is misnamed (e.g. "Lupin Trcaker").
TAB_DATA = _env("TRACKER_TAB", "Tracker")
TAB_RECIPIENTS = "Recipients"

# Bibliography. Schema: Therapies | Sr. No | Article header |
# Header of communication | Link | Bucket. Therapies forward-fills.
TAB_TOC = _env("TOC_TAB", "TOC Bank")

# ──────────── Auth ────────────
DASHBOARD_PASSWORD = _env("DASHBOARD_PASSWORD", "CHANGE_ME")
# Shared secret between Flask and the Apps Script — must match the
# PASSWORD constant inside google_apps_script.js exactly. Defaults to
# the dashboard password so a single env var suffices for the common
# case.
TICK_PASSWORD = _env("TICK_PASSWORD", DASHBOARD_PASSWORD)
# Stable (not random) fallback so the 2 gunicorn workers share keys and
# logins persist between requests routed to different workers.
SECRET_KEY = _env("SECRET_KEY", "lupin-tracker-stable-secret-change-me")

# ──────────── Telegram ────────────
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")

# ──────────── Email (SMTP) ────────────
# Render's free tier blocks outbound SMTP, so emails actually deliver via
# the Apps Script MailApp fallback. SMTP config is here for paid Render
# plans and local dev.
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM_NAME = _env("SMTP_FROM_NAME", "Lupin Tracker")
SMTP_FROM_ADDR = _env("SMTP_FROM_ADDR", SMTP_USER)

# Used as the "Open dashboard ↗" CTA target in email bodies. Blank → no
# button.
DASHBOARD_PUBLIC_URL = _env("DASHBOARD_PUBLIC_URL", "https://lupin-tracker.onrender.com")
