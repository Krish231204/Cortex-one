"""Configuration, loaded once per cold start.

Everything sensitive comes from the environment. Nothing here has a usable
default that would let the app run with a guessable secret — the old build
shipped `app.secret_key = '231204'`, which let anyone forge a session cookie.
"""

import os
import secrets


class ConfigError(RuntimeError):
    """Raised at import time when a required setting is missing."""


def _require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env for local work, or add "
            f"it under Project Settings -> Environment Variables on Vercel."
        )
    return value


def _int(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


class Config:
    def __init__(self):
        self.env = os.environ.get("FLASK_ENV", "production").strip().lower()
        self.is_development = self.env == "development"

        # In development we mint an ephemeral key so `python app.py` just works;
        # the cost is that restarting logs you out, which is the correct
        # trade-off. In production a missing key is a hard failure.
        if self.is_development:
            self.secret_key = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48)
        else:
            self.secret_key = _require("SECRET_KEY")

        self.database_url = _require("DATABASE_URL")
        self.openai_api_key = _require("OPENAI_API_KEY")

        # Optional: point at an Azure/OpenRouter/self-hosted OpenAI-compatible
        # endpoint, or at a local stub during testing.
        self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None

        self.model = os.environ.get("OPENAI_MODEL", "gpt-5.6-sol").strip()
        self.title_model = os.environ.get("OPENAI_TITLE_MODEL", "gpt-5.6-luna").strip()

        self.max_context_messages = _int("MAX_CONTEXT_MESSAGES", 20)
        self.max_context_chars = _int("MAX_CONTEXT_CHARS", 24_000)
        self.rate_limit_per_hour = _int("RATE_LIMIT_PER_HOUR", 120)

    def apply_to(self, app):
        app.config.update(
            SECRET_KEY=self.secret_key,
            # Cookie hardening. Secure is relaxed only for local plain-HTTP work.
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=not self.is_development,
            SESSION_COOKIE_NAME="cortexone_session",
            PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
            MAX_CONTENT_LENGTH=256 * 1024,
            JSON_SORT_KEYS=False,
            cortexone=self,
        )
