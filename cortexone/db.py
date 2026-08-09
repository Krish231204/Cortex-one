"""Postgres access.

Two things drive the shape of this module:

1. Serverless reuse. Vercel's Fluid compute keeps warm instances around and
   reuses them across invocations, so a module-level pool is both safe and
   worth having — the first request pays for the TCP+TLS handshake and the
   rest reuse it.

2. Neon's pooled endpoint runs PgBouncer in *transaction* pooling mode. Server
   side prepared statements do not survive that, and psycopg3 creates them
   automatically after a few executions, so `prepare_threshold=None` is
   mandatory. Without it you get sporadic "prepared statement already exists"
   errors under load that are miserable to debug.
"""

import atexit
import os
import threading
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool = None
_lock = threading.Lock()


def _build_pool(conninfo):
    pool = ConnectionPool(
        conninfo,
        min_size=0,
        # A single warm instance handles a handful of concurrent requests; the
        # cap keeps one instance from monopolising the PgBouncer client slots.
        max_size=int(os.environ.get("DB_POOL_MAX", "5")),
        max_idle=60,
        timeout=10,
        kwargs={
            "row_factory": dict_row,
            "prepare_threshold": None,
            "autocommit": False,
        },
        open=False,
        name="cortexone",
    )
    pool.open()
    atexit.register(pool.close)
    return pool


def get_pool():
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                from flask import current_app

                _pool = _build_pool(current_app.config["cortexone"].database_url)
    return _pool


@contextmanager
def transaction():
    """Yield a cursor inside a transaction; commits on success, rolls back on error."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur


def query_all(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def query_one(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def execute(sql, params=()):
    with transaction() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def init_schema(conninfo=None):
    """Apply migrations/001_init.sql. Idempotent; called by scripts, not by requests."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "migrations", "001_init.sql"), encoding="utf-8") as fh:
        ddl = fh.read()

    if conninfo:
        with psycopg.connect(conninfo, prepare_threshold=None) as conn:
            conn.execute(ddl)
            conn.commit()
    else:
        with transaction() as cur:
            cur.execute(ddl)


class UniqueViolation(Exception):
    """Raised when an insert collides with a unique constraint."""


@contextmanager
def unique_guard():
    try:
        yield
    except psycopg.errors.UniqueViolation as exc:
        raise UniqueViolation(str(exc)) from exc
