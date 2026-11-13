"""lib/origin_proxy.py: a crawler asking for the site over HTTPS reaches the local origin, nothing else."""

from __future__ import annotations

from collections.abc import Iterator
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
    def do_GET(self) -> None:
        body = f"{self.headers['Host']} {self.path}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


@pytest.fixture
def proxy(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    """Return the proxy's port and CA, fronting an origin that echoes the Host it was sent."""
    origin = ThreadingHTTPServer(("127.0.0.1", 0), _EchoHost)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    port_file = tmp_path / "port"
    proc = subprocess.Popen(
        [
            sys.executable, "-I", str(SCRIPT), "--site", "https://heygaia.test",
            "--origin", f"http://127.0.0.1:{origin.server_address[1]}",
            "--cert-dir", str(tmp_path / "certs"), "--port-file", str(port_file),
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


def _get(port: int, ca: Path, host: str) -> tuple[int, str]:
    conn = http.client.HTTPSConnection(
        "127.0.0.1", port, context=ssl.create_default_context(cafile=ca), timeout=10
    )
    conn.set_tunnel(host, 443)
    try:
        conn.request("GET", "/about")
        resp = conn.getresponse()
        return resp.status, resp.read().decode()
    finally:
        conn.close()


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
