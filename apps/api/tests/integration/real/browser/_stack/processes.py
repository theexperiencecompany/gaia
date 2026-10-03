"""The browser stack's processes: the API, the ARQ browser worker and two browser hosts, each a real OS process.

The hosts run python -m app.browser_host (one Chrome, one Obscura); the API
and the worker run serve.py. All of them run on this interpreter with the
stack's environment: this test process's own credential-fenced environment plus
what wires them to each other, the fake models and the fixture site. Each takes
its every setting from that environment at import, as in production. Each writes
a log the stack attaches to a failing test's report. Readiness is a polled
deadline, never a fixed sleep.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess  # nosec B404 -- starts this repo's own processes with a fixed argv, never a shell
import sys
import time

import httpx

from app.constants.browser import BROWSER_HOST_KEY_HEADER, BrowserEngine
from tests.helpers import pick_free_port

API_ROOT = Path(__file__).resolve().parents[5]
#: What serve.py's processes log once their services are up: the lines the stack waits for.
WORKER_READY_LINE = "browser stack worker serving the browser queue"
API_READY_LINE = "browser stack api serving"
#: How long a process gets to boot: a cold import of the app, or an engine launch.
READY_SECONDS = 120.0
_SERVE_MODULE = "tests.integration.real.browser._stack.serve"
_POLL_SECONDS = 0.2
#: The lines of a process log a failing test's report carries.
LOG_TAIL_LINES = 80
_STOP_GRACE_SECONDS = 10


class StackProcessError(RuntimeError):
    """A stack process exited, or never became ready, within its deadline."""


@dataclass
class StackProcess:
    """One child process, in its own process group, and the log it writes."""

    name: str
    argv: list[str]
    env: dict[str, str]
    log_path: Path
    proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        with self.log_path.open("ab") as log:
            self.proc = subprocess.Popen(  # nosec B603 -- fixed argv built here, no shell
                self.argv,
                cwd=API_ROOT,
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    def kill(self) -> None:
        """SIGKILL the whole process group: no cleanup, as a crashed machine would leave it."""
        if self.proc is not None and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()

    def stop(self) -> None:
        """SIGTERM the process group, killing what outlives a short grace."""
        if self.proc is None or self.proc.poll() is not None:
            return
        os.killpg(self.proc.pid, signal.SIGTERM)
        try:
            self.proc.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self.kill()

    def log(self) -> str:
        return self.log_path.read_text(errors="replace") if self.log_path.exists() else ""

    def tail(self) -> str:
        lines = self.log().splitlines()[-LOG_TAIL_LINES:]
        return "\n".join([f"--- {self.name} ({self.log_path}) ---", *lines])

    def assert_alive(self) -> None:
        if self.proc is not None and self.proc.poll() is not None:
            raise StackProcessError(
                f"{self.name} exited with {self.proc.returncode}\n{self.tail()}"
            )

    async def wait_for_line(self, line: str) -> None:
        """Wait until the process logs line, failing at once if it exits first."""
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            self.assert_alive()
            if line in self.log():
                return
            await asyncio.sleep(_POLL_SECONDS)
        raise StackProcessError(f"{self.name} never logged {line!r}\n{self.tail()}")


def child_environment(overrides: Mapping[str, str]) -> dict[str, str]:
    """Return this test process's (already credential-fenced) environment plus overrides."""
    env = dict(os.environ)
    env.update(overrides)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(API_ROOT)
    # One JSON object per line: what a failing scenario's report carries.
    env["LOG_FORMAT"] = "json"
    return env


@dataclass
class BrowserHost:
    """A browser host process serving one engine on its own port."""

    engine: BrowserEngine
    key: str
    process: StackProcess
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def wait_ready(self) -> None:
        deadline = time.monotonic() + READY_SECONDS
        async with httpx.AsyncClient(timeout=5) as client:
            while time.monotonic() < deadline:
                self.process.assert_alive()
                try:
                    response = await client.get(
                        f"{self.url}/healthz", headers={BROWSER_HOST_KEY_HEADER: self.key}
                    )
                    if response.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                await asyncio.sleep(_POLL_SECONDS)
        raise StackProcessError(
            f"{self.process.name} never answered healthz\n{self.process.tail()}"
        )


def browser_host(
    engine: BrowserEngine,
    binary: str,
    key: str,
    site: tuple[tuple[str, ...], Path],
    log_dir: Path,
) -> BrowserHost:
    """Build (not start) a host for engine, reaching exactly the fixture site's origins and trusting its CA."""
    allowed_origins, ca_file = site
    port = pick_free_port()
    binary_var = "OBSCURA_BIN" if engine is BrowserEngine.OBSCURA else "CHROMIUM_BIN"
    env = child_environment(
        {
            "ENV": "development",
            "BROWSER_ENGINE": engine.value,
            binary_var: binary,
            "BROWSER_HOST_BIND_ADDRESS": "127.0.0.1",
            "BROWSER_HOST_PORT": str(port),
            "BROWSER_HOST_URL": f"http://127.0.0.1:{port}",
            "BROWSER_HOST_KEY": key,
            "BROWSER_HOST_ALLOW_PRIVATE_ORIGINS": ",".join(allowed_origins),
            "BROWSER_HOST_TEST_CA_FILE": str(ca_file),
        }
    )
    process = StackProcess(
        name=f"{engine.value}-host",
        argv=[sys.executable, "-m", "app.browser_host"],
        env=env,
        log_path=log_dir / f"{engine.value}-host.log",
    )
    return BrowserHost(engine=engine, key=key, process=process, port=port)


def api_process(env: dict[str, str], port: int, log_dir: Path) -> StackProcess:
    """Build (not start) the API process, serving on port."""
    return StackProcess(
        name="api",
        argv=[sys.executable, "-m", _SERVE_MODULE, "api", str(port)],
        env=env,
        log_path=log_dir / "api.log",
    )


class BrowserWorker:
    """The ARQ browser worker process; restartable, so a test can kill one and bring up the next."""

    def __init__(self, env: dict[str, str], log_dir: Path) -> None:
        self._env = env
        self._log_dir = log_dir
        self._generation = 0
        self.process = self._next()

    def _next(self) -> StackProcess:
        self._generation += 1
        return StackProcess(
            name=f"browser-worker-{self._generation}",
            argv=[sys.executable, "-m", _SERVE_MODULE, "worker"],
            env=self._env,
            log_path=self._log_dir / f"browser-worker-{self._generation}.log",
        )

    async def start(self) -> None:
        self.process.start()
        await self.process.wait_for_line(WORKER_READY_LINE)

    def kill(self) -> None:
        self.process.kill()

    async def restart(self) -> None:
        """Bring up a fresh worker after the last one died."""
        self.process.stop()
        self.process = self._next()
        await self.start()
