"""Serve the static site locally (stdlib only, no dependencies)."""
from __future__ import annotations

import functools
import http.server
import socketserver
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {SITE} at http://127.0.0.1:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
