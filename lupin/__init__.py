"""Lupin Tracker — application factory.

Routes are organised as feature blueprints so each part stays independent:

    config            → env-var resolution (no deps)
    colors            → green-cell detection (pure functions)
    sheets            → gviz CSV + Apps Script proxy
    recipients        → reads the Recipients tab fuzzily
    analytics         → /api/analytics
    tocbank           → /api/toc-bank
    telegram_client   → _tg() + /api/telegram webhook
    email_client      → SMTP send + HTML body formatters
    notifications     → /api/sheet-edit + /api/weekly (uses telegram + email)
    auth              → /login + /logout + login_required decorator
    core              → /, /healthz, /favicon, /api/tick, /iframe, /api/diag

Edit ONE blueprint without touching the others. create_app() is also handy
for tests — instantiate a fresh app per test with whatever env you need.
"""
from __future__ import annotations

from flask import Flask

from . import config


def create_app() -> Flask:
    app = Flask(
        __name__,
        # Templates live at the project root next to app.py; this package
        # sits one level down, so reach back up.
        template_folder="../templates",
        static_folder="../static",
    )
    app.secret_key = config.SECRET_KEY

    # Import-then-register so each blueprint module owns its own routes.
    from .auth import auth_bp
    from .analytics import analytics_bp
    from .tocbank import tocbank_bp
    from .telegram_client import telegram_bp
    from .notifications import notifications_bp
    from .core import core_bp

    for bp in (auth_bp, analytics_bp, tocbank_bp, telegram_bp, notifications_bp, core_bp):
        app.register_blueprint(bp)

    return app
