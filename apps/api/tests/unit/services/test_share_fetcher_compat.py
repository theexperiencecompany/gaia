"""Composio fetcher compatibility: our share responses satisfy their fetcher.

Uses Composio's real ``_fetch_file_from_url`` (no mocks on their side) against
a local socket server emitting exactly what the share route serves: a direct
200 with Content-Type and bytes. Also pins the constraint that killed the
redirect design — their fetcher raises on 301/302/303/307/308, so the token
route must serve bytes itself, never 302 elsewhere.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

CONTENT = b"%PDF-1.4 compat-proof"


class _DirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = CONTENT
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


class _RedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/api/v1/files/s/tok/report.pdf")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def _direct_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _DirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        # Real minted shape: filename in path (basename derivation), bearer in
        # query (redacted by Composio's error sanitizer, absent from our logs).
        yield f"http://{host}:{port}/api/v1/files/s/report.pdf?token=some-token"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def _redirect_url() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/api/v1/files/s/report.pdf?token=some-token"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_composio_fetcher_consumes_direct_share_response(_direct_url: str) -> None:
    from composio.core.models._files import _fetch_file_from_url

    filename, content, mimetype = _fetch_file_from_url(_direct_url)
    assert filename == "report.pdf"  # derived from the URL basename
    assert content == CONTENT
    assert mimetype == "application/pdf"  # read off our Content-Type


def test_composio_fetcher_rejects_redirect(_redirect_url: str) -> None:
    from composio.core.models._files import (
        ErrorUploadingFile,
        _fetch_file_from_url,
    )

    with pytest.raises(ErrorUploadingFile, match="redirect"):
        _fetch_file_from_url(_redirect_url)
