"""One throwaway runner per connector call, behind one interface.

GAIA Cloud runs each call in a fresh E2B sandbox; self-host runs it in a fresh
local docker container. The runner holds the real credential for that one call
and is destroyed afterwards. It returns raw output: scrubbing is the caller's.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

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
