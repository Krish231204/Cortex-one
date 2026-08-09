"""Registration, sign-in, and sign-out."""

import logging

from flask import Blueprint, redirect, render_template, request, url_for

from .. import models
from ..security import (
    current_user,
    hash_password,
    log_in,
    log_out,
    normalize_email,
    validate_credentials,
    verify_password,
)

log = logging.getLogger(__name__)
bp = Blueprint("auth", __name__)


def _safe_next(target):
    """Only allow same-site relative redirects, so ?next= can't send users off-site."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("chat.index")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("chat.index"))

    if request.method == "GET":
        return render_template("register.html", errors=[], email="")

    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    errors = validate_credentials(email, password)

    if not errors:
        try:
            user = models.create_user(email, normalize_email(email), hash_password(password))
        except models.UniqueViolation:
            errors.append("That email is already registered.")
        else:
            log_in(user["id"])
            return redirect(url_for("chat.index"))

    return render_template("register.html", errors=errors, email=email), 400


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("chat.index"))

    if request.method == "GET":
        return render_template("login.html", errors=[], email="")

    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""
    user = models.get_user_by_email(normalize_email(email))

    # One message for both "no such account" and "wrong password" so the form
    # can't be used to enumerate which emails are registered.
    if user is None or not verify_password(user["password_hash"], password):
        return (
            render_template(
                "login.html", errors=["Email or password is incorrect."], email=email
            ),
            401,
        )

    log_in(user["id"])
    models.touch_login(user["id"])
    return redirect(_safe_next(request.form.get("next")))


@bp.post("/logout")
def logout():
    log_out()
    return redirect(url_for("auth.login"))
