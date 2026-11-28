"""The E2B runner's phase order against a recorded sandbox: no secret before egress narrows, always killed."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from e2b import AsyncSandbox, CommandExitException, CommandResult, SandboxException
import pytest

from app.constants.connectors import CONNECTOR_RAW_OUTPUT_MAX_BYTES
from app.models.connector_models import InstallPackage, PackageManager
from app.services.connectors import e2b_runner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from app.services.connectors.rest_helper import REST_HELPER_PATH
from app.services.connectors.runner import RunnerFile, RunOutcome, RunRequest
from app.services.providers.provider_credentials_service import ProviderConfig

_SECRET = "ghp_secretvalue123"  # pragma: allowlist secret
_PIP = InstallPackage(manager=PackageManager.PIP, name="httpie", version="3.2.4")


@dataclass
class _Script:
    """What the fake sandbox's commands do, in run order."""

    exit_codes: list[int] = field(default_factory=list)
    stdout_chunks: list[str] = field(default_factory=list)
    hang: bool = False


class _Handle:
    def __init__(self, exit_code: int, hang: bool, events: list[tuple[str, Any]]) -> None:
        self._exit_code = exit_code
        self._done = asyncio.Event()
        self._events = events
        if not hang:
            self._done.set()

    async def wait(self) -> CommandResult:
        await self._done.wait()
        if self._exit_code != 0:
            raise CommandExitException(
                stderr="boom", stdout="", exit_code=self._exit_code, error=None
            )
        return CommandResult(stderr="", stdout="", exit_code=0, error=None)

    async def kill(self) -> bool:
        self._events.append(("kill_command", None))
        self._exit_code = -1
        self._done.set()
        return True


class _Sandbox:
    def __init__(self, script: _Script, events: list[tuple[str, Any]]) -> None:
        self._script = script
        self.events = events
        self.commands = self
        self.files = self

    async def run(
        self,
        cmd: str,
        *,
        envs: dict[str, str],
        user: str,
        on_stdout: Callable[[str], None],
        **_: object,
    ) -> _Handle:
        self.events.append(("run", {"cmd": cmd, "envs": envs, "user": user}))
        exit_code = self._script.exit_codes.pop(0)
        hang = self._script.hang and not self._script.exit_codes
        for chunk in self._script.stdout_chunks:
            on_stdout(chunk)
        return _Handle(exit_code, hang, self.events)

    async def update_network(self, network: dict[str, list[str]]) -> None:
        self.events.append(("update_network", network))

    async def write_files(self, files: list[dict[str, str]], user: str) -> None:
        self.events.append(("write_files", {"paths": [f["path"] for f in files], "user": user}))

    async def kill(self) -> None:
        self.events.append(("kill", None))


@pytest.fixture
def events() -> list[tuple[str, Any]]:
    return []


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[str, Any]],
    script: _Script,
    api_key: str | None = "e2b_test",  # pragma: allowlist secret
    create_error: Exception | None = None,
) -> None:
    async def resolve(_: object) -> ProviderConfig | None:
        return ProviderConfig(api_key=api_key) if api_key else None

    async def create(**kwargs: Any) -> _Sandbox:
        events.append(("create", kwargs))
        if create_error is not None:
            raise create_error
        return _Sandbox(script, events)

    monkeypatch.setattr(e2b_runner, "resolve_provider", resolve)
    monkeypatch.setattr(AsyncSandbox, "create", create)


def _request(**overrides: Any) -> RunRequest:
    fields: dict[str, Any] = {
        "install": (_PIP,),
        "install_hosts": ("pypi.org",),
        "call_hosts": ("api.github.com",),
        "argv": ("gh", "api", "user"),
        "timeout_seconds": 30,
        "env": {"GH_TOKEN": _SECRET},
        "files": (RunnerFile("~/.config/gh/hosts.yml", f"token: {_SECRET}"),),
    }
    return RunRequest(**{**fields, **overrides})


async def test_the_secret_arrives_only_after_egress_narrows_to_the_call_hosts(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(exit_codes=[0, 0], stdout_chunks=["ok"]))

    result = await E2BConnectorRunner().run(_request())

    assert result.outcome is RunOutcome.OK
    names = [name for name, _ in events]
    assert names == ["create", "run", "update_network", "write_files", "run", "kill"]
    create, install = events[0][1], events[1][1]
    assert create["network"]["allow_out"] == ["api.github.com", "pypi.org"]
    assert (install["user"], install["envs"]) == ("root", {})
    assert _SECRET not in repr(events[:3])
    assert events[2][1] == {"allow_out": ["api.github.com"], "deny_out": ["0.0.0.0/0"]}
    assert REST_HELPER_PATH in events[3][1]["paths"]
    call = events[4][1]
    assert call["cmd"] == "gh api user < /dev/null"
    assert (call["user"], call["envs"]) == ("user", {"GH_TOKEN": _SECRET})


async def test_a_failed_install_never_writes_the_secret_or_runs_the_call(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(exit_codes=[1]))

    result = await E2BConnectorRunner().run(_request())

    assert (result.outcome, result.exit_code) == (RunOutcome.INSTALL_FAILED, 1)
    assert [name for name, _ in events] == ["create", "run", "kill"]
    assert _SECRET not in repr(events)


async def test_no_e2b_key_is_runner_unavailable_without_creating_a_sandbox(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(), api_key=None)

    result = await E2BConnectorRunner().run(_request())

    assert result.outcome is RunOutcome.RUNNER_UNAVAILABLE
    assert events == []


async def test_a_create_failure_is_runner_unavailable(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(), create_error=SandboxException("quota"))

    result = await E2BConnectorRunner().run(_request())

    assert result.outcome is RunOutcome.RUNNER_UNAVAILABLE
    assert "quota" in result.stderr


async def test_output_past_the_cap_kills_the_command_and_flags_it(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    chunk = "y" * (CONNECTOR_RAW_OUTPUT_MAX_BYTES // 2)
    _patch(monkeypatch, events, _Script(exit_codes=[0], stdout_chunks=[chunk] * 3, hang=True))

    result = await E2BConnectorRunner().run(_request(install=()))

    assert result.output_capped
    assert len(result.stdout) == CONNECTOR_RAW_OUTPUT_MAX_BYTES
    assert ("kill_command", None) in events
    assert result.outcome is RunOutcome.EXIT_NONZERO


async def test_a_call_past_its_deadline_is_killed_and_times_out(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(exit_codes=[0], hang=True))

    result = await E2BConnectorRunner().run(_request(install=(), timeout_seconds=0))

    assert (result.outcome, result.exit_code) == (RunOutcome.TIMEOUT, None)
    assert [name for name, _ in events][-2:] == ["kill_command", "kill"]


async def test_the_sandbox_is_killed_even_when_a_phase_raises(
    monkeypatch: pytest.MonkeyPatch, events: list[tuple[str, Any]]
) -> None:
    _patch(monkeypatch, events, _Script(exit_codes=[0]))

    async def broken(*_: Any, **__: Any) -> None:
        raise SandboxException("envd went away")

    monkeypatch.setattr(_Sandbox, "write_files", broken)

    with pytest.raises(SandboxException, match="envd went away"):
        await E2BConnectorRunner().run(_request(install=()))
    assert events[-1] == ("kill", None)
