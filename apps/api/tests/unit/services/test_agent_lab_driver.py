"""Unit tests for AgentDriver (session lifecycle over a fake sandbox + store)."""

from collections.abc import AsyncIterator, Iterator
import contextlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.agent_lab_models import (
    AgentKind,
    AgentSessionDocument,
    AgentSessionState,
    AgentSessionUpdate,
)
from app.services.agent_lab.driver import AgentDriver
from app.utils.errors import AppError

USER_ID = "507f1f77bcf86cd799439011"


class _FakeCommands:
    """Records commands; exit code scripted per test."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.exit_code: int = 0
        self.exit_codes: list[int] | None = None

    async def run(self, command: str, **kwargs: object) -> SimpleNamespace:
        self.ran.append(command)
        if self.exit_codes is not None:
            code = self.exit_codes.pop(0) if self.exit_codes else 0
            return SimpleNamespace(exit_code=code, stdout="", stderr="")
        return SimpleNamespace(exit_code=self.exit_code, stdout="", stderr="")


class _FakeSandbox:
    """Mimics the AsyncSandbox surface the driver touches."""

    def __init__(self, commands: _FakeCommands) -> None:
        self.commands = commands
        self.sandbox_id = "sbx-test"


class _FakeSessionStore:
    """In-memory stand-in for the session repository."""

    def __init__(self) -> None:
        self.docs: dict[str, AgentSessionDocument] = {}

    async def create(self, doc: AgentSessionDocument) -> AgentSessionDocument:
        stored = doc.model_copy(update={"id": f"lab-{len(self.docs) + 1}"})
        self.docs[stored.id] = stored
        return stored

    async def update(
        self, session_id: str, *, user_id: str, update: AgentSessionUpdate
    ) -> AgentSessionDocument | None:
        current = self.docs.get(session_id)
        if current is None or current.user_id != user_id:
            return None
        data = current.model_dump()
        data.update(update.model_dump(exclude_unset=True))
        stored = AgentSessionDocument.model_validate(data)
        self.docs[stored.id] = stored
        return stored

    async def get_for_user(self, session_id: str, *, user_id: str) -> AgentSessionDocument | None:
        current = self.docs.get(session_id)
        if current is None or current.user_id != user_id:
            return None
        return current


class _FakeDriver(AgentDriver):
    agent_kind = AgentKind.CLAUDE
    install_bin = "fake"
    install_package = "@fake/cli"
    install_version = "0.0.1"

    @classmethod
    def build_start_command(cls, prompt: str) -> str:
        return f"launch {prompt}"

    @classmethod
    def build_message_command(cls, text: str) -> str:
        return f"send {text}"

    @classmethod
    def build_stop_command(cls) -> str:
        return "halt"


@pytest.fixture
def fake_store() -> Iterator[_FakeSessionStore]:
    store = _FakeSessionStore()
    with patch("app.services.agent_lab.driver.agent_lab_session_repository", store):
        yield store


@pytest.fixture
def fake_sandbox() -> Iterator[SimpleNamespace]:
    commands = _FakeCommands()
    entered: list[str] = []

    @contextlib.asynccontextmanager
    async def _acquire(user_id: str) -> AsyncIterator[_FakeSandbox]:
        entered.append(user_id)
        yield _FakeSandbox(commands)

    with patch("app.services.agent_lab.driver.acquire_sandbox", _acquire):
        yield SimpleNamespace(commands=commands, entered=entered)


class _SeededDriver(_FakeDriver):
    lab_hooks_enabled = True

    @classmethod
    def build_seed_command(cls, events_url: str, token: str) -> str | None:
        return f"seed {events_url} {token}"


@pytest.fixture
def _seed_env() -> Iterator[None]:
    with (
        patch("app.services.agent_lab.driver.lab_events_enabled", return_value=True),
        patch(
            "app.services.agent_lab.driver.lab_events_url",
            return_value="https://gaia.test/api/v1/lab/events",
        ),
        patch("app.services.agent_lab.driver.mint_lab_hooks_token", return_value="tok-1"),
    ):
        yield


def _seed(store: _FakeSessionStore, state: AgentSessionState) -> AgentSessionDocument:
    doc = AgentSessionDocument(
        id="lab-9",
        user_id=USER_ID,
        todo_id="todo-1",
        agent=AgentKind.CLAUDE,
        state=state,
    )
    store.docs[doc.id] = doc
    return doc


@pytest.mark.unit
class TestInstallCommands:
    def test_install_pins_package_at_version_under_prefix(self) -> None:
        command = _FakeDriver.install_command()

        assert "@fake/cli@0.0.1" in command
        assert "--prefix /workspace/.local" in command
        assert "sudo" not in command

    def test_ensure_probes_before_installing(self) -> None:
        ensure = _FakeDriver.ensure_installed_command()

        assert "command -v fake" in ensure
        assert _FakeDriver.install_command() in ensure
        assert "sudo" not in ensure


@pytest.mark.unit
class TestStart:
    async def test_runs_ensure_then_launch_and_marks_running(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        result = await _FakeDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert result.todo_id == "todo-1"
        assert result.agent is AgentKind.CLAUDE
        assert result.sandbox_session_ref == "sbx-test"
        assert fake_sandbox.commands.ran == [
            _FakeDriver.ensure_installed_command(),
            "launch do the thing",
        ]

    @pytest.mark.parametrize("todo_id", ["", "   "])
    async def test_rejects_missing_todo_id_without_side_effects(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace, todo_id: str
    ):
        with pytest.raises(AppError, match="todo_id is required"):
            await _FakeDriver.start(USER_ID, "do the thing", todo_id)

        assert fake_store.docs == {}
        assert fake_sandbox.entered == []

    async def test_marks_failed_when_install_exits_nonzero(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        fake_sandbox.commands.exit_code = 1

        with pytest.raises(AppError, match="failed to install"):
            await _FakeDriver.start(USER_ID, "do the thing", "todo-1")

        (doc,) = fake_store.docs.values()
        assert doc.state is AgentSessionState.FAILED
        assert fake_sandbox.commands.ran == [_FakeDriver.ensure_installed_command()]

    async def test_marks_failed_when_launch_exits_nonzero(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        fake_sandbox.commands.exit_codes = [0, 1]

        with pytest.raises(AppError, match="failed to start"):
            await _FakeDriver.start(USER_ID, "do the thing", "todo-1")

        (doc,) = fake_store.docs.values()
        assert doc.state is AgentSessionState.FAILED


@pytest.mark.unit
class TestSeedHooks:
    async def test_runs_ensure_then_seed_then_launch(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace, _seed_env: None
    ):
        result = await _SeededDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert fake_sandbox.commands.ran == [
            _SeededDriver.ensure_installed_command(),
            "seed https://gaia.test/api/v1/lab/events tok-1",
            "launch do the thing",
        ]

    async def test_marks_failed_when_seed_exits_nonzero(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace, _seed_env: None
    ):
        fake_sandbox.commands.exit_codes = [0, 1]

        with pytest.raises(AppError, match="failed to seed"):
            await _SeededDriver.start(USER_ID, "do the thing", "todo-1")

        (doc,) = fake_store.docs.values()
        assert doc.state is AgentSessionState.FAILED
        assert fake_sandbox.commands.ran == [
            _SeededDriver.ensure_installed_command(),
            "seed https://gaia.test/api/v1/lab/events tok-1",
        ]

    async def test_skips_seeding_when_receiver_unconfigured(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        with patch("app.services.agent_lab.driver.lab_events_enabled", return_value=False):
            result = await _SeededDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert fake_sandbox.commands.ran == [
            _SeededDriver.ensure_installed_command(),
            "launch do the thing",
        ]

    async def test_unseeded_driver_starts_without_hooks(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        result = await _FakeDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert fake_sandbox.commands.ran == [
            _FakeDriver.ensure_installed_command(),
            "launch do the thing",
        ]


@pytest.mark.unit
class TestMessage:
    async def test_sends_to_running_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.RUNNING)

        result = await _FakeDriver.message(USER_ID, seeded.id, "continue")

        assert result.id == seeded.id
        assert fake_sandbox.commands.ran == ["send continue"]

    async def test_rejects_non_running_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.STOPPED)

        with pytest.raises(AppError, match="not running"):
            await _FakeDriver.message(USER_ID, seeded.id, "continue")

        assert fake_sandbox.entered == []

    async def test_rejects_unknown_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        with pytest.raises(AppError, match="not found"):
            await _FakeDriver.message(USER_ID, "lab-missing", "continue")


@pytest.mark.unit
class TestStop:
    async def test_runs_halt_and_marks_stopped(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.RUNNING)

        result = await _FakeDriver.stop(USER_ID, seeded.id)

        assert result.state is AgentSessionState.STOPPED
        assert fake_sandbox.commands.ran == ["halt"]

    async def test_terminal_session_returns_untouched(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.STOPPED)

        result = await _FakeDriver.stop(USER_ID, seeded.id)

        assert result.state is AgentSessionState.STOPPED
        assert fake_sandbox.entered == []

    async def test_rejects_unknown_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        with pytest.raises(AppError, match="not found"):
            await _FakeDriver.stop(USER_ID, "lab-missing")


@pytest.mark.unit
class TestStatus:
    async def test_probes_sandbox_for_live_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.RUNNING)

        result = await _FakeDriver.status(USER_ID, seeded.id)

        assert result.id == seeded.id
        assert fake_sandbox.entered == [USER_ID]

    async def test_skips_sandbox_for_terminal_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        seeded = _seed(fake_store, AgentSessionState.STOPPED)

        result = await _FakeDriver.status(USER_ID, seeded.id)

        assert result.state is AgentSessionState.STOPPED
        assert fake_sandbox.entered == []

    async def test_rejects_unknown_session(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ):
        with pytest.raises(AppError, match="not found"):
            await _FakeDriver.status(USER_ID, "lab-missing")
