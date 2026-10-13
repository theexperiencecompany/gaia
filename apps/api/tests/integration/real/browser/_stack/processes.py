"""The browser stack's processes: the API, the ARQ browser worker and two browser hosts, each a real OS process.

The hosts run python -m app.browser_host (one Chrome, one Obscura); the API
and the worker run serve.py. All of them run on this interpreter with the
stack's environment: this test process's own credential-fenced environment plus
what wires them to each other, the fake models and the fixture site. Each takes
its every setting from that environment at import, as in production, and runs
under guard.py, so a hard-killed test process takes it and its engines along.
Each writes a log a failing test's report carries. Readiness is what each serves,
polled to a deadline: an HTTP health route, or the workers' ARQ health keys.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess  # nosec B404 -- starts this repo's own processes with a fixed argv, never a shell
import sys
import time

import httpx
from redis.asyncio import Redis

from app.constants.browser import BROWSER_HOST_KEY_HEADER, BrowserEngine
from app.workers.browser_worker import browser_worker_health_key
from tests.helpers import pick_free_port

API_ROOT = Path(__file__).resolve().parents[5]
#: The health key the worker process's reaper (a main-queue ARQ worker) refreshes while it polls.
REAPER_HEALTH_KEY = "browser-stack:reaper:health"
#: How long a process gets to boot: a cold import of the app, or an engine launch.
READY_SECONDS = 120.0
_SERVE_MODULE = "tests.integration.real.browser._stack.serve"
#: Runs each process so it dies with this one, however this one dies (guard.py).
_GUARD_MODULE = "tests.integration.real.browser._stack.guard"
_POLL_SECONDS = 0.2
#: The lines of a process log a failing test's report carries.
LOG_TAIL_LINES = 80
_STOP_GRACE_SECONDS = 10


class StackProcessError(RuntimeError):
    """A stack process exited, or never became ready, within its deadline."""


@dataclass
class StackProcess:
    """One child process, in its own process group under a guard that dies with this process, and its log."""

    name: str
    argv: list[str]
    env: dict[str, str]
    log_path: Path
    proc: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        with self.log_path.open("ab") as log:
            self.proc = subprocess.Popen(  # nosec B603 -- fixed argv built here, no shell
                [sys.executable, "-m", _GUARD_MODULE, str(os.getpid()), *self.argv],
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

    async def wait_until(self, ready: Callable[[], Awaitable[bool]], what: str) -> None:
        """Wait until ready() holds, failing at once if the process exits first."""
        deadline = time.monotonic() + READY_SECONDS
        while time.monotonic() < deadline:
            self.assert_alive()
            if await ready():
                return
            await asyncio.sleep(_POLL_SECONDS)
        raise StackProcessError(f"{self.name} never {what}\n{self.tail()}")

    async def wait_healthy(self, url: str, headers: Mapping[str, str] | None = None) -> None:
        """Wait until url answers 200: the process serves HTTP with its startup done."""
        async with httpx.AsyncClient(timeout=5, headers=headers) as client:

            async def answers() -> bool:
                try:
                    return (await client.get(url)).status_code == 200
                except httpx.TransportError:
                    return False

            await self.wait_until(answers, f"answered 200 on {url}")


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
        await self.process.wait_healthy(
            f"{self.url}/healthz", headers={BROWSER_HOST_KEY_HEADER: self.key}
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

    def __init__(self, env: dict[str, str], log_dir: Path, redis: Redis) -> None:
        self._env = env
        self._log_dir = log_dir
        #: The stack's own database, where both of the process's ARQ workers record their health.
        self._redis = redis
        self._health_keys = (browser_worker_health_key(), REAPER_HEALTH_KEY)
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
        """Start the process and wait until both its workers poll, each having refreshed its health key.

        A SIGKILLed predecessor leaves its keys behind, so they are cleared first.
        """
        await self._redis.delete(*self._health_keys)
        self.process.start()

        async def polling() -> bool:
            return await self._redis.exists(*self._health_keys) == len(self._health_keys)

        await self.process.wait_until(polling, "polled its queues (no ARQ health keys)")

    def kill(self) -> None:
        self.process.kill()

    async def restart(self) -> None:
        """Bring up a fresh worker after the last one died."""
        self.process.stop()
        self.process = self._next()
        await self.start()
