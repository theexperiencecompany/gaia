"""One throwaway runner per connector call, behind one interface.

GAIA Cloud runs each call in a fresh E2B sandbox; self-host runs it in a fresh
local docker container. The runner holds the real credential for that one call
and is destroyed afterwards. It returns raw output: scrubbing is the caller's.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import time
from typing import Protocol

from app.constants.connectors import CONNECTOR_RAW_OUTPUT_MAX_BYTES
from app.constants.sandbox import SANDBOX_USER_HOME
from app.models.connector_models import InstallPackage


@dataclass(frozen=True)
class RunnerFile:
    """A file written into the runner before the call; a ~/ path is under the runner's home."""

    path: str
    content: str


@dataclass(frozen=True)
class RunRequest:
    """Everything one call needs; argv is never a shell string."""

    install: tuple[InstallPackage, ...]
    # Hosts the install phase may reach (registries, binary download hosts).
    install_hosts: tuple[str, ...]
    # Hosts the call phase may reach: the spec's allowed_hosts.
    call_hosts: tuple[str, ...]
    argv: tuple[str, ...]
    timeout_seconds: int
    # Present only during the call phase, never during install.
    env: Mapping[str, str] = field(default_factory=dict)
    files: tuple[RunnerFile, ...] = ()


class RunOutcome(StrEnum):
    OK = "ok"
    EXIT_NONZERO = "exit_nonzero"
    TIMEOUT = "timeout"
    INSTALL_FAILED = "install_failed"
    RUNNER_UNAVAILABLE = "runner_unavailable"


@dataclass(frozen=True)
class RunResult:
    outcome: RunOutcome
    exit_code: int | None
    stdout: str
    stderr: str
    # True when a stream passed CONNECTOR_RAW_OUTPUT_MAX_BYTES and was cut.
    output_capped: bool = False
    duration_ms: int = 0


class ConnectorRunner(Protocol):
    async def run(self, request: RunRequest) -> RunResult: ...


def runner_path(path: str) -> str:
    """Resolve a ~/ path under the runner user's home, which both backends share."""
    if path.startswith("~/"):
        return f"{SANDBOX_USER_HOME}/{path.removeprefix('~/')}"
    if not path.startswith("/"):
        raise ValueError(f"a runner path is absolute or starts with ~/, got {path!r}")
    return path


class CappedOutput:
    """One stream's raw output, kept up to CONNECTOR_RAW_OUTPUT_MAX_BYTES and cut there."""

    def __init__(self, max_bytes: int = CONNECTOR_RAW_OUTPUT_MAX_BYTES) -> None:
        self._max_bytes = max_bytes
        self._parts: list[str] = []
        self._size = 0
        self.capped = False

    def add(self, text: str) -> None:
        if self.capped or not text:
            return
        encoded = text.encode()
        room = self._max_bytes - self._size
        if len(encoded) > room:
            # A cut mid-character drops the partial character rather than inventing one.
            self._parts.append(encoded[:room].decode(errors="ignore"))
            self._size = self._max_bytes
            self.capped = True
            return
        self._parts.append(text)
        self._size += len(encoded)

    @property
    def text(self) -> str:
        return "".join(self._parts)


def capped(text: str) -> CappedOutput:
    """Return a stream already holding text, cut at the cap."""
    output = CappedOutput()
    output.add(text)
    return output


def run_result(
    outcome: RunOutcome,
    exit_code: int | None,
    stdout: CappedOutput,
    stderr: CappedOutput,
    started: float,
) -> RunResult:
    """Build a call's result from its two streams; started is the run's time.monotonic()."""
    return RunResult(
        outcome=outcome,
        exit_code=exit_code,
        stdout=stdout.text,
        stderr=stderr.text,
        output_capped=stdout.capped or stderr.capped,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def failed_before_call(outcome: RunOutcome, reason: str, started: float) -> RunResult:
    """Build the result of a run that never reached the call, with the reason on stderr."""
    return run_result(outcome, None, CappedOutput(), capped(reason), started)
