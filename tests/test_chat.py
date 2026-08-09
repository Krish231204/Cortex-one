"""Behavioural tests for conversation memory, streaming, and titles."""

import json

from conftest import csrf_of, register


def sse_events(response):
    """Parse an SSE response body into a list of payload dicts."""
    events = []
    for frame in response.data.decode().split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data:"):
            events.append(json.loads(frame[5:].strip()))
    return events


# --- conversation memory --------------------------------------------------


def test_build_messages_replays_prior_turns(app):
    from cortexone import llm

    history = [
        {"role": "user", "content": "My name is Krish."},
        {"role": "assistant", "content": "Nice to meet you, Krish."},
    ]
    messages = llm.build_messages(history, "What is my name?", 20, 24_000)

    assert messages[0]["role"] == "system"
    # The whole thread is present, in order, with the new message last.
    assert [m["content"] for m in messages[1:]] == [
        "My name is Krish.",
        "Nice to meet you, Krish.",
        "What is my name?",
    ]


def test_build_messages_drops_oldest_turns_over_budget(app):
    from cortexone import llm

    history = [{"role": "user", "content": "x" * 100} for _ in range(10)]
    history.append({"role": "user", "content": "RECENT"})

    messages = llm.build_messages(history, "new", max_messages=20, max_chars=250)
    contents = [m["content"] for m in messages[1:]]

    assert contents[-1] == "new"
    assert "RECENT" in contents          # newest history survives
    assert len(contents) < len(history)  # oldest were dropped


def test_build_messages_respects_message_count_cap(app):
    from cortexone import llm

    history = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    messages = llm.build_messages(history, "new", max_messages=5, max_chars=24_000)
    assert len(messages) == 1 + 5 + 1  # system + capped history + new message


def test_chat_endpoint_sends_history_to_the_model(app, monkeypatch):
    from cortexone import llm, models

    captured = {}

    def fake_stream(messages):
        captured["messages"] = messages
        return iter(["ok"])

    monkeypatch.setattr(llm, "stream_reply", fake_stream)
    monkeypatch.setattr(llm, "generate_title", lambda m: "Chat")

    client = app.test_client()
    register(client, "alice@example.com")
    with client.session_transaction() as sess:
        user_id = sess["user_id"]
    with app.app_context():
        conv_id = str(models.create_conversation(user_id, "T")["id"])

    # Reading .data drives the streaming generator to completion; without it the
    # reply is never produced or persisted.
    client.post("/api/chat", json={"message": "first", "conversation_id": conv_id},
                headers={"X-CSRF-Token": csrf_of(client)}).data
    client.post("/api/chat", json={"message": "second", "conversation_id": conv_id},
                headers={"X-CSRF-Token": csrf_of(client)}).data

    sent = [m["content"] for m in captured["messages"]]
    # The second call must carry the first exchange, which the old build never did.
    assert "first" in sent and "ok" in sent and sent[-1] == "second"


# --- streaming ------------------------------------------------------------


def test_chat_streams_deltas_and_persists_both_messages(app, monkeypatch):
    from cortexone import llm, models

    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter(["Hel", "lo ", "there"]))
    monkeypatch.setattr(llm, "generate_title", lambda m: "Greeting")

    client = app.test_client()
    register(client, "alice@example.com")

    response = client.post(
        "/api/chat", json={"message": "hi"}, headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"

    events = sse_events(response)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hello there"

    conv_id = events[0]["conversation_id"]
    with client.session_transaction() as sess:
        user_id = sess["user_id"]
    with app.app_context():
        stored = models.list_messages(user_id, conv_id)

    assert [(m["role"], m["content"]) for m in stored] == [
        ("user", "hi"),
        ("assistant", "Hello there"),
    ]


def test_new_conversation_gets_a_generated_title(app, monkeypatch):
    from cortexone import llm

    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter(["sure"]))
    monkeypatch.setattr(llm, "generate_title", lambda m: "Fruit Names")

    client = app.test_client()
    register(client, "alice@example.com")
    response = client.post(
        "/api/chat", json={"message": "name some fruits"},
        headers={"X-CSRF-Token": csrf_of(client)}
    )

    done = sse_events(response)[-1]
    assert done["title"] == "Fruit Names"
    assert client.get("/api/conversations").get_json()["conversations"][0]["title"] == "Fruit Names"


def test_model_failure_is_reported_without_leaking_details(app, monkeypatch):
    from cortexone import llm

    def boom(messages):
        raise RuntimeError("api key sk-secret-value rejected by upstream")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_reply", boom)

    client = app.test_client()
    register(client, "alice@example.com")
    response = client.post(
        "/api/chat", json={"message": "hi"}, headers={"X-CSRF-Token": csrf_of(client)}
    )

    body = response.data.decode()
    assert "sk-secret-value" not in body
    assert any(e["type"] == "error" for e in sse_events(response))


# --- input validation and limits -----------------------------------------


def test_empty_message_rejected(app):
    client = app.test_client()
    register(client, "alice@example.com")
    response = client.post(
        "/api/chat", json={"message": "   "}, headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert response.status_code == 400


def test_oversized_message_rejected(app):
    client = app.test_client()
    register(client, "alice@example.com")
    response = client.post(
        "/api/chat", json={"message": "x" * 20_000},
        headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert response.status_code == 413


def test_rate_limit_blocks_when_configured(app, monkeypatch):
    from cortexone import llm

    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter(["ok"]))
    monkeypatch.setattr(llm, "generate_title", lambda m: "T")
    # Exercise the real counter rather than a stub of it.
    app.config["cortexone"].rate_limit_per_hour = 1

    client = app.test_client()
    register(client, "alice@example.com")

    first = client.post(
        "/api/chat", json={"message": "hi"}, headers={"X-CSRF-Token": csrf_of(client)}
    )
    first.data
    assert first.status_code == 200

    second = client.post(
        "/api/chat", json={"message": "again"}, headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert second.status_code == 429


def test_unknown_conversation_id_is_not_a_server_error(app):
    client = app.test_client()
    register(client, "alice@example.com")
    assert client.get("/chat/not-a-uuid").status_code == 404
    response = client.post(
        "/api/chat", json={"message": "hi", "conversation_id": "not-a-uuid"},
        headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert response.status_code == 404


# --- conversation management ---------------------------------------------


def test_rename_and_delete_own_conversation(app, monkeypatch):
    from cortexone import llm

    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter(["ok"]))
    monkeypatch.setattr(llm, "generate_title", lambda m: "T")

    client = app.test_client()
    register(client, "alice@example.com")
    conv_id = sse_events(
        client.post("/api/chat", json={"message": "hi"},
                    headers={"X-CSRF-Token": csrf_of(client)})
    )[0]["conversation_id"]

    renamed = client.patch(
        f"/api/conversations/{conv_id}", json={"title": "Renamed thread"},
        headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert renamed.status_code == 200
    assert client.get("/api/conversations").get_json()["conversations"][0]["title"] == "Renamed thread"

    deleted = client.delete(
        f"/api/conversations/{conv_id}", headers={"X-CSRF-Token": csrf_of(client)}
    )
    assert deleted.status_code == 200
    assert client.get("/api/conversations").get_json()["conversations"] == []
    assert client.get(f"/chat/{conv_id}").status_code == 404
