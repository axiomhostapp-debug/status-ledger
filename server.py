"""Loopback-only, read-only JSON demo server; mutations use the local CLI."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit
from ledger import Ledger
from dashboard import render


def handler(database):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            store = Ledger(database)
            try:
                if path == "/":
                    body = render(store).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/status":
                    result, code = store.status(), 200
                elif path.startswith("/api/incidents/"):
                    try:
                        result, code = store.get(path.removeprefix("/api/incidents/")), 200
                    except KeyError:
                        result, code = {"error": "not found"}, 404
                else:
                    result, code = {"error": "not found"}, 404
            finally:
                store.close()
            body = json.dumps(result).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="demo.sqlite3")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    HTTPServer(("127.0.0.1", args.port), handler(args.db)).serve_forever()
