"""Unit tests for ClaudeDriver (command construction + stream-json parsing)."""

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
from app.services.agent_lab.claude_driver import (
    ClaudeDriver,
    ClaudeStreamKind,
    parse_stream_line,
    parse_stream_transcript,
    summarize_events,
)

USER_ID = "507f1f77bcf86cd799439011"

# Representative-sample fixture only: envelope shapes below are illustrative of
# newline-delimited stream-json; the full Claude event taxonomy is UNVERIFIED
# per the spike (only `text` and error/permission_denied shapes are parsed,
# everything else is passthrough).
SAMPLE_TRANSCRIPT = (
    '{"type": "text", "part": {"text": "fixed the bug"}}\n'
    '{"type": "system", "subtype": "permission_denied", "text": "denied Bash rm"}\n'
    '{"type": "error", "error": "model overloaded"}\n'
    '{"type": "tool_use", "part": {"id": "tu-1"}}\n'
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
    def test_drives_claude(self) -> None:
        assert ClaudeDriver.agent_kind is AgentKind.CLAUDE


@pytest.mark.unit
class TestStartCommand:
    def test_uses_print_stream_json_with_env_stripped(self) -> None:
        command = ClaudeDriver.build_start_command("do the thing")

        assert "claude -p" in command
        assert "--output-format stream-json" in command
        assert command.startswith("env -u ANTHROPIC_API_KEY")

    def test_never_uses_bare_flag(self) -> None:
        assert "--bare" not in ClaudeDriver.build_start_command("do the thing").split()

    def test_quotes_prompt(self) -> None:
        prompt = "don't break; rm -rf /"

        assert shlex.quote(prompt) in ClaudeDriver.build_start_command(prompt)


@pytest.mark.unit
class TestMessageCommand:
    def test_continues_session(self) -> None:
        command = ClaudeDriver.build_message_command("keep going")

        assert "--continue" in command
        assert "--output-format stream-json" in command
        assert "--bare" not in command.split()
        assert command.startswith("env -u ANTHROPIC_API_KEY")

    def test_resume_targets_explicit_session(self) -> None:
        command = ClaudeDriver.build_resume_command("sess-123", "keep going")

        assert "--resume sess-123" in command
        assert "--output-format stream-json" in command
        assert "--bare" not in command.split()


@pytest.mark.unit
class TestStopCommand:
    def test_foreground_stop_uses_sigterm(self) -> None:
        command = ClaudeDriver.build_stop_command()

        assert "TERM" in command
        assert "claude" in command

    def test_background_stop_keeps_conversation(self) -> None:
        command = ClaudeDriver.build_stop_session_command("sess-123")

        assert command == "env -u ANTHROPIC_API_KEY claude stop sess-123"


@pytest.mark.unit
class TestSanitizedEnv:
    def test_strips_api_key_without_mutating_input(self) -> None:
        env = {"ANTHROPIC_API_KEY": "secret", "PATH": "/usr/bin"}

        stripped = ClaudeDriver.sanitized_env(env)

        assert stripped == {"PATH": "/usr/bin"}
        assert env == {"ANTHROPIC_API_KEY": "secret", "PATH": "/usr/bin"}

    def test_missing_key_passes_through(self) -> None:
        assert ClaudeDriver.sanitized_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


@pytest.mark.unit
class TestParseStream:
    def test_text_event_extracts_text(self) -> None:
        event = parse_stream_line('{"type": "text", "part": {"text": "hello"}}')

        assert event.kind is ClaudeStreamKind.TEXT
        assert event.text == "hello"

    def test_permission_denied_detected(self) -> None:
        event = parse_stream_line(
            '{"type": "system", "subtype": "permission_denied", "text": "no"}'
        )

        assert event.kind is ClaudeStreamKind.PERMISSION_DENIED

    def test_error_detected(self) -> None:
        event = parse_stream_line('{"type": "error", "error": "boom"}')

        assert event.kind is ClaudeStreamKind.ERROR
        assert event.text == "boom"

    def test_unknown_shape_is_passthrough(self) -> None:
        event = parse_stream_line('{"type": "tool_use", "part": {"id": "tu-1"}}')

        assert event.kind is ClaudeStreamKind.PASSTHROUGH
        assert event.raw == '{"type": "tool_use", "part": {"id": "tu-1"}}'

    def test_non_json_is_passthrough(self) -> None:
        event = parse_stream_line("not json at all")

        assert event.kind is ClaudeStreamKind.PASSTHROUGH

    def test_transcript_skips_blanks_and_summarizes(self) -> None:
        events = parse_stream_transcript(SAMPLE_TRANSCRIPT)
        progress = summarize_events(events)

        assert [event.kind for event in events] == [
            ClaudeStreamKind.TEXT,
            ClaudeStreamKind.PERMISSION_DENIED,
            ClaudeStreamKind.ERROR,
            ClaudeStreamKind.PASSTHROUGH,
            ClaudeStreamKind.PASSTHROUGH,
        ]
        assert progress.text_chars == len("fixed the bug")
        assert progress.permission_denials == 1
        assert progress.errors == 1
        assert progress.passthrough == 2


@pytest.mark.unit
class TestStartLifecycle:
    async def test_start_runs_constructed_command(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ) -> None:
        result = await ClaudeDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert result.agent is AgentKind.CLAUDE
        assert fake_sandbox.commands.ran == [ClaudeDriver.build_start_command("do the thing")]
