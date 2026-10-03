"""Unit tests for CodexDriver (command construction + exec JSONL parsing)."""

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
from app.services.agent_lab.codex_driver import (
    INSTALL_VERSION,
    CodexDriver,
    CodexStreamKind,
    parse_stream_line,
    parse_stream_transcript,
    summarize_events,
)

USER_ID = "507f1f77bcf86cd799439011"

# Representative-sample fixture only: envelope shapes below are illustrative of
# newline-delimited exec --json; the full Codex event taxonomy is UNVERIFIED
# per the spike (only the documented thread/turn/item/error names are parsed,
# everything else is passthrough).
SAMPLE_TRANSCRIPT = (
    '{"type": "thread.started"}\n'
    '{"type": "turn.started"}\n'
    '{"type": "item.started"}\n'
    '{"type": "item.completed", "text": "edited main.py"}\n'
    '{"type": "turn.completed"}\n'
    '{"type": "turn.failed"}\n'
    '{"type": "error"}\n'
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
    def test_drives_codex(self) -> None:
        assert CodexDriver.agent_kind is AgentKind.CODEX


@pytest.mark.unit
class TestInstallCommand:
    def test_pins_probed_version(self) -> None:
        assert INSTALL_VERSION == "0.160.0"
        assert f"@openai/codex@{INSTALL_VERSION}" in CodexDriver.install_command()

    def test_installs_to_user_writable_prefix(self) -> None:
        command = CodexDriver.install_command()

        assert "--prefix /workspace/.local" in command
        assert "-g" in command.split()

    def test_install_never_uses_sudo(self) -> None:
        assert "sudo" not in CodexDriver.install_command()
        assert "sudo" not in CodexDriver.ensure_installed_command()

    def test_ensure_probes_before_installing(self) -> None:
        ensure = CodexDriver.ensure_installed_command()

        assert "command -v codex" in ensure
        assert CodexDriver.install_command() in ensure


@pytest.mark.unit
class TestStartCommand:
    def test_uses_exec_json_with_env_stripped(self) -> None:
        command = CodexDriver.build_start_command("do the thing")

        assert "codex exec" in command
        assert "--json" in command
        assert "env -u CODEX_API_KEY" in command
        assert 'PATH="/workspace/.local/bin:$PATH"' in command

    def test_defaults_to_workspace_write_sandbox(self) -> None:
        command = CodexDriver.build_start_command("do the thing")

        assert "--sandbox workspace-write" in command
        assert "read-only" not in command

    def test_skips_git_repo_check(self) -> None:
        assert "--skip-git-repo-check" in CodexDriver.build_start_command("do the thing")

    def test_quotes_prompt(self) -> None:
        prompt = "don't break; rm -rf /"

        assert shlex.quote(prompt) in CodexDriver.build_start_command(prompt)


@pytest.mark.unit
class TestMessageCommand:
    def test_resumes_last_session(self) -> None:
        command = CodexDriver.build_message_command("keep going")

        assert "resume --last" in command
        assert "--json" in command
        assert "--sandbox workspace-write" in command
        assert "env -u CODEX_API_KEY" in command

    def test_resume_targets_explicit_session(self) -> None:
        command = CodexDriver.build_resume_command("sess-123", "keep going")

        assert "resume sess-123" in command
        assert "--last" not in command
        assert "--json" in command


@pytest.mark.unit
class TestStopCommand:
    def test_foreground_stop_uses_sigterm(self) -> None:
        command = CodexDriver.build_stop_command()

        assert "TERM" in command
        assert "codex" in command

    def test_no_stop_subcommand_exists(self) -> None:
        assert "stop" not in CodexDriver.build_stop_command()


@pytest.mark.unit
class TestSanitizedEnv:
    def test_strips_key_vars_without_mutating_input(self) -> None:
        env = {"CODEX_API_KEY": "secret", "OPENAI_API_KEY": "secret", "PATH": "/usr/bin"}

        stripped = CodexDriver.sanitized_env(env)

        assert stripped == {"PATH": "/usr/bin"}
        assert env == {"CODEX_API_KEY": "secret", "OPENAI_API_KEY": "secret", "PATH": "/usr/bin"}

    def test_missing_keys_pass_through(self) -> None:
        assert CodexDriver.sanitized_env({"PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


@pytest.mark.unit
class TestParseStream:
    def test_documented_events_classify(self) -> None:
        cases = {
            "thread.started": CodexStreamKind.THREAD_STARTED,
            "turn.started": CodexStreamKind.TURN_STARTED,
            "item.started": CodexStreamKind.ITEM_STARTED,
            "item.completed": CodexStreamKind.ITEM_COMPLETED,
            "turn.completed": CodexStreamKind.TURN_COMPLETED,
            "turn.failed": CodexStreamKind.TURN_FAILED,
            "error": CodexStreamKind.ERROR,
        }

        for event_type, kind in cases.items():
            event = parse_stream_line(f'{{"type": "{event_type}"}}')

            assert event.kind is kind

    def test_item_completed_extracts_text(self) -> None:
        event = parse_stream_line('{"type": "item.completed", "text": "edited main.py"}')

        assert event.kind is CodexStreamKind.ITEM_COMPLETED
        assert event.text == "edited main.py"

    def test_unknown_shape_is_passthrough(self) -> None:
        event = parse_stream_line('{"type": "tool_use", "part": {"id": "tu-1"}}')

        assert event.kind is CodexStreamKind.PASSTHROUGH
        assert event.raw == '{"type": "tool_use", "part": {"id": "tu-1"}}'

    def test_non_json_is_passthrough(self) -> None:
        event = parse_stream_line("not json at all")

        assert event.kind is CodexStreamKind.PASSTHROUGH

    def test_transcript_skips_blanks_and_summarizes(self) -> None:
        events = parse_stream_transcript(SAMPLE_TRANSCRIPT)
        progress = summarize_events(events)

        assert [event.kind for event in events] == [
            CodexStreamKind.THREAD_STARTED,
            CodexStreamKind.TURN_STARTED,
            CodexStreamKind.ITEM_STARTED,
            CodexStreamKind.ITEM_COMPLETED,
            CodexStreamKind.TURN_COMPLETED,
            CodexStreamKind.TURN_FAILED,
            CodexStreamKind.ERROR,
            CodexStreamKind.PASSTHROUGH,
            CodexStreamKind.PASSTHROUGH,
        ]
        assert progress.threads_started == 1
        assert progress.turns_started == 1
        assert progress.items_started == 1
        assert progress.items_completed == 1
        assert progress.turns_completed == 1
        assert progress.failures == 1
        assert progress.errors == 1
        assert progress.passthrough == 2


@pytest.mark.unit
class TestStartLifecycle:
    async def test_start_runs_constructed_command(
        self, fake_store: _FakeSessionStore, fake_sandbox: SimpleNamespace
    ) -> None:
        result = await CodexDriver.start(USER_ID, "do the thing", "todo-1")

        assert result.state is AgentSessionState.RUNNING
        assert result.agent is AgentKind.CODEX
        assert fake_sandbox.commands.ran == [
            CodexDriver.ensure_installed_command(),
            CodexDriver.build_start_command("do the thing"),
        ]
