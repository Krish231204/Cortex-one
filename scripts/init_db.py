#!/usr/bin/env python3
"""Create the CortexOne schema. Idempotent — safe to re-run.

    python scripts/init_db.py

Reads DATABASE_URL from the environment or .env. Point it at the *direct*
(non-pooled) Neon endpoint if you hit issues; DDL through PgBouncer is fine but
the direct endpoint gives clearer errors.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from cortexone.db import init_schema  # noqa: E402


def main():
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    init_schema(conninfo=url)
    print("Schema applied.")


if __name__ == "__main__":
    main()
