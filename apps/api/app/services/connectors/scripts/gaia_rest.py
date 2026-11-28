"""GAIA's REST request helper, run inside a connector runner: the key only reaches base_url's host.

Usage: gaia_rest.py METHOD PATH [--query K=V]... [--json BODY] [--header K:V]...
Prints the body to stdout and "HTTP <status>" to stderr. Exits 0 on 2xx, 22 on
any other status, 1 when the request got no response, 2 on a usage error.
The connection is opened to base_url's host itself, with no proxy and no
redirect following, so neither the path nor a 3xx can carry the key elsewhere.
"""

import argparse
import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import http.client
import json
import os
import ssl
import sys
from typing import NoReturn
from urllib.parse import urlencode, urlsplit

BASE_URL_ENV = "GAIA_CONNECTOR_BASE_URL"
SECRET_ENV = "GAIA_CONNECTOR_SECRET"
AUTH_HEADER_ENV = "GAIA_CONNECTOR_AUTH_HEADER"
AUTH_QUERY_ENV = "GAIA_CONNECTOR_AUTH_QUERY"
AUTH_TEMPLATE_ENV = "GAIA_CONNECTOR_AUTH_TEMPLATE"
SECRET_PLACEHOLDER = "{secret}"
# HTTP Basic: the user pastes "user:password" and the header carries its base64.
SECRET_BASE64_PLACEHOLDER = "{secret_base64}"

EXIT_OK = 0
EXIT_NO_RESPONSE = 1
EXIT_USAGE = 2
EXIT_HTTP_ERROR = 22

METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
# Headers that would change where or as whom the request goes.
RESERVED_HEADERS = frozenset(
    {"host", "authorization", "proxy-authorization", "cookie", "content-length"}
)
REQUEST_TIMEOUT_SECONDS = 60


class UsageError(Exception):
    """A request the helper refuses before opening any connection."""


@dataclass(frozen=True)
class PreparedRequest:
    """One request, already bound to base_url's host and port."""

    method: str
    host: str
    port: int | None
    target: str
    headers: Mapping[str, str]
    body: bytes | None


@dataclass(frozen=True)
class _AuthConfig:
    host: str
    port: int | None
    base_path: str
    secret_value: str
    header: str | None
    query: str | None


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_request(argv: Sequence[str], env: Mapping[str, str]) -> PreparedRequest:
    """Parse the call and the runner's env into one request for base_url's host."""
    parser = _Parser(prog="gaia_rest.py", add_help=False)
    parser.add_argument("method")
    parser.add_argument("path")
    parser.add_argument("--query", action="append", default=[])
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--json", dest="json_body")
    args = parser.parse_args(list(argv))

    method = args.method.upper()
    if method not in METHODS:
        raise UsageError(f"method must be one of {', '.join(METHODS)}")
    auth = _auth_config(env)
    _check_path(args.path)

    query = [_split_pair(item, "=", "--query") for item in args.query]
    if auth.query is not None:
        if any(key == auth.query for key, _ in query):
            raise UsageError(f"--query may not set the auth parameter {auth.query}")
        query.append((auth.query, auth.secret_value))

    headers = {"Accept": "application/json", "User-Agent": "gaia-connector"}
    for item in args.header:
        name, value = _split_pair(item, ":", "--header")
        lowered = name.lower()
        if lowered in RESERVED_HEADERS or (auth.header and lowered == auth.header.lower()):
            raise UsageError(f"--header may not set {name}")
        if not _is_printable_ascii(name + value):
            raise UsageError("--header names and values must be printable ASCII")
        headers[name] = value.strip()
    if auth.header is not None:
        headers[auth.header] = auth.secret_value

    body = None
    if args.json_body is not None:
        try:
            json.loads(args.json_body)
        except json.JSONDecodeError as error:
            raise UsageError(f"--json is not valid JSON: {error}") from error
        body = args.json_body.encode()
        headers["Content-Type"] = "application/json"

    target = auth.base_path + args.path + (f"?{urlencode(query)}" if query else "")
    return PreparedRequest(method, auth.host, auth.port, target, headers, body)


def _auth_config(env: Mapping[str, str]) -> _AuthConfig:
    base = urlsplit(env.get(BASE_URL_ENV, ""))
    secret = env.get(SECRET_ENV, "")
    header = env.get(AUTH_HEADER_ENV) or None
    query = env.get(AUTH_QUERY_ENV) or None
    template = env.get(AUTH_TEMPLATE_ENV, "")
    if base.scheme != "https" or not base.hostname or base.username or base.password:
        raise UsageError(f"{BASE_URL_ENV} must be an https URL with a host")
    if base.query or base.fragment:
        raise UsageError(f"{BASE_URL_ENV} may not carry a query or fragment")
    if not secret:
        raise UsageError(f"{SECRET_ENV} is not set")
    if (header is None) == (query is None):
        raise UsageError(f"set exactly one of {AUTH_HEADER_ENV} or {AUTH_QUERY_ENV}")
    if SECRET_PLACEHOLDER not in template and SECRET_BASE64_PLACEHOLDER not in template:
        raise UsageError(
            f"{AUTH_TEMPLATE_ENV} must contain {SECRET_PLACEHOLDER} or {SECRET_BASE64_PLACEHOLDER}"
        )
    encoded = base64.b64encode(secret.encode()).decode()
    return _AuthConfig(
        host=base.hostname,
        port=base.port,
        base_path=base.path.rstrip("/"),
        secret_value=template.replace(SECRET_BASE64_PLACEHOLDER, encoded).replace(
            SECRET_PLACEHOLDER, secret
        ),
        header=header,
        query=query,
    )


def _check_path(path: str) -> None:
    """Refuse any path that could name another host, carry a query, or smuggle bytes."""
    if not path.startswith("/") or path.startswith("//"):
        raise UsageError("path must start with a single /")
    if "://" in path or "\\" in path:
        raise UsageError("path may not contain :// or a backslash")
    if "@" in path.split("/", 2)[1]:
        raise UsageError("path may not contain @ in its first segment")
    if not _is_printable_ascii(path) or " " in path or "?" in path or "#" in path:
        raise UsageError("path must be printable ASCII (percent-encode the rest), without ? or #")


def _is_printable_ascii(text: str) -> bool:
    return all(0x20 <= ord(ch) < 0x7F for ch in text)


def _split_pair(item: str, sep: str, flag: str) -> tuple[str, str]:
    key, found, value = item.partition(sep)
    if not found or not key.strip():
        raise UsageError(f"{flag} takes NAME{sep}VALUE, got {item!r}")
    return key.strip(), value


def send(request: PreparedRequest) -> int:
    """Send the request, print the body and status, and return the exit code."""
    connection = http.client.HTTPSConnection(
        request.host,
        request.port,
        timeout=REQUEST_TIMEOUT_SECONDS,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(request.method, request.target, request.body, dict(request.headers))
        response = connection.getresponse()
        body = response.read()
    except (OSError, http.client.HTTPException) as error:
        print(f"request failed: {error}", file=sys.stderr)
        return EXIT_NO_RESPONSE
    finally:
        connection.close()
    sys.stdout.buffer.write(body)
    sys.stdout.flush()
    print(f"HTTP {response.status}", file=sys.stderr)
    return EXIT_OK if 200 <= response.status < 300 else EXIT_HTTP_ERROR


def main(argv: Sequence[str]) -> int:
    """Run one REST call from the command line."""
    try:
        request = build_request(argv, os.environ)
    except UsageError as error:
        print(f"gaia_rest.py: {error}", file=sys.stderr)
        return EXIT_USAGE
    return send(request)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
