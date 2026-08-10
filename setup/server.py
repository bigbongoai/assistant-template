#!/usr/bin/env python3
"""
Local onboarding server for the assistant workspace.

Claude starts this, tells the person to open the printed URL, and waits for
setup/answers.json to appear. Binds to 127.0.0.1 only — never the network —
because the form collects R2 credentials.

Prints the URL on the first line of stdout, then serves until stopped.
"""
import http.server
import json
import os
import socketserver
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANSWERS = HERE / "answers.json"
FIRST_PORT = int(os.environ.get("PORT", "8899"))


ROOT = HERE.parent
CONFIG = ROOT / "assistant.config.json"
CONFIG_LOCAL = ROOT / "assistant.config.local.json"


def load_config():
    """Committed defaults, overlaid with the org file if one was dropped in.

    Credentials are stripped before this reaches the browser — the form only
    needs to know they exist, not what they are.
    """
    def read(p):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return {}

    cfg = read(CONFIG)
    for key, val in read(CONFIG_LOCAL).items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key] = {**cfg[key], **val}
        else:
            cfg[key] = val

    storage = cfg.get("storage")
    if isinstance(storage, dict) and storage.pop("credentials", None):
        storage["credentials_provided"] = True
    cfg.pop("_comment", None)
    return cfg


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def do_GET(self):
        # The form adapts itself from this: with no org overlay present it
        # simply doesn't offer company options.
        if self.path.rstrip("/") == "/config.json":
            body = json.dumps(load_config()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/submit":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self.send_error(400, "expected JSON")
            return

        ANSWERS.write_text(json.dumps(payload, indent=2))
        ANSWERS.chmod(0o600)  # may contain R2 keys

        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # No caching, so a re-run never serves a stale form.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass  # keep Claude's terminal readable


class Server(socketserver.ThreadingTCPServer):
    # Threaded on purpose: browsers hold keep-alive connections open, and a
    # single-threaded server would then refuse to answer anything else —
    # including the form's POST — until that connection died.
    allow_reuse_address = True
    daemon_threads = True


def main():
    # answers.json is the completion signal — clear any stale one first.
    ANSWERS.unlink(missing_ok=True)

    for port in range(FIRST_PORT, FIRST_PORT + 12):
        try:
            with Server(("127.0.0.1", port), Handler) as httpd:
                print(f"http://127.0.0.1:{port}", flush=True)
                httpd.serve_forever()
            return
        except OSError:
            continue  # port busy, try the next

    print("could not bind a free port", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
