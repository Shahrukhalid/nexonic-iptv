#!/usr/bin/env python3
"""Serve the Nexonic IPTV playlists to apps that log in with a server URL, username and password (Xtream Codes).

    python scripts/xtream_server.py                         # http://127.0.0.1:8080, login nexonic / free
    python scripts/xtream_server.py --host 0.0.0.0 --port 8080 --public-url http://192.168.1.20:8080

In the app choose "Xtream Codes" (or "Login with Xtream"), enter the server URL, username ``nexonic`` and password
``free``. Channels, countries and the free films and series come from ``playlists/``; run ``git pull`` to update them
(the server reloads them by itself). Streams are redirects to the broadcasters' own URLs; no video passes through here.
"""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import _bootstrap  # noqa: F401

from nexonic.records import ROOT
from nexonic.xtream import DEFAULT_PASSWORD, DEFAULT_USER, Gateway


def make_handler(gateway: Gateway):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NexonicXtream/1.0"

        def _answer(self, head_only: bool = False) -> None:
            parts = urlsplit(self.path)
            status, headers, body = gateway.handle(parts.path, parts.query)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._answer()

        def do_POST(self) -> None:  # noqa: N802 (some apps POST their login)
            n = min(int(self.headers.get("Content-Length") or 0), 4096)
            form = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            if form and "?" not in self.path:
                self.path = f"{self.path}?{form}"
            self._answer()

        def do_HEAD(self) -> None:  # noqa: N802
            self._answer(head_only=True)

        def log_message(self, fmt: str, *args) -> None:  # keep logins out of the logs
            first = urlsplit(self.path).path.split("/")[1:2]
            sys.stderr.write(f"{self.command} /{first[0] if first else ''} -> {args[1] if len(args) > 1 else ''}\n")

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow other devices on your network")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--public-url", help="address the apps use, e.g. http://192.168.1.20:8080 (default: host:port)")
    ap.add_argument("--username", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASSWORD)
    ap.add_argument("--playlists", type=Path, default=ROOT / "playlists")
    args = ap.parse_args(argv)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host  # noqa: S104 (only compared, never bound here)
    public = args.public_url or f"http://{shown}:{args.port}"
    gateway = Gateway(args.playlists, public, args.username, args.password)
    cat = gateway.catalog
    print(f"Nexonic IPTV Xtream gateway on {public}")
    print(f"  username: {args.username}   password: {args.password}")
    print(f"  {len(cat.live)} channels, {len(cat.movies)} films, {len(cat.episodes)} series episodes")
    print(
        "  M3U for this login: " + f"{public}/get.php?username={args.username}&password={args.password}&type=m3u_plus"
    )
    ThreadingHTTPServer((args.host, args.port), make_handler(gateway)).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
