"""End-to-end smoke test against a throwaway local HTTP server.

Usage:  python scripts/smoke_test.py
Starts a local target on 127.0.0.1:8099, runs one ffuf scan and one Katana crawl
through the application API and prints the parsed results.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services.process_manager import process_manager

PORT = 8099
PAGE = b"""<html><body>
<a href="/admin/">admin</a><a href="/api/v1/users">users</a>
<a href="/login.php">login</a><a href="/assets/app.js">app.js</a>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        known = {"/", "/admin/", "/api/v1/users", "/login.php", "/assets/app.js", "/api"}
        status = 200 if self.path.rstrip("/") + "/" in known or self.path in known else 404
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE if status == 200 else b"not found")

    def log_message(self, *args):
        pass


def wait_for(app, scan_id, timeout=90):
    from app.models import Scan, db

    deadline = time.time() + timeout
    while time.time() < deadline:
        with app.app_context():
            scan = db.session.get(Scan, scan_id)
            if scan.status not in ("RUNNING", "QUEUED"):
                return scan.to_dict()
        time.sleep(1)
    raise SystemExit(f"scan {scan_id} did not finish in {timeout}s")


def main() -> None:
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    app = create_app("config.TestConfig")
    client = app.test_client()
    base = f"http://127.0.0.1:{PORT}"

    ffuf = client.post(
        "/api/scans",
        json={
            "tool": "ffuf",
            "config": {
                "url": f"{base}/FUZZ",
                "wordlist": "directories/common-directories.txt",
                "threads": 20,
                "match_status": "200,301,302,403",
            },
        },
    )
    print("ffuf start:", ffuf.status_code, ffuf.get_json().get("error", ""))
    ffuf_id = ffuf.get_json()["id"]
    print("ffuf command:", ffuf.get_json()["command_string"])
    print("ffuf final:", wait_for(app, ffuf_id)["status"])
    print("ffuf results:", client.get(f"/api/scans/{ffuf_id}/results").get_json()["results"])

    katana = client.post(
        "/api/scans",
        json={"tool": "katana", "config": {"urls": base, "depth": 2, "timeout": 5}},
    )
    print("katana start:", katana.status_code, katana.get_json().get("error", ""))
    katana_id = katana.get_json()["id"]
    print("katana command:", katana.get_json()["command_string"])
    print("katana final:", wait_for(app, katana_id)["status"])
    print(
        "katana results:",
        [row["url"] for row in client.get(f"/api/scans/{katana_id}/results").get_json()["results"]],
    )

    # invalid configuration + stop handling
    bad = client.post("/api/scans", json={"tool": "ffuf", "config": {"url": base}})
    print("invalid config:", bad.status_code, bad.get_json())
    missing = client.post(
        "/api/scans",
        json={"tool": "ffuf", "config": {"url": f"{base}/FUZZ", "wordlist": "custom/nope.txt"}},
    )
    print("missing wordlist:", missing.status_code, missing.get_json())

    long_scan = client.post(
        "/api/scans",
        json={
            "tool": "katana",
            "config": {"urls": base, "depth": 10, "crawl_duration": "60s", "delay": 1},
        },
    ).get_json()
    time.sleep(3)
    stopped = client.post(f"/api/scans/{long_scan['id']}/stop")
    print("stop:", stopped.status_code, wait_for(app, long_scan["id"], timeout=30)["status"])

    process_manager.stop_all()
    server.shutdown()


if __name__ == "__main__":
    main()
