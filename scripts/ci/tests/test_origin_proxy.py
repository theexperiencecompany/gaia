"""lib/origin_proxy.py: a crawler asking for the site over HTTPS reaches the local origin, nothing else."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import subprocess
import sys
import threading
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "lib" / "origin_proxy.py"


class _EchoHost(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = f"{self.headers['Host']} {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


@contextmanager
def _proxy(tmp_path: Path, *extra: str) -> Iterator[tuple[int, Path]]:
    """Yield the proxy's port and CA, fronting an origin that echoes the Host and path it was sent."""
    origin = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHost)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    port_file = tmp_path / "port"
    proc = subprocess.Popen(
        [
            sys.executable, "-I", str(SCRIPT), "--site", "https://heygaia.test",
            "--origin", f"http://127.0.0.1:{origin.server_address[1]}",
            "--cert-dir", str(tmp_path / "certs"), "--port-file", str(port_file), *extra,
        ]
    )  # fmt: skip
    try:
        for _ in range(100):
            if port_file.exists() and port_file.read_text():
                break
            assert proc.poll() is None, "the proxy exited before it listened"
            time.sleep(0.1)
        yield int(port_file.read_text()), tmp_path / "certs/ca.pem"
    finally:
        proc.kill()
        proc.wait()
        origin.shutdown()


@pytest.fixture
def proxy(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    with _proxy(tmp_path) as running:
        yield running


def _get_all(port: int, ca: Path, host: str, paths: list[str]) -> list[tuple[int, str]]:
    """GET each path in turn on one kept-alive connection."""
    conn = http.client.HTTPSConnection(
        "127.0.0.1", port, context=ssl.create_default_context(cafile=ca), timeout=10
    )
    conn.set_tunnel(host, 443)
    answers = []
    try:
        for path in paths:
            conn.request("GET", path)
            resp = conn.getresponse()
            answers.append((resp.status, resp.read().decode()))
        return answers
    finally:
        conn.close()


def _get(port: int, ca: Path, host: str) -> tuple[int, str]:
    return _get_all(port, ca, host, ["/about"])[0]


@pytest.mark.parametrize("host", ["heygaia.test", "www.heygaia.test"])
def test_the_site_is_served_from_the_origin_under_its_own_host(
    proxy: tuple[int, Path], host: str
) -> None:
    port, ca = proxy
    assert _get(port, ca, host) == (200, f"{host} /about")


def test_any_other_host_is_refused(proxy: tuple[int, Path]) -> None:
    port, ca = proxy
    with pytest.raises(OSError, match="403"):
        _get(port, ca, "example.com")


def test_a_plain_http_request_is_refused(proxy: tuple[int, Path]) -> None:
    port, _ = proxy
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "http://heygaia.test/about")
    assert conn.getresponse().status == 403


def test_with_a_sitemap_it_answers_the_sitemap_and_forwards_everything_else(tmp_path: Path) -> None:
    listed = tmp_path / "pages.txt"
    listed.write_text("https://heygaia.test/compare/a\nhttps://heygaia.test/de?x=1&y=2\n")
    with _proxy(tmp_path, "--sitemap", str(listed)) as (port, ca):
        about, sitemap = _get_all(port, ca, "heygaia.test", ["/about", "/sitemap.xml"])
        assert about == (200, "heygaia.test /about")
        assert sitemap[0] == 200
        assert "<loc>https://heygaia.test/compare/a</loc>" in sitemap[1]
        assert "<loc>https://heygaia.test/de?x=1&amp;y=2</loc>" in sitemap[1]
        assert sitemap[1].count("<loc>") == 2
        assert _get_all(port, ca, "heygaia.test", ["/sitemap/0.xml"]) == [
            (200, "heygaia.test /sitemap/0.xml")
        ]
