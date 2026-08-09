"""OpenAI integration: conversation memory, streaming, and titles.

Three problems with the previous version are fixed here.

*No memory.* The old `generate_response` sent `[system, current_message]` and
nothing else, so the assistant had no recollection of anything said earlier in
the same chat. `build_messages` replays the recent transcript within a budget.

*Doubled first-message latency.* Title generation used to run before the reply
call, serially, so the very first message of every chat waited on two round
trips. It now runs concurrently with the streamed reply.

*No streaming.* The user waited for the entire completion. `stream_reply`
yields deltas as they arrive.
"""

import logging
import threading

from flask import current_app
from openai import OpenAI

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are CortexOne, a helpful assistant. Be accurate and concise. "
    "Use Markdown for structure and fenced code blocks for code."
)

TITLE_PROMPT = (
    "Write a title of at most five words for a conversation that opens with the "
    "following message. Reply with the title only — no quotes, no punctuation at "
    "the end, no preamble."
)

_client = None
_client_lock = threading.Lock()


def client():
    """Module-level client, reused across warm serverless invocations."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                cfg = current_app.config["cortexone"]
                _client = OpenAI(
                    api_key=cfg.openai_api_key,
                    base_url=cfg.openai_base_url,
                    max_retries=2,
                    timeout=120.0,
                )
    return _client


def build_messages(history, user_message, max_messages, max_chars):
    """Assemble the request payload from recent history plus the new message.

    History is trimmed from the *oldest* end so the most recent turns — the ones
    that actually carry the thread of the conversation — always survive.
    """
    trimmed = list(history)[-max_messages:]

    budget = max_chars - len(user_message)
    kept = []
    for row in reversed(trimmed):
        content = row["content"]
        if budget - len(content) < 0:
            break
        kept.append(row)
        budget -= len(content)
    kept.reverse()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend({"role": r["role"], "content": r["content"]} for r in kept)
    messages.append({"role": "user", "content": user_message})
    return messages


def _create(**kwargs):
    """Call chat.completions, tolerating the max_tokens/max_completion_tokens split.

    Reasoning-era models rejected `max_tokens` in favour of
    `max_completion_tokens`, and older ones do the reverse. Rather than pin the
    app to one model generation, try the modern name and fall back.
    """
    cap = kwargs.pop("token_cap", None)
    if cap is None:
        return client().chat.completions.create(**kwargs)

    try:
        return client().chat.completions.create(max_completion_tokens=cap, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the SDK raises several types here
        if "max_completion_tokens" not in str(exc):
            raise
        return client().chat.completions.create(max_tokens=cap, **kwargs)


def stream_reply(messages):
    """Yield the assistant's reply in text deltas as they arrive."""
    cfg = current_app.config["cortexone"]
    stream = _create(model=cfg.model, messages=messages, stream=True)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        text = getattr(delta, "content", None)
        if text:
            yield text


def generate_title(user_message):
    """A short conversation title. Never raises — falls back to a truncation."""
    cfg = current_app.config["cortexone"]
    try:
        completion = _create(
            model=cfg.title_model,
            messages=[
                {"role": "system", "content": TITLE_PROMPT},
                {"role": "user", "content": user_message[:2000]},
            ],
            token_cap=24,
        )
        title = (completion.choices[0].message.content or "").strip().strip('"')
        if title:
            return title[:80]
    except Exception:  # noqa: BLE001 - a title is never worth failing a chat over
        log.exception("Title generation failed; falling back to truncation")

    fallback = " ".join(user_message.split())[:48]
    return fallback or "New chat"


class BackgroundTitle:
    """Runs title generation alongside the streamed reply instead of before it.

    The thread is started and joined inside a single request, so nothing
    outlives the serverless invocation.
    """

    def __init__(self, app, user_message):
        self._result = None
        self._thread = threading.Thread(
            target=self._run, args=(app, user_message), daemon=True
        )
        self._thread.start()

    def _run(self, app, user_message):
        with app.app_context():
            self._result = generate_title(user_message)

    def result(self, timeout=20.0):
        self._thread.join(timeout)
        return self._result
