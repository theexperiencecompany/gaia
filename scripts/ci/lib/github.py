"""github.py — the one GitHub REST client every scripts/ci entrypoint talks through.

Stdlib only: runner.py, verdict.py and test_impact.py run under a bare python3
on runners that have no project venv. Timeouts and retry with backoff on 5xx,
429 and network errors are built in; a call that still fails raises
GitHubError, so an outage is never read as an empty listing. A caller with a
safe fallback catches GitHubError at its call site and says so.

Env: GH_TOKEN or GITHUB_TOKEN (else `gh auth token`), GITHUB_API_URL (default
https://api.github.com), GITHUB_API_TIMEOUT_SECS (10), GITHUB_API_ATTEMPTS (3),
GITHUB_API_BACKOFF_SECS (2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import TypeVar
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_API_URL = "https://api.github.com"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECS = 60
ERROR_BODY_CHARS = 300
LINK_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')

Json = dict[str, object]
T = TypeVar("T")


class GitHubError(Exception):
    """An API call that did not produce the document the caller needs; status is its HTTP code."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def field_of(doc: Json, key: str, kind: type[T]) -> T:
    value = doc.get(key)
    if not isinstance(value, kind):
        raise GitHubError(f"response field {key!r} is {type(value).__name__}, not {kind.__name__}")
    return value


def text_of(doc: Json, key: str) -> str:
    """Read a string field GitHub sends as null until it happens (started_at, completed_at)."""
    value = doc.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise GitHubError(f"response field {key!r} is {type(value).__name__}, not str")
    return value


def _objects(items: list[object], where: str) -> list[Json]:
    out: list[Json] = []
    for item in items:
        if not isinstance(item, dict):
            raise GitHubError(f"{where} holds a {type(item).__name__}, not an object")
        out.append(item)
    return out


def records(doc: Json, key: str) -> list[Json]:
    return _objects(field_of(doc, key, list), f"response list {key!r}")


def _env_number(name: str, default: str) -> float:
    raw = os.environ.get(name) or default
    try:
        return float(raw)
    except ValueError as err:
        raise GitHubError(f"{name}={raw!r} is not a number") from err


def _resolve_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if token or shutil.which("gh") is None:
        return token
    proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


@dataclass(frozen=True)
class GitHub:
    """The one REST client: timeouts, retry with backoff, and no failure read as data."""

    base: str
    token: str
    timeout: float
    attempts: int
    backoff: float

    @classmethod
    def from_env(cls) -> GitHub:
        return cls(
            base=(os.environ.get("GITHUB_API_URL") or DEFAULT_API_URL).rstrip("/"),
            token=_resolve_token(),
            timeout=_env_number("GITHUB_API_TIMEOUT_SECS", "10"),
            attempts=max(int(_env_number("GITHUB_API_ATTEMPTS", "3")), 1),
            backoff=_env_number("GITHUB_API_BACKOFF_SECS", "2"),
        )

    def _url(self, path: str) -> str:
        url = path if path.startswith(("http://", "https://")) else f"{self.base}/{path}"
        if urllib.parse.urlsplit(url).scheme not in {"http", "https"}:
            raise GitHubError(f"refusing non-http URL {url}")
        return url

    def _request(
        self, method: str, url: str, body: Mapping[str, object] | None
    ) -> urllib.request.Request:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310  # scheme checked in _url

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after and retry_after.isdigit():
            return float(min(int(retry_after), MAX_RETRY_AFTER_SECS))
        return self.backoff * float(2 ** (attempt - 1))

    def send(
        self, method: str, path: str, body: Mapping[str, object] | None = None
    ) -> tuple[bytes, str]:
        """Return the body and the Link header; raise GitHubError once retries are spent."""
        url = self._url(path)
        for attempt in range(1, self.attempts + 1):
            failure, retry_after, retryable, status = "", None, True, None
            try:
                req = self._request(method, url, body)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 — scheme checked in _url
                    return resp.read(), resp.headers.get("Link", "")
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:ERROR_BODY_CHARS]
                failure = f"HTTP {err.code}: {detail}"
                retry_after = err.headers.get("Retry-After")
                retryable = err.code in RETRYABLE_STATUS
                status = err.code
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                failure = f"network: {err}"
            if not retryable or attempt == self.attempts:
                raise GitHubError(
                    f"{method} {url} failed after {attempt} attempt(s) — {failure}", status
                )
            delay = self._delay(attempt, retry_after)
            print(
                f"[github] {method} {url} — {failure}; retry {attempt}/{self.attempts - 1} in {delay:g}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def get(self, path: str) -> Json:
        return _decode_object(self.send("GET", path)[0], path)

    def get_list(self, path: str) -> list[Json]:
        """GET an endpoint that serves a bare JSON array (check-run annotations)."""
        raw, _ = self.send("GET", path)
        doc = _decode(raw, path)
        if not isinstance(doc, list):
            raise GitHubError(f"GET {path} returned a {type(doc).__name__}, not an array")
        return _objects(doc, f"GET {path}")

    def get_bytes(self, path: str) -> bytes:
        return self.send("GET", path)[0]

    def post(self, path: str, body: Mapping[str, object] | None = None) -> None:
        self.send("POST", path, body)

    def graphql(self, query: str, variables: Mapping[str, object]) -> Json:
        """Return a GraphQL query's data; a response carrying errors raises."""
        raw, _ = self.send("POST", "graphql", {"query": query, "variables": variables})
        doc = _decode_object(raw, "graphql")
        if errors := doc.get("errors"):
            raise GitHubError(f"graphql query failed — {json.dumps(errors)[:ERROR_BODY_CHARS]}")
        return field_of(doc, "data", dict)

    def collect(self, path: str, key: str) -> list[Json]:
        """Collect every record under key across all pages."""
        out: list[Json] = []
        url: str | None = path
        while url:
            raw, link = self.send("GET", url)
            out.extend(records(_decode_object(raw, url), key))
            match = LINK_NEXT.search(link)
            url = match.group(1) if match else None
        return out


def _decode(raw: bytes, path: str) -> object:
    try:
        doc: object = json.loads(raw)
    except json.JSONDecodeError as err:
        raise GitHubError(f"GET {path} returned a non-JSON body") from err
    return doc


def _decode_object(raw: bytes, path: str) -> Json:
    doc = _decode(raw, path)
    if not isinstance(doc, dict):
        raise GitHubError(f"GET {path} returned a {type(doc).__name__}, not an object")
    return doc
