"""Chat UI and the streaming chat API."""

import json
import logging
import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

from .. import llm, models
from ..security import current_user, login_required, rate_limit_exceeded

log = logging.getLogger(__name__)
bp = Blueprint("chat", __name__)

MAX_MESSAGE_CHARS = 16_000
MAX_TITLE_CHARS = 80


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _sse(payload):
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# --- pages ---------------------------------------------------------------


@bp.get("/")
def root():
    if current_user():
        return redirect(url_for("chat.index"))
    # Public landing page. It renders no user data; everything behind it
    # still requires a session.
    return render_template("landing.html")


@bp.get("/chat")
@login_required
def index():
    user = current_user()
    return render_template(
        "chat.html",
        conversations=models.list_conversations(user["id"]),
        conversation=None,
        messages=[],
        user=user,
    )


@bp.get("/chat/<conversation_id>")
@login_required
def view_conversation(conversation_id):
    user = current_user()
    conv_id = _parse_uuid(conversation_id)
    if conv_id is None:
        abort(404)

    # Scoped to this user — someone else's id returns None, not their transcript.
    conversation = models.get_conversation(user["id"], conv_id)
    if conversation is None:
        abort(404)

    return render_template(
        "chat.html",
        conversations=models.list_conversations(user["id"]),
        conversation=conversation,
        messages=models.list_messages(user["id"], conv_id),
        user=user,
    )


# --- conversation management --------------------------------------------


@bp.get("/api/conversations")
@login_required
def api_list_conversations():
    rows = models.list_conversations(current_user()["id"])
    return jsonify(
        conversations=[
            {
                "id": str(r["id"]),
                "title": r["title"] or "New chat",
                "updated_at": r["updated_at"].isoformat(),
            }
            for r in rows
        ]
    )


@bp.patch("/api/conversations/<conversation_id>")
@login_required
def api_rename_conversation(conversation_id):
    conv_id = _parse_uuid(conversation_id)
    if conv_id is None:
        return jsonify(error="Unknown conversation."), 404

    title = (request.get_json(silent=True) or {}).get("title", "")
    title = " ".join(str(title).split())[:MAX_TITLE_CHARS]
    if not title:
        return jsonify(error="Title cannot be empty."), 400

    if not models.rename_conversation(current_user()["id"], conv_id, title):
        return jsonify(error="Unknown conversation."), 404
    return jsonify(id=str(conv_id), title=title)


@bp.delete("/api/conversations/<conversation_id>")
@login_required
def api_delete_conversation(conversation_id):
    conv_id = _parse_uuid(conversation_id)
    if conv_id is None:
        return jsonify(error="Unknown conversation."), 404

    if not models.delete_conversation(current_user()["id"], conv_id):
        return jsonify(error="Unknown conversation."), 404
    return jsonify(ok=True)


# --- streaming chat ------------------------------------------------------


@bp.post("/api/chat")
@login_required
def api_chat():
    user = current_user()
    cfg = current_app.config["cortexone"]
    payload = request.get_json(silent=True) or {}

    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify(error="Message cannot be empty."), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify(error=f"Message exceeds {MAX_MESSAGE_CHARS} characters."), 413

    if rate_limit_exceeded(user["id"]):
        return jsonify(error="Hourly message limit reached. Try again later."), 429

    # Resolve the conversation, creating one if this is a fresh chat.
    raw_id = payload.get("conversation_id")
    if raw_id:
        conv_id = _parse_uuid(raw_id)
        if conv_id is None:
            return jsonify(error="Unknown conversation."), 404
        conversation = models.get_conversation(user["id"], conv_id)
        if conversation is None:
            return jsonify(error="Unknown conversation."), 404
    else:
        conversation = models.create_conversation(user["id"])
        conv_id = conversation["id"]

    needs_title = not conversation.get("title")

    # Read history *before* inserting, so the new message isn't duplicated when
    # build_messages appends it.
    history = models.context_messages(user["id"], conv_id, cfg.max_context_messages)
    if models.add_message(user["id"], conv_id, "user", message) is None:
        return jsonify(error="Unknown conversation."), 404

    messages = llm.build_messages(history, message, cfg.max_context_messages, cfg.max_context_chars)
    app = current_app._get_current_object()

    # Kick the title off now so it overlaps the reply instead of delaying it.
    title_job = llm.BackgroundTitle(app, message) if needs_title else None

    def persist(chunks, outcome):
        """Save whatever the model produced. Must not yield — see `finally` below."""
        reply = "".join(chunks)
        try:
            if reply:
                models.add_message(user["id"], conv_id, "assistant", reply)
            if title_job:
                title = title_job.result()
                if title:
                    models.rename_conversation(user["id"], conv_id, title)
                    outcome["title"] = title
        except Exception:  # noqa: BLE001 - the reply already reached the user
            log.exception("Post-stream persistence failed for conversation %s", conv_id)

    @stream_with_context
    def generate():
        chunks = []
        outcome = {"title": None}
        yield _sse({"type": "start", "conversation_id": str(conv_id)})
        try:
            for delta in llm.stream_reply(messages):
                chunks.append(delta)
                yield _sse({"type": "delta", "text": delta})
        except Exception:  # noqa: BLE001 - surface a clean message, log the detail
            log.exception("Streaming failed for conversation %s", conv_id)
            yield _sse({"type": "error", "message": "The model request failed. Try again."})
        finally:
            # Runs on GeneratorExit too, so closing the tab mid-reply still saves
            # the partial answer instead of leaving a user message with no reply.
            persist(chunks, outcome)

        yield _sse({"type": "done", "conversation_id": str(conv_id), "title": outcome["title"]})

    response = current_app.response_class(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"  # stop proxies buffering the stream
    # No `Connection: keep-alive` here. It is a connection-specific header that
    # HTTP/2 forbids, and Vercel serves HTTP/2 — sending it risks the client
    # mishandling where the response ends.
    return response
