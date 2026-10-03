"""CodexDriver: drives Codex CLI headlessly inside the user's sandbox."""

from collections.abc import Mapping
from enum import StrEnum
import json
import shlex
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent_lab_models import AgentKind
from app.services.agent_lab.driver import AgentDriver

_ENV_STRIP_PREFIX = "env -u CODEX_API_KEY -u OPENAI_API_KEY"

CREDENTIAL_PATH = "~/.codex/auth.json"


class CodexStreamKind(StrEnum):
    """Known exec --json event types; everything else is passthrough."""

    THREAD_STARTED = "thread.started"
    TURN_STARTED = "turn.started"
    ITEM_STARTED = "item.started"
    ITEM_COMPLETED = "item.completed"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    ERROR = "error"
    PASSTHROUGH = "passthrough"


class CodexStreamEvent(BaseModel):
    """One classified exec JSONL line; raw keeps the original line verbatim."""

    model_config = ConfigDict(extra="forbid")

    kind: CodexStreamKind
    text: str | None = None
    raw: str


class CodexProgress(BaseModel):
    """Counts over parsed events for status display on the todo."""

    model_config = ConfigDict(extra="forbid")

    threads_started: int = Field(default=0, ge=0)
    turns_started: int = Field(default=0, ge=0)
    items_started: int = Field(default=0, ge=0)
    items_completed: int = Field(default=0, ge=0)
    turns_completed: int = Field(default=0, ge=0)
    failures: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    passthrough: int = Field(default=0, ge=0)


def parse_stream_line(line: str) -> CodexStreamEvent:
    """Classify one exec JSONL line; unknown shapes pass through untouched."""
    stripped = line.strip()
    try:
        payload: object = json.loads(stripped)
    except json.JSONDecodeError:
        return CodexStreamEvent(kind=CodexStreamKind.PASSTHROUGH, raw=line)
    if not isinstance(payload, Mapping):
        return CodexStreamEvent(kind=CodexStreamKind.PASSTHROUGH, raw=line)
    mapping: Mapping[str, Any] = payload
    event_type = mapping.get("type")
    if not isinstance(event_type, str):
        return CodexStreamEvent(kind=CodexStreamKind.PASSTHROUGH, raw=line)
    try:
        kind = CodexStreamKind(event_type)
    except ValueError:
        return CodexStreamEvent(kind=CodexStreamKind.PASSTHROUGH, raw=line)
    text = mapping.get("text")
    return CodexStreamEvent(kind=kind, text=text if isinstance(text, str) else None, raw=line)


def parse_stream_transcript(transcript: str) -> list[CodexStreamEvent]:
    """Parse newline-delimited exec JSONL; blank lines are skipped."""
    return [parse_stream_line(line) for line in transcript.splitlines() if line.strip()]


def summarize_events(events: list[CodexStreamEvent]) -> CodexProgress:
    """Count parsed events into a status summary."""
    progress = CodexProgress()
    for event in events:
        if event.kind is CodexStreamKind.THREAD_STARTED:
            progress.threads_started += 1
        elif event.kind is CodexStreamKind.TURN_STARTED:
            progress.turns_started += 1
        elif event.kind is CodexStreamKind.ITEM_STARTED:
            progress.items_started += 1
        elif event.kind is CodexStreamKind.ITEM_COMPLETED:
            progress.items_completed += 1
        elif event.kind is CodexStreamKind.TURN_COMPLETED:
            progress.turns_completed += 1
        elif event.kind is CodexStreamKind.TURN_FAILED:
            progress.failures += 1
        elif event.kind is CodexStreamKind.ERROR:
            progress.errors += 1
        else:
            progress.passthrough += 1
    return progress


class CodexDriver(AgentDriver):
    """Codex CLI over `codex exec --json` with file-auth-safe env."""

    agent_kind: ClassVar[AgentKind] = AgentKind.CODEX

    credential_path: ClassVar[str] = CREDENTIAL_PATH

    @classmethod
    def _base(cls) -> str:
        """Codex invocation with key env removed so saved file auth applies."""
        return f"{_ENV_STRIP_PREFIX} codex"

    @classmethod
    def _flags(cls) -> str:
        """Shared exec flags: JSONL output, writable workspace, no git requirement."""
        # workspace-write: the agent must write code, and the exec default is
        # read-only which would block every edit. --skip-git-repo-check is
        # required outside a git repo (spike section 2).
        return "--json --sandbox workspace-write --skip-git-repo-check"

    @classmethod
    def build_start_command(cls, prompt: str) -> str:
        """Fresh headless run streaming newline-delimited JSON events."""
        return f"{cls._base()} exec {shlex.quote(prompt)} {cls._flags()}"

    @classmethod
    def build_message_command(cls, text: str) -> str:
        """Follow-up against the most recent session via resume --last."""
        return f"{cls._base()} exec resume --last {shlex.quote(text)} {cls._flags()}"

    @classmethod
    def build_resume_command(cls, session_ref: str, text: str) -> str:
        """Follow-up against an explicit session id via exec resume."""
        return (
            f"{cls._base()} exec resume {shlex.quote(session_ref)} "
            f"{shlex.quote(text)} {cls._flags()}"
        )

    @classmethod
    def build_stop_command(cls) -> str:
        """SIGTERM the foreground exec run; the shell stays green when nothing runs."""
        # No `codex stop <id>` equivalent was observed (spike section 2: stop
        # method UNVERIFIED); exec is a one-shot foreground process, so SIGTERM
        # to the process is the expected stop.
        return 'pkill -TERM -f "codex exec" || true'

    @classmethod
    def sanitized_env(cls, env: Mapping[str, str]) -> dict[str, str]:
        """Copy env minus key vars so saved file auth is not shadowed."""
        stripped = dict(env)
        stripped.pop("CODEX_API_KEY", None)
        stripped.pop("OPENAI_API_KEY", None)
        return stripped

    @classmethod
    def parse_output(cls, transcript: str) -> tuple[list[CodexStreamEvent], CodexProgress]:
        """Parse an exec JSONL transcript into events plus a progress summary."""
        events = parse_stream_transcript(transcript)
        return events, summarize_events(events)
