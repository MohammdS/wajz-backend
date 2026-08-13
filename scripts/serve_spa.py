"""Serve a built single-page app with history fallback for local demos."""

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class SpaHandler(SimpleHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        if code == 404:
            self.path = "/index.html"
            return self.do_GET()
        return super().send_error(code, message, explain)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    handler = partial(SpaHandler, directory=str(root))
    ThreadingHTTPServer((args.host, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
