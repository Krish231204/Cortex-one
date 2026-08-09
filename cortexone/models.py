"""Data access.

The one rule this module exists to enforce: **every conversation and message
query is scoped by user_id in the WHERE clause.** Not filtered in Python after
the fact, not trusted from the session alone — in the SQL. A caller that passes
someone else's conversation id gets zero rows back rather than their data.

The previous build had no such scoping, so `/session/<id>` served any
conversation to anyone who had the URL, and the sidebar listed every
conversation in the database to every visitor.
"""

from .db import UniqueViolation, execute, query_all, query_one, transaction, unique_guard

__all__ = [
    "UniqueViolation",
    "create_user",
    "get_user_by_email",
    "get_user_by_id",
    "touch_login",
    "list_conversations",
    "create_conversation",
    "get_conversation",
    "rename_conversation",
    "delete_conversation",
    "list_messages",
    "add_message",
    "context_messages",
    "messages_in_last_hour",
]


# --- users ---------------------------------------------------------------


def create_user(email, email_normalized, password_hash):
    with unique_guard():
        return query_one(
            """
            INSERT INTO users (email, email_normalized, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id, email, created_at
            """,
            (email, email_normalized, password_hash),
        )


def get_user_by_email(email_normalized):
    return query_one(
        "SELECT id, email, password_hash FROM users WHERE email_normalized = %s",
        (email_normalized,),
    )


def get_user_by_id(user_id):
    return query_one("SELECT id, email FROM users WHERE id = %s", (user_id,))


def touch_login(user_id):
    execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))


# --- conversations -------------------------------------------------------


def list_conversations(user_id, limit=200):
    return query_all(
        """
        SELECT id, title, updated_at
        FROM conversations
        WHERE user_id = %s
        ORDER BY updated_at DESC
        LIMIT %s
        """,
        (user_id, limit),
    )


def create_conversation(user_id, title=None):
    return query_one(
        """
        INSERT INTO conversations (user_id, title)
        VALUES (%s, %s)
        RETURNING id, title, created_at, updated_at
        """,
        (user_id, title),
    )


def get_conversation(user_id, conversation_id):
    """Return the conversation only if this user owns it, else None."""
    return query_one(
        """
        SELECT id, title, created_at, updated_at
        FROM conversations
        WHERE id = %s AND user_id = %s
        """,
        (conversation_id, user_id),
    )


def rename_conversation(user_id, conversation_id, title):
    return execute(
        """
        UPDATE conversations
        SET title = %s, updated_at = now()
        WHERE id = %s AND user_id = %s
        """,
        (title, conversation_id, user_id),
    )


def delete_conversation(user_id, conversation_id):
    # Messages go with it via ON DELETE CASCADE.
    return execute(
        "DELETE FROM conversations WHERE id = %s AND user_id = %s",
        (conversation_id, user_id),
    )


# --- messages ------------------------------------------------------------


def list_messages(user_id, conversation_id):
    return query_all(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id = %s AND user_id = %s
        ORDER BY id
        """,
        (conversation_id, user_id),
    )


def add_message(user_id, conversation_id, role, content):
    """Insert a message and bump the conversation's updated_at in one transaction."""
    with transaction() as cur:
        cur.execute(
            """
            INSERT INTO messages (conversation_id, user_id, role, content)
            SELECT %s, %s, %s, %s
            WHERE EXISTS (
                SELECT 1 FROM conversations WHERE id = %s AND user_id = %s
            )
            RETURNING id, created_at
            """,
            (conversation_id, user_id, role, content, conversation_id, user_id),
        )
        row = cur.fetchone()
        if row is None:
            # The EXISTS guard failed: the conversation is missing or not theirs.
            return None
        cur.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        return row


def context_messages(user_id, conversation_id, limit):
    """The most recent `limit` turns, oldest first, for replay to the model."""
    rows = query_all(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = %s AND user_id = %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (conversation_id, user_id, limit),
    )
    return list(reversed(rows))


def messages_in_last_hour(user_id):
    row = query_one(
        """
        SELECT count(*) AS n
        FROM messages
        WHERE user_id = %s AND role = 'user' AND created_at > now() - interval '1 hour'
        """,
        (user_id,),
    )
    return row["n"] if row else 0
