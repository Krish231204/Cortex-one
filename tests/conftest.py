"""Test fixtures. Requires a reachable Postgres in TEST_DATABASE_URL.

    docker run -d --name cortexone-pg -e POSTGRES_PASSWORD=devpass \
        -e POSTGRES_DB=cortexone -p 55432:5432 postgres:16-alpine

    TEST_DATABASE_URL=postgresql://postgres:devpass@localhost:55432/cortexone \
        .venv/bin/python -m pytest
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_URL = "postgresql://postgres:devpass@localhost:55432/cortexone"


@pytest.fixture(scope="session", autouse=True)
def _environment():
    os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", DEFAULT_URL)
    os.environ["SECRET_KEY"] = "test-secret-not-used-anywhere-real"
    os.environ["OPENAI_API_KEY"] = "sk-test-placeholder"
    os.environ["FLASK_ENV"] = "development"
    os.environ["RATE_LIMIT_PER_HOUR"] = "0"


@pytest.fixture()
def app(_environment):
    import psycopg

    from cortexone import create_app
    from cortexone.db import init_schema

    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, prepare_threshold=None) as conn:
        conn.execute("DROP TABLE IF EXISTS legacy_session_map, messages, conversations, users CASCADE")
        conn.commit()
    init_schema(conninfo=url)

    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def register(client, email, password="correct-horse-battery"):
    """Register a user and return a client session already logged in."""
    client.get("/register")  # seed the CSRF token
    with client.session_transaction() as sess:
        token = sess["csrf_token"]
    response = client.post(
        "/register",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.data
    return token


def csrf_of(client):
    with client.session_transaction() as sess:
        return sess.get("csrf_token", "")
