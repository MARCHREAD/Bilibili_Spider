"""Serve the patched click asset to the real browser over http://127.0.0.1.

The page loads https://static.geetest.com/static/js/click.3.1.2.js; an initScript in
the browser rewrites that src to this server, so the REAL page (real fingerprint, real
DOM, real events) runs our instrumented asset and exposes __gt3Widget / __gt3Plain.
127.0.0.1 counts as a trustworthy origin, so an https page may load it without mixed
content blocking.

usage: python serve_patched.py [port]
"""
from __future__ import annotations

import http.server
import pathlib
import socketserver
import sys

TASK = pathlib.Path(__file__).resolve().parent
CACHE = TASK / "cache"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(CACHE), **kw)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[serve] %s %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        print(f"serving {CACHE} on http://127.0.0.1:{PORT}/", flush=True)
        httpd.serve_forever()
