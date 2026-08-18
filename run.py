"""Development entry point.

Run with:  python run.py
The server is threaded so live scan output streams while other requests are served.
"""

from __future__ import annotations

import os

from app import create_app

app = create_app()


def main() -> None:
    host = os.environ.get("WST_HOST", "127.0.0.1")
    port = int(os.environ.get("WST_PORT", "5000"))
    debug = os.environ.get("WST_DEBUG", "0") == "1"
    try:
        app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=debug)
    except OSError as exc:
        raise SystemExit(
            f"Could not bind to {host}:{port} ({exc}). Set WST_PORT to a free port and try again."
        ) from exc


if __name__ == "__main__":
    main()
