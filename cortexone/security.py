"""Authentication, CSRF, and input validation helpers."""

import functools
import hmac
import re
import secrets

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import models

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024  # Bound the work an unauthenticated caller can cause.


# --- passwords -----------------------------------------------------------


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def normalize_email(email):
    return (email or "").strip().lower()


def validate_credentials(email, password):
    """Return a list of human-readable problems; empty means valid."""
    problems = []
    if not EMAIL_RE.match(normalize_email(email)) or len(email) > 254:
        problems.append("Enter a valid email address.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        problems.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password or "") > MAX_PASSWORD_LENGTH:
        problems.append("Password is too long.")
    return problems


# --- sessions ------------------------------------------------------------


def log_in(user_id):
    """Start an authenticated session, discarding any prior session state.

    Clearing first prevents session fixation: a value planted before login
    cannot survive into the authenticated session.
    """
    session.clear()
    session["user_id"] = int(user_id)
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def log_out():
    session.clear()


def current_user():
    """The logged-in user row, or None. Cached per request."""
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = models.get_user_by_id(user_id) if user_id else None
        if user_id and g.user is None:
            # Account was deleted out from under a live cookie.
            session.clear()
    return g.user


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if _wants_json():
                return jsonify(error="Not signed in."), 401
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _wants_json():
    return request.path.startswith("/api/") or "application/json" in (
        request.headers.get("Accept", "")
    )


# --- CSRF ----------------------------------------------------------------


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def inject_csrf_token():
    """Template context processor, so forms can render {{ csrf_token }}."""
    return {"csrf_token": csrf_token()}


def verify_csrf():
    """Reject state-changing requests that lack a matching token.

    Registered as a global before_request hook rather than a per-view decorator
    so that adding a new POST route cannot accidentally skip the check.
    """
    if request.method in SAFE_METHODS:
        return None

    expected = session.get("csrf_token")
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")

    if not expected or not hmac.compare_digest(str(expected), str(provided)):
        current_app.logger.warning("CSRF rejection on %s", request.path)
        return jsonify(error="Your session expired. Reload the page and try again."), 403
    return None


# --- rate limiting -------------------------------------------------------


def rate_limit_exceeded(user_id):
    limit = current_app.config["cortexone"].rate_limit_per_hour
    if limit <= 0:
        return False
    return models.messages_in_last_hour(user_id) >= limit
