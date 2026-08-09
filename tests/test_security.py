"""Regression tests for the vulnerabilities the rebuild closes.

Each test here corresponds to something the previous version got wrong.
"""

import os

import pytest

from conftest import csrf_of, register


# --- authentication is required at all ------------------------------------


def test_root_redirects_anonymous_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_chat_page_requires_login(client):
    response = client.get("/chat")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_chat_api_requires_login(client):
    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code in (401, 403)


# --- per-user isolation: the big one --------------------------------------


def _make_conversation(client, title="Private notes"):
    """Create a conversation directly through the model layer for the logged-in user."""
    from cortexone import models

    with client.application.app_context():
        with client.session_transaction() as sess:
            user_id = sess["user_id"]
        conv = models.create_conversation(user_id, title)
        models.add_message(user_id, conv["id"], "user", "my private question")
        models.add_message(user_id, conv["id"], "assistant", "my private answer")
        return str(conv["id"])


def test_user_cannot_read_another_users_conversation(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    conv_id = _make_conversation(alice)

    # Alice can read her own.
    assert alice.get(f"/chat/{conv_id}").status_code == 200

    bob = app.test_client()
    register(bob, "bob@example.com")
    response = bob.get(f"/chat/{conv_id}")

    assert response.status_code == 404
    assert b"my private question" not in response.data


def test_sidebar_only_lists_own_conversations(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    _make_conversation(alice, "Alice secret plan")

    bob = app.test_client()
    register(bob, "bob@example.com")

    page = bob.get("/chat")
    assert b"Alice secret plan" not in page.data

    listing = bob.get("/api/conversations").get_json()
    assert listing["conversations"] == []


def test_user_cannot_delete_another_users_conversation(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    conv_id = _make_conversation(alice)

    bob = app.test_client()
    register(bob, "bob@example.com")
    response = bob.delete(
        f"/api/conversations/{conv_id}", headers={"X-CSRF-Token": csrf_of(bob)}
    )
    assert response.status_code == 404

    # Still there for Alice.
    assert alice.get(f"/chat/{conv_id}").status_code == 200


def test_user_cannot_rename_another_users_conversation(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    conv_id = _make_conversation(alice, "Original")

    bob = app.test_client()
    register(bob, "bob@example.com")
    response = bob.patch(
        f"/api/conversations/{conv_id}",
        json={"title": "hijacked"},
        headers={"X-CSRF-Token": csrf_of(bob)},
    )
    assert response.status_code == 404
    assert b"hijacked" not in alice.get(f"/chat/{conv_id}").data


def test_user_cannot_post_into_another_users_conversation(app, monkeypatch):
    from cortexone import llm

    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter(["nope"]))

    alice = app.test_client()
    register(alice, "alice@example.com")
    conv_id = _make_conversation(alice)

    bob = app.test_client()
    register(bob, "bob@example.com")
    response = bob.post(
        "/api/chat",
        json={"message": "inject", "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf_of(bob)},
    )
    assert response.status_code == 404


# --- CSRF -----------------------------------------------------------------


def test_state_changing_request_without_csrf_is_rejected(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    conv_id = _make_conversation(alice)

    response = alice.delete(f"/api/conversations/{conv_id}")  # no token header
    assert response.status_code == 403


def test_logout_without_csrf_is_rejected(app):
    alice = app.test_client()
    register(alice, "alice@example.com")
    assert alice.post("/logout").status_code == 403


# --- credential handling --------------------------------------------------


def test_password_is_not_stored_in_plaintext(app):
    from cortexone import models

    alice = app.test_client()
    register(alice, "alice@example.com", password="correct-horse-battery")
    with app.app_context():
        row = models.get_user_by_email("alice@example.com")
    assert "correct-horse-battery" not in row["password_hash"]
    assert row["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_login_does_not_reveal_whether_email_exists(app):
    client = app.test_client()
    register(client, "alice@example.com")
    client.post("/logout", data={"csrf_token": csrf_of(client)})

    client.get("/login")
    token = csrf_of(client)
    wrong_password = client.post(
        "/login", data={"email": "alice@example.com", "password": "wrongwrongwrong", "csrf_token": token}
    )
    unknown_email = client.post(
        "/login", data={"email": "nobody@example.com", "password": "wrongwrongwrong", "csrf_token": token}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401

    message = b"Email or password is incorrect."
    assert message in wrong_password.data and message in unknown_email.data

    # The only difference between the two pages is the email echoed back into
    # the form, which the submitter typed and already knows.
    assert wrong_password.data.replace(b"alice@example.com", b"X") == unknown_email.data.replace(
        b"nobody@example.com", b"X"
    )


def test_weak_password_rejected(app):
    client = app.test_client()
    client.get("/register")
    response = client.post(
        "/register",
        data={"email": "weak@example.com", "password": "short", "csrf_token": csrf_of(client)},
    )
    assert response.status_code == 400
    assert b"at least 10 characters" in response.data


def test_next_parameter_cannot_redirect_offsite(app):
    client = app.test_client()
    register(client, "alice@example.com")
    client.post("/logout", data={"csrf_token": csrf_of(client)})
    client.get("/login")

    response = client.post(
        "/login",
        data={
            "email": "alice@example.com",
            "password": "correct-horse-battery",
            "next": "https://evil.example.com/steal",
            "csrf_token": csrf_of(client),
        },
    )
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]


# --- XSS ------------------------------------------------------------------


def test_message_markup_is_escaped_in_server_rendered_history(app, monkeypatch):
    from cortexone import llm, models

    payload = '<img src=x onerror="alert(1)">'
    monkeypatch.setattr(llm, "stream_reply", lambda messages: iter([payload]))
    monkeypatch.setattr(llm, "generate_title", lambda message: "Title")

    client = app.test_client()
    register(client, "alice@example.com")

    with client.session_transaction() as sess:
        user_id = sess["user_id"]
    with app.app_context():
        conv = models.create_conversation(user_id, "T")
        conv_id = str(conv["id"])

    client.post(
        "/api/chat",
        json={"message": payload, "conversation_id": conv_id},
        headers={"X-CSRF-Token": csrf_of(client)},
    )

    page = client.get(f"/chat/{conv_id}").data.decode()
    assert "<img src=x" not in page
    assert "&lt;img src=x" in page


def test_security_headers_present(client):
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


# --- config safety --------------------------------------------------------


def test_production_refuses_to_boot_without_secret_key(monkeypatch):
    from cortexone.config import Config, ConfigError

    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        Config()


def test_missing_config_serves_a_readable_503_instead_of_crashing(monkeypatch):
    """A misconfigured deploy must name the problem, not crash opaquely."""
    from cortexone import create_app

    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    client = create_app().test_client()
    for path in ("/", "/login", "/chat", "/api/conversations"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert b"SECRET_KEY" in response.data

    # Inert: no session cookie is issued and no real route is reachable.
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 503
    assert not any("cortexone_session" in h for h in
                   client.get("/").headers.getlist("Set-Cookie"))


def test_misconfigured_app_does_not_echo_secret_values(monkeypatch):
    from cortexone import create_app

    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:hunter2@db.example.com/x")

    body = create_app().test_client().get("/").data.decode()
    assert "hunter2" not in body and "db.example.com" not in body


def test_missing_schema_reports_uninitialised_database(app):
    """An empty database must say so, not surface as a generic 500."""
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"], prepare_threshold=None) as conn:
        conn.execute("DROP TABLE IF EXISTS messages, conversations, users CASCADE")
        conn.commit()

    client = app.test_client()
    client.get("/login")  # seeds the CSRF token; this path touches no tables
    response = client.post(
        "/login",
        data={
            "email": "a@example.com",
            "password": "whatever-long-enough",
            "csrf_token": csrf_of(client),
        },
    )
    assert response.status_code == 503
    assert b"schema is not initialised" in response.data
