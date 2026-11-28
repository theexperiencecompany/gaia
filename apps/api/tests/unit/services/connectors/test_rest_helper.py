"""The REST helper run as the runner runs it, against a local HTTPS server that records every request."""

import base64
from collections.abc import Iterator
from dataclasses import dataclass, field
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import subprocess
import sys
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import pytest

from app.services.connectors.rest_helper import (
    ACCOUNT_HEADER_ENV,
    AUTH_HEADER_ENV,
    AUTH_QUERY_ENV,
    AUTH_TEMPLATE_ENV,
    BASE_URL_ENV,
    REST_HELPER_SOURCE,
    SECRET_ENV,
)

_SECRET = "sk-live-0123456789"  # pragma: allowlist secret
_LOCALHOST = "127.0.0.1"


@dataclass
class _Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass
class _Server:
    base_url: str
    cert_file: Path
    seen: list[_Seen] = field(default_factory=list)


def _self_signed(tmp_path: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _LOCALHOST)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(_LOCALHOST))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_file, key_file


@pytest.fixture
def server(tmp_path: Path) -> Iterator[_Server]:
    cert_file, key_file = _self_signed(tmp_path)
    seen: list[_Seen] = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(_Seen(self.command, self.path, dict(self.headers), self.rfile.read(length)))
            if self.path.startswith("/v1/redirect"):
                self.send_response(302)
                self.send_header("Location", "https://evil.example.org/steal")
                self.end_headers()
                return
            status = 404 if self.path.startswith("/v1/missing") else 200
            payload = json.dumps({"path": self.path}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_DELETE = _answer

        def log_message(self, *args: object) -> None:
            del args

    httpd = ThreadingHTTPServer((_LOCALHOST, 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Server(f"https://{_LOCALHOST}:{httpd.server_address[1]}/v1", cert_file, seen)
    finally:
        httpd.shutdown()
        httpd.server_close()


def _helper(tmp_path: Path) -> Path:
    path = tmp_path / "gaia_rest.py"
    path.write_text(REST_HELPER_SOURCE)
    return path


def _run(
    tmp_path: Path,
    server: _Server,
    *args: str,
    auth: dict[str, str] | None = None,
    secret: str = _SECRET,
) -> subprocess.CompletedProcess[str]:
    env = {
        BASE_URL_ENV: server.base_url,
        SECRET_ENV: secret,
        AUTH_TEMPLATE_ENV: "Bearer {secret}",
        "SSL_CERT_FILE": str(server.cert_file),
        **(auth if auth is not None else {AUTH_HEADER_ENV: "Authorization"}),
    }
    return subprocess.run(
        [sys.executable, "-I", str(_helper(tmp_path)), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_a_get_sends_the_key_in_the_auth_header_and_prints_the_body(
    tmp_path: Path, server: _Server
) -> None:
    ran = _run(tmp_path, server, "GET", "/user", "--query", "per_page=5")

    assert ran.returncode == 0, ran.stderr
    assert json.loads(ran.stdout) == {"path": "/v1/user?per_page=5"}
    assert ran.stderr.strip() == "HTTP 200"
    assert [s.headers["Authorization"] for s in server.seen] == [f"Bearer {_SECRET}"]


def test_a_basic_auth_template_sends_the_pasted_user_and_password_base64_encoded(
    tmp_path: Path, server: _Server
) -> None:
    auth = {AUTH_HEADER_ENV: "Authorization", AUTH_TEMPLATE_ENV: "Basic {secret_base64}"}

    ran = _run(tmp_path, server, "GET", "/user", auth=auth)

    assert ran.returncode == 0, ran.stderr
    expected = base64.b64encode(_SECRET.encode()).decode()
    assert [s.headers["Authorization"] for s in server.seen] == [f"Basic {expected}"]


_ACCOUNT_AUTH = {
    AUTH_HEADER_ENV: "X-Algolia-API-Key",
    AUTH_TEMPLATE_ENV: "{secret_password}",
    ACCOUNT_HEADER_ENV: "X-Algolia-Application-Id",
}


def test_a_two_part_key_sends_its_account_half_and_key_half_in_their_own_headers(
    tmp_path: Path, server: _Server
) -> None:
    ran = _run(tmp_path, server, "GET", "/user", auth=_ACCOUNT_AUTH, secret=f"LATENCY:{_SECRET}")

    assert ran.returncode == 0, ran.stderr
    (seen,) = server.seen
    assert seen.headers["X-Algolia-API-Key"] == _SECRET
    assert seen.headers["X-Algolia-Application-Id"] == "LATENCY"


def test_the_account_header_cannot_be_set_by_the_call(tmp_path: Path, server: _Server) -> None:
    ran = _run(
        tmp_path,
        server,
        "GET",
        "/user",
        "--header",
        "X-Algolia-Application-Id:OTHER",
        auth=_ACCOUNT_AUTH,
        secret=f"LATENCY:{_SECRET}",
    )

    assert ran.returncode == 2
    assert server.seen == []


def test_query_auth_puts_the_key_in_its_parameter_not_a_header(
    tmp_path: Path, server: _Server
) -> None:
    ran = _run(tmp_path, server, "GET", "/user", auth={AUTH_QUERY_ENV: "api_key"})

    assert ran.returncode == 0, ran.stderr
    (seen,) = server.seen
    assert seen.path == "/v1/user?api_key=Bearer+sk-live-0123456789"
    assert "Authorization" not in seen.headers


def test_a_json_body_is_sent_with_its_content_type(tmp_path: Path, server: _Server) -> None:
    ran = _run(tmp_path, server, "post", "/items", "--json", '{"name": "x"}')

    assert ran.returncode == 0, ran.stderr
    (seen,) = server.seen
    assert (seen.method, seen.body) == ("POST", b'{"name": "x"}')
    assert seen.headers["Content-Type"] == "application/json"


def test_an_http_error_exits_22_with_its_body_and_status(tmp_path: Path, server: _Server) -> None:
    ran = _run(tmp_path, server, "GET", "/missing")

    assert ran.returncode == 22
    assert json.loads(ran.stdout) == {"path": "/v1/missing"}
    assert ran.stderr.strip() == "HTTP 404"


def test_a_redirect_is_never_followed_so_the_key_cannot_follow_it(
    tmp_path: Path, server: _Server
) -> None:
    ran = _run(tmp_path, server, "GET", "/redirect")

    assert ran.returncode == 22
    assert ran.stderr.strip() == "HTTP 302"
    assert len(server.seen) == 1


@pytest.mark.parametrize(
    "path",
    [
        "user",
        "//evil.example.org/x",
        "/https://evil.example.org/x",
        "/a\\b",
        "/@evil.example.org",
        "/user?token=x",
        "/user#frag",
        "/user name",
        "/user\r\nHost: evil.example.org",
        "/ünïcode",
    ],
)
def test_a_path_that_could_escape_the_base_host_is_refused_before_any_request(
    tmp_path: Path, server: _Server, path: str
) -> None:
    ran = _run(tmp_path, server, "GET", path)

    assert ran.returncode == 2
    assert ran.stdout == ""
    assert server.seen == []


@pytest.mark.parametrize(
    "header",
    ["Authorization: Bearer other", "authorization:x", "Host: evil.example.org", "Cookie: a=b"],
)
def test_a_header_that_overrides_auth_or_host_is_refused(
    tmp_path: Path, server: _Server, header: str
) -> None:
    ran = _run(tmp_path, server, "GET", "/user", "--header", header)

    assert ran.returncode == 2
    assert server.seen == []


def test_a_custom_auth_header_cannot_be_overridden_either(tmp_path: Path, server: _Server) -> None:
    ran = _run(
        tmp_path,
        server,
        "GET",
        "/user",
        "--header",
        "X-Api-Key: mine",
        auth={AUTH_HEADER_ENV: "X-API-Key"},
    )

    assert ran.returncode == 2
    assert server.seen == []


def test_the_auth_query_parameter_cannot_be_set_by_the_caller(
    tmp_path: Path, server: _Server
) -> None:
    ran = _run(
        tmp_path, server, "GET", "/user", "--query", "api_key=x", auth={AUTH_QUERY_ENV: "api_key"}
    )

    assert ran.returncode == 2
    assert server.seen == []


@pytest.mark.parametrize(
    "args",
    [
        ("TRACE", "/user"),
        ("GET",),
        ("GET", "/user", "--json", "{not json"),
        ("GET", "/user", "--query", "novalue"),
        ("GET", "/user", "--unknown"),
    ],
)
def test_a_malformed_call_is_a_usage_error(
    tmp_path: Path, server: _Server, args: tuple[str, ...]
) -> None:
    ran = _run(tmp_path, server, *args)

    assert ran.returncode == 2
    assert server.seen == []


@pytest.mark.parametrize(
    "base_url",
    ["http://127.0.0.1:1/v1", "https://user:pw@127.0.0.1:1/v1", "https://127.0.0.1:1/v1?x=1", ""],
)
def test_a_base_url_that_is_not_plain_https_is_refused(
    tmp_path: Path, server: _Server, base_url: str
) -> None:
    server.base_url = base_url

    ran = _run(tmp_path, server, "GET", "/user")

    assert ran.returncode == 2
    assert server.seen == []


def test_both_or_neither_auth_slot_is_a_usage_error(tmp_path: Path, server: _Server) -> None:
    both = _run(
        tmp_path,
        server,
        "GET",
        "/user",
        auth={AUTH_HEADER_ENV: "Authorization", AUTH_QUERY_ENV: "api_key"},
    )
    neither = _run(tmp_path, server, "GET", "/user", auth={})

    assert (both.returncode, neither.returncode) == (2, 2)
    assert server.seen == []


def test_an_unreachable_host_exits_1(tmp_path: Path, server: _Server) -> None:
    server.base_url = "https://127.0.0.1:9/v1"

    ran = _run(tmp_path, server, "GET", "/user")

    assert ran.returncode == 1
    assert "request failed" in ran.stderr
