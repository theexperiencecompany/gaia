"""A local HTTP server with fixed routes, for driving the post-deploy scripts for real."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

Routes = dict[str, tuple[int, dict[str, str], str]]


@contextmanager
def serve(routes: Routes, posts: list[tuple[str, bytes]] | None = None) -> Iterator[str]:
    """Answer each path (query string included) from routes for the block; record POST bodies in posts."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            status, headers, body = routes.get(self.path, (404, {}, ""))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self) -> None:
            self._reply()

        def do_POST(self) -> None:
            if posts is not None:
                posts.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self._reply()

        def log_message(self, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
