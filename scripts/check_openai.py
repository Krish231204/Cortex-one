#!/usr/bin/env python3
"""Check that OPENAI_API_KEY works, and list the models it can reach.

    python scripts/check_openai.py

Reads the key from .env (gitignored) or the environment. Never takes the key
as an argument, so it cannot end up in shell history, and never prints it.

Use this to tell apart the three failures that all surface in the app as
"The model request failed": a bad key, an account with no credit, and a model
id that does not exist.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from openai import (  # noqa: E402
    APIConnectionError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)


def main():
    load_dotenv()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        sys.exit("OPENAI_API_KEY is not set. Add it to .env (which is gitignored).")

    print(f"Using a key ending {key[-4:]} ({len(key)} chars).\n")

    client = OpenAI(api_key=key, base_url=os.environ.get("OPENAI_BASE_URL") or None)

    try:
        models = sorted(m.id for m in client.models.list())
    except AuthenticationError:
        sys.exit("Key rejected. It is wrong, revoked, or has a stray space.")
    except RateLimitError:
        sys.exit(
            "Key is valid but the account is out of quota. Add billing at "
            "platform.openai.com — no model name will fix this."
        )
    except APIConnectionError as exc:
        sys.exit(f"Could not reach the API: {exc}")

    chat = [m for m in models if m.startswith("gpt") and "realtime" not in m]
    print(f"{len(models)} models available. Chat-capable ones:\n")
    for model_id in chat:
        print(f"  {model_id}")

    configured = os.environ.get("OPENAI_MODEL", "gpt-5.6")
    title = os.environ.get("OPENAI_TITLE_MODEL", "gpt-5.6-luna")
    print()
    for label, value in (("OPENAI_MODEL", configured), ("OPENAI_TITLE_MODEL", title)):
        mark = "OK " if value in models else "!! "
        note = "" if value in models else "  <- not in your account's list"
        print(f"{mark}{label}={value}{note}")


if __name__ == "__main__":
    main()
