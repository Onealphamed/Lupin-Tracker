"""Login gate.

Single password (DASHBOARD_PASSWORD). Session is server-side via Flask's
signed cookie, keyed by SECRET_KEY.
"""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, redirect, render_template, request, session, url_for

from . import config

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return wrapper


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password", "") == config.DASHBOARD_PASSWORD:
            session["logged_in"] = True
            return redirect(request.args.get("next") or url_for("core.dashboard"))
        return render_template("login.html", error="Wrong password"), 401
    return render_template("login.html", error=None)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
