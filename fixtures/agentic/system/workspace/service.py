#!/usr/bin/env python3
"""quoteservice - demo HTTP service (fixture program; do not modify)."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

VALID_LOG_LEVELS = ("debug", "info", "warning", "error")


def load_config():
    cfg = json.loads(Path("config/service.json").read_text())
    level = cfg.get("log_level")
    if level not in VALID_LOG_LEVELS:
        raise SystemExit(f"FATAL: invalid log_level: {level!r} "
                         f"(valid: {', '.join(VALID_LOG_LEVELS)})")
    return cfg


def load_quotes(path):
    return json.loads(Path(path).read_text())


class Handler(BaseHTTPRequestHandler):
    quotes = []

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok", "quotes": len(self.quotes)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def main():
    cfg = load_config()
    Handler.quotes = load_quotes(cfg["data_file"])
    HTTPServer(("127.0.0.1", int(cfg["port"])), Handler).serve_forever()


if __name__ == "__main__":
    main()
