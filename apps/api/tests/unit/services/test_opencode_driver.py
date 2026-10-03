"""Unit tests for OpenCodeDriver (command construction + run JSONL parsing)."""

from collections.abc import AsyncIterator, Iterator
import contextlib
import shlex
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.agent_lab_models import (
    AgentKind,
    AgentSessionDocument,
    AgentSessionState,
    AgentSessionUpdate,
)
from app.services.agent_lab.opencode_driver import (
    DEFAULT_MODEL,
    OpenCodeDriver,
    OpenCodeStreamKind,
    parse_stream_line,
    parse_stream_transcript,
    summarize_events,
)

USER_ID = "507f1f77bcf86cd799439011"

# Representative-sample fixture only: envelope shapes below mirror the two
# types observed in scripts/dev/doctrine_bench.py:59-81; the full opencode
# event taxonomy is UNVERIFIED per the spike (only `text` and `step_finish`
# are parsed, everything else is passthrough).
SAMPLE_TRANSCRIPT = (
    '{"type": "text", "part": {"text": "fixed the bug"}}\n'
    '{"type": "step_finish", "part": {"tokens": {"input": 10, "output": 5}}}\n'
    '{"type": "tool_use", "part": {"id": "tu-1"}}\n'
    '{"type": "text", "part": {}}\n'
    "not json at all\n"
)


class _FakeCommands:
    """Records commands; exit code scripted per test."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.exit_code: int = 0

    async def run(self, command: str, **kwargs: object) -> SimpleNamespace:
        self.ran.append(command)
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


@pytest.fixture
def fake_store() -> Iterator[_FakeSessionStore]:
    store = _FakeSessionStore()
    with patch("app.services.agent_lab.driver.agent_lab_session_repository", store):
        yield store


@pytest.fixture
def fake_sandbox() -> Iterator[SimpleNamespace]:
    commands = _FakeCommands()

    @contextlib.asynccontextmanager
    async def _acquire(user_id: str) -> AsyncIterator[_FakeSandbox]:
        yield _FakeSandbox(commands)

    with patch("app.services.agent_lab.driver.acquire_sandbox", _acquire):
        yield SimpleNamespace(commands=commands)


@pytest.mark.unit
class TestAgentKind:
    def test_drives_opencode(self) -> None:
        assert OpenCodeDriver.agent_kind is AgentKind.OPENCODE


@pytest.mark.unit
class TestStartCommand:
    def test_uses_run_format_json_with_model(self) -> None:
        command = OpenCodeDriver.build_start_command("do the thing")

        assert "opencode run" in command
        assert "--format json" in command
        assert f"-m {DEFAULT_MODEL}" in command

    def test_default_model_is_observed_zen_free(self) -> None:
        assert DEFAULT_MODEL == "opencode/muse-spark-1.3-contributor-free"

    def test_model_passthrough_overrides_default(self) -> None:
        command = OpenCodeDriver.build_start_command("do the thing", model="foo/bar")

        assert "-m foo/bar" in command
        assert DEFAULT_MODEL not in command

    def test_message_is_last_arg(self) -> None:
        prompt = "do the thing"

        assert OpenCodeDriver.build_start_command(prompt).endswith(shlex.quote(prompt))

    def test_quotes_prompt(self) -> None:
        prompt = "don't break; rm -rf /"

        assert shlex.quote(prompt) in OpenCodeDriver.build_start_command(prompt)


@pytest.mark.unit
class TestMessageCommand:
    def test_continues_last_session(self) -> None:
        command = OpenCodeDriver.build_message_command("keep going")

        assert "-c" in command.split()
        assert "-s" not in command.split()
        assert "--format json" in command
        assert f"-m {DEFAULT_MODEL}" in command

    def test_resume_targets_explicit_session(self) -> None:
        command = OpenCodeDriver.build_resume_command("sess-123", "keep going")

        assert "-s" in command.split()
        assert "sess-123" in command.split()
        assert "-c" not in command.split()
        assert "--format json" in command


@pytest.mark.unit
class TestStopCommand:
    def test_foreground_stop_uses_sigterm(self) -> None:
        command = OpenCodeDriver.build_stop_command()

        assert "TERM" in command
        assert "opencode run" in command

    def test_no_serve_stop_subcommand_exists(self) -> None:
        assert "stop" not in OpenCodeDriver.build_stop_command()


@pytest.mark.unit
class TestSanitizedEnv:
    def test_passes_env_through_without_mutating_input(self) -> None:
        env = {"PATH": "/usr/bin", "OPENCODE_FOO": "x"}

        stripped = OpenCodeDriver.sanitized_env(env)

        assert stripped == env
        assert stripped is not env


@pytest.mark.unit
class TestParseStream:
    def test_text_event_extracts_text(self) -> None:
        event = parse_stream_line('{"type": "text", "part": {"text": "hello"}}')

        assert event.kind is OpenCodeStreamKind.TEXT
        assert event.text == "hello"

    def test_step_finish_classifies_without_text(self) -> None:
        event = parse_stream_line('{"type": "step_finish", "part": {"tokens": {}}}')

        assert event.kind is OpenCodeStreamKind.STEP_FINISH
        assert event.text is None

    def test_text_without_text_is_passthrough(self) -> None:
        event = parse_stream_line('{"type": "text", "part": {}}')

        assert event.kind is OpenCodeStreamKind.PASSTHROUGH
        assert event.raw == '{"type": "text", "part": {}}'

    def test_unknown_shape_is_passthrough(self) -> None:
        event = parse_stream_line('{"type": "tool_use", "part": {"id": "tu-1"}}')

        assert event.kind is OpenCodeStreamKind.PASSTHROUGH
        assert event.raw == '{"type": "tool_use", "part": {"id": "tu-1"}}'

    def test_non_json_is_passthrough(self) -> None:
        event = parse_stream_line("not json at all")

        assert event.kind is OpenCodeStreamKind.PASSTHROUGH

    def test_transcript_skips_blanks_and_summarizes(self) -> None:
        events = parse_stream_transcript(SAMPLE_TRANSCRIPT)
        progress = summarize_events(events)

        assert [event.kind for event in events] == [
            OpenCodeStreamKind.TEXT,
            OpenCodeStreamKind.STEP_FINISH,
            OpenCodeStreamKind.PASSTHROUGH,
            OpenCodeStreamKind.PASSTHROUGH,
            OpenCodeStreamKind.PASSTHROUGH,
        ]
        assert progress.text_chars == len("fixed the bug")
        assert progress.steps_finished == 1
        assert progress.passthrough == 3


@pytest.mark.unit
class TestLifecycle:
    async def test_start_runs_constructed_command(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ) -> None:
        result = await OpenCodeDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert result.agent is AgentKind.OPENCODE
        assert fake_sandbox.commands.ran == [OpenCodeDriver.build_start_command("do the thing")]

    async def test_stop_runs_constructed_command(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ) -> None:
        session = await OpenCodeDriver.start(USER_ID, "do the thing", "todo-1")

        result = await OpenCodeDriver.stop(USER_ID, session.id)

        assert result.state is AgentSessionState.STOPPED
        assert fake_sandbox.commands.ran == [
            OpenCodeDriver.build_start_command("do the thing"),
            OpenCodeDriver.build_stop_command(),
        ]
