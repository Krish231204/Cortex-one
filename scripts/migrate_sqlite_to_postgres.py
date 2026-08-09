#!/usr/bin/env python3
"""Move the old SQLite chat history into Postgres, assigned to one account.

The old database had no concept of a user — every row sat in one global `chats`
table keyed only by a random session_id. This assigns all of it to a single
existing account, so register through the web UI first, then run:

    python scripts/migrate_sqlite_to_postgres.py --email you@example.com

Each old row held a user message and its reply in one record; that becomes two
messages, preserving the original timestamp.

Re-running is safe: conversations already imported are skipped, tracked by the
old session_id recorded in the conversation title mapping table below.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS legacy_session_map (
    legacy_session_id TEXT PRIMARY KEY,
    conversation_id   UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    imported_at       TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def parse_ts(raw):
    """SQLite stored naive local strings; treat them as UTC."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return datetime.now(timezone.utc)


def read_legacy(path):
    """Group legacy rows into {session_id: {"name": str, "rows": [...]}}."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT session_id, session_name, user_message, response, timestamp
            FROM chats
            ORDER BY session_id, id
            """
        ).fetchall()
    finally:
        conn.close()

    sessions = {}
    for row in rows:
        sid = row["session_id"] or "orphaned-legacy-rows"
        bucket = sessions.setdefault(sid, {"name": None, "rows": []})
        if row["session_name"] and not bucket["name"]:
            bucket["name"] = row["session_name"]
        bucket["rows"].append(row)
    return sessions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing account to import into")
    parser.add_argument("--sqlite", default="chat_history.db.local", help="Old SQLite file")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("DATABASE_URL is not set.")
    if not os.path.exists(args.sqlite):
        sys.exit(f"No such file: {args.sqlite}")

    sessions = read_legacy(args.sqlite)
    total_rows = sum(len(s["rows"]) for s in sessions.values())
    print(f"Found {len(sessions)} legacy sessions / {total_rows} exchanges in {args.sqlite}.")

    with psycopg.connect(url, row_factory=dict_row, prepare_threshold=None) as conn:
        conn.execute(TRACKING_DDL)

        user = conn.execute(
            "SELECT id, email FROM users WHERE email_normalized = %s",
            (args.email.strip().lower(),),
        ).fetchone()
        if user is None:
            sys.exit(
                f"No account for {args.email}. Register through the web UI first, "
                f"then re-run this script."
            )

        already = {
            r["legacy_session_id"]
            for r in conn.execute("SELECT legacy_session_id FROM legacy_session_map").fetchall()
        }

        imported_conversations = 0
        imported_messages = 0

        for sid, bucket in sessions.items():
            if sid in already:
                print(f"  skip {sid[:8]}… (already imported)")
                continue
            if args.dry_run:
                print(f"  would import {sid[:8]}… — {len(bucket['rows'])} exchanges")
                continue

            first_ts = parse_ts(bucket["rows"][0]["timestamp"])
            last_ts = parse_ts(bucket["rows"][-1]["timestamp"])

            conv = conn.execute(
                """
                INSERT INTO conversations (user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (user["id"], bucket["name"] or "Imported chat", first_ts, last_ts),
            ).fetchone()
            conv_id = conv["id"]

            for row in bucket["rows"]:
                ts = parse_ts(row["timestamp"])
                for role, content in (("user", row["user_message"]), ("assistant", row["response"])):
                    if not content:
                        continue
                    conn.execute(
                        """
                        INSERT INTO messages (conversation_id, user_id, role, content, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (conv_id, user["id"], role, content, ts),
                    )
                    imported_messages += 1

            conn.execute(
                "INSERT INTO legacy_session_map (legacy_session_id, conversation_id) VALUES (%s, %s)",
                (sid, conv_id),
            )
            imported_conversations += 1
            print(f"  imported {sid[:8]}… as {conv_id}")

        if args.dry_run:
            conn.rollback()
            print("\nDry run — nothing written.")
        else:
            conn.commit()
            print(
                f"\nImported {imported_conversations} conversations "
                f"({imported_messages} messages) into {user['email']}."
            )


if __name__ == "__main__":
    main()
