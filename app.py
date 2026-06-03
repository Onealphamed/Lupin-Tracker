"""Entry point — kept thin so gunicorn's `app:app` import stays cheap.

Everything else lives in the `lupin` package (one module per concern).
The Flask app is built by `lupin.create_app()`, so tests can spin up
fresh instances without leaking state across runs.
"""
from __future__ import annotations

import os

from lupin import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5003")), debug=True)
