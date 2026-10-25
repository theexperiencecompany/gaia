"""A local stand-in for api.github.com that runner.py talks real HTTP to.

runner.py reads GITHUB_API_URL (which Actions sets on every runner), so a test
points it here and the real client — URL building, pagination, retries, JSON
parsing — runs unchanged. Routes answer canned replies; every request is kept,
so a test asserts on what the script actually sent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import urllib.parse

RUNNER = Path(__file__).resolve().parent.parent / "runner.py"
REPO = "theexperiencecompany/gaia"


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, str]
    body: object


@dataclass(frozen=True)
class Reply:
    status: int = 200
    body: object = None
    link: str = ""


Responder = Callable[[Request], Reply]


@dataclass
class Route:
    method: str
    pattern: re.Pattern[str]
    query: dict[str, str]
    replies: list[Reply] | Responder

    def matches(self, req: Request) -> bool:
        if req.method != self.method or not self.pattern.search(req.path):
            return False
        return all(req.query.get(k) == v for k, v in self.query.items())

    def answer(self, req: Request) -> Reply:
        if callable(self.replies):
            return self.replies(req)
        # Consumed in order; the last reply repeats.
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@dataclass
class FakeGitHub:
    url: str = ""
    routes: list[Route] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)

    def on(
        self,
        method: str,
        pattern: str,
        *replies: Reply,
        query: dict[str, str] | None = None,
        responder: Responder | None = None,
    ) -> None:
        """Register a route; a later registration wins over an earlier one."""
        answer: list[Reply] | Responder = responder if responder else list(replies) or [Reply()]
        self.routes.insert(0, Route(method, re.compile(pattern), query or {}, answer))

    def handle(self, req: Request) -> Reply:
        self.requests.append(req)
        for route in self.routes:
            if route.matches(req):
                return route.answer(req)
        return Reply(404, {"message": f"no fake route for {req.method} {req.path}"})

    def posts(self) -> list[str]:
        """List the last path segment of every POST, in order: cancel, rerun, dispatches."""
        return [r.path.rsplit("/", 1)[-1] for r in self.requests if r.method == "POST"]

    def env(self, **extra: str) -> dict[str, str]:
        """Build a hermetic environment for runner.py: this server, a stub token, no retry wait."""
        return {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),
            "GITHUB_API_URL": self.url,
            "GITHUB_TOKEN": "stub-token",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_API_BACKOFF_SECS": "0",
            "GAIA_CPU_SLOTS_DIR": os.environ.get("GAIA_CPU_SLOTS_DIR", ""),
            "GAIA_CPU_TOKENS": os.environ.get("GAIA_CPU_TOKENS", ""),
            **extra,
        }


def _handler_for(fake: FakeGitHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            parts = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            req = Request(
                method=self.command,
                path=parts.path,
                query=dict(urllib.parse.parse_qsl(parts.query)),
                body=json.loads(raw) if raw else None,
            )
            reply = fake.handle(req)
            payload = b"" if reply.body is None else json.dumps(reply.body).encode()
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if reply.link:
                self.send_header("Link", reply.link)
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _serve  # http.server dispatches on these exact names
        do_POST = _serve  # http.server dispatches on these exact names

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002  # stdlib signature
            return

    return Handler


@contextmanager
def serve() -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(fake))
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()


def run_runner(
    *args: str, env: dict[str, str], timeout: int = 60, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the real runner.py; never raises on a non-zero exit (that is often the outcome)."""
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


def ago(seconds: int) -> str:
    when = datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=seconds)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def runner(name: str, status: str, label: str, *, busy: bool = False) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "busy": busy,
        "os": "linux",
        "labels": [{"name": "self-hosted"}, {"name": label}],
    }
