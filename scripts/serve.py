#!/usr/bin/env python3
"""serve.py — minimal static server + /api/likes endpoint (public build).

Replaces `python3 -m http.server 8000`. Serves the repo root as static
files AND exposes one tiny JSON API:

    GET  /api/likes  -> {"ok": true, "count": N}
    POST /api/likes  -> {"ok": true, "count": N+1}   (rate-limited per /24)

The like counter lives in ~/.ct_likes.json (outside the web root). When the
site is hosted on GitHub Pages (no backend), the frontend's like widget
gracefully falls back to showing "—" — no other server-side functionality
is needed for the public build.

Run:  python3 scripts/serve.py 8000
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Defence-in-depth: even if a future maintainer drops a counter file into the
# repo, the static handler should refuse to serve it.
_FORBIDDEN_NAMES = {"likes.json", ".ct_likes.json"}


# Likes counter — single integer kept in a JSON file outside the web root.
# Crude per-IP-block burst limit prevents trivial spam; the frontend's
# per-page-load `liked` flag is the primary one-click gate.
def _likes_path() -> Path:
    p = Path(os.environ.get("CT_LIKES_FILE") or (Path.home() / ".ct_likes.json"))
    return p.resolve()


_LIKES_LOCK_RECENT: dict[str, float] = {}   # ip_block -> monotonic ts of last like
_LIKES_THROTTLE_SECONDS = 2.0


def _read_likes_count() -> int:
    p = _likes_path()
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get("count", 0))
    except Exception:
        return 0


def _write_likes_count(n: int) -> None:
    p = _likes_path()
    try:
        p.relative_to(ROOT)
        sys.stderr.write(f"[serve] REFUSING to write likes to {p}: inside web root.\n")
        return
    except ValueError:
        pass
    p.write_text(json.dumps({"count": int(n)}), encoding="utf-8")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[serve] {self.address_string()} {fmt % args}\n")

    def do_GET(self):
        if self.path.split("?")[0] == "/api/likes":
            return self._json(200, {"ok": True, "count": _read_likes_count()})
        name = self.path.lstrip("/").split("?")[0].rsplit("/", 1)[-1]
        if name in _FORBIDDEN_NAMES:
            sys.stderr.write(f"[serve] blocked GET of sensitive file: {self.path}\n")
            self.send_error(403, "forbidden")
            return
        super().do_GET()

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/likes":
            return self._handle_like()
        self.send_error(404, "Not Found")

    def _handle_like(self) -> None:
        ip = self.client_address[0] if self.client_address else ""
        if ":" in ip:
            ip_block = ":".join(ip.split(":")[:4]) + "::/64"
        else:
            ip_block = ".".join(ip.split(".")[:3]) + ".0/24"
        now = time.monotonic()
        last = _LIKES_LOCK_RECENT.get(ip_block, 0.0)
        if now - last < _LIKES_THROTTLE_SECONDS:
            return self._json(200, {"ok": True, "count": _read_likes_count(), "throttled": True})

        try:
            current = _read_likes_count()
            new_count = current + 1
            _write_likes_count(new_count)
            _LIKES_LOCK_RECENT[ip_block] = now
            sys.stderr.write(f"[serve] like #{new_count} from {ip_block}\n")
            return self._json(200, {"ok": True, "count": new_count})
        except Exception as e:
            sys.stderr.write(f"[serve] like failed: {e}\n")
            return self._json(500, {"ok": False, "error": "could not record like"})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    addr = os.environ.get("CT_BIND", "0.0.0.0")
    sys.stderr.write(f"[serve] root={ROOT} listening on http://{addr}:{port}\n")
    ThreadingHTTPServer((addr, port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
