"""Vercel entrypoint.

The Python runtime looks for a top-level `app` in app.py, so the whole Flask
application builds into a single Vercel Function from this file.
"""

import os

from cortexone import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5050)), debug=False)
