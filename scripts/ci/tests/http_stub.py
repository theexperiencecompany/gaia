"""A local HTTP server with fixed routes, for driving the post-deploy scripts for real."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

Response = tuple[int, dict[str, str], str]
#: A path answers one response every time, or a list of them in turn, the last one repeating.
Routes = dict[str, Response | list[Response]]


@contextmanager
def serve(
    routes: Routes,
    posts: list[tuple[str, bytes]] | None = None,
    gets: list[str] | None = None,
) -> Iterator[str]:
    """Answer each path (query string included) from routes for the block; record POST and PUT bodies in posts, GET paths in gets."""
    served: dict[str, int] = {}
    lock = threading.Lock()

    def answer(path: str) -> Response:
        route = routes.get(path, (404, {}, ""))
        if not isinstance(route, list):
            return route
        with lock:
            index = served.get(path, 0)
            served[path] = index + 1
        return route[min(index, len(route) - 1)]

    class Handler(BaseHTTPRequestHandler):
        def _reply(self) -> None:
            status, headers, body = answer(self.path)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self) -> None:
            if gets is not None:
                gets.append(self.path)
            self._reply()

        def do_POST(self) -> None:
            if posts is not None:
                length = int(self.headers.get("Content-Length") or 0)
                posts.append((self.path, self.rfile.read(length)))
            self._reply()

        do_PUT = do_POST

        def log_message(self, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
