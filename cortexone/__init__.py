"""Application factory for CortexOne."""

import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv()


def _misconfigured_app(message):
    """A deliberately inert app that explains what is missing.

    Raising out of create_app() is safe but opaque: on a serverless host the
    import crashes and the platform shows a generic FUNCTION_INVOCATION_FAILED
    page with no hint which variable is absent. This keeps the safety property
    that matters — no secret key, no database, no routes that touch user data —
    while making the cause readable. It names variables, never values.
    """
    app = Flask(__name__)
    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    @app.route("/", defaults={"path": ""}, methods=methods)
    @app.route("/<path:path>", methods=methods)
    def unconfigured(path):
        body = (
            "CortexOne is not configured.\n\n"
            f"{message}\n\n"
            "Set SECRET_KEY, DATABASE_URL and OPENAI_API_KEY in your hosting "
            "provider's environment variables, then redeploy.\n"
        )
        return body, 503, {"Content-Type": "text/plain; charset=utf-8"}

    return app


def create_app():
    from .config import Config, ConfigError
    from .blueprints.auth import bp as auth_bp
    from .blueprints.chat import bp as chat_bp
    from .security import inject_csrf_token, verify_csrf

    try:
        config = Config()
    except ConfigError as exc:
        return _misconfigured_app(str(exc))

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )
    config.apply_to(app)

    # CSRF is enforced centrally rather than per-view so a new state-changing
    # route cannot silently opt out of it.
    app.before_request(verify_csrf)
    app.context_processor(inject_csrf_token)

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)

    @app.errorhandler(404)
    def not_found(_err):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return jsonify(error="Not found"), 404

    @app.errorhandler(500)
    def server_error(_err):
        # Never leak tracebacks or driver messages to the client.
        app.logger.exception("Unhandled error on %s", request.path)
        return jsonify(error="Something went wrong on our end."), 500

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'",
        )
        return response

    return app
