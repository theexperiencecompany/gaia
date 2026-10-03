"""OpenCodeDriver: drives OpenCode CLI headlessly inside the user's sandbox."""

from collections.abc import Mapping
from enum import StrEnum
import json
import shlex
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent_lab_models import AgentKind
from app.services.agent_lab.driver import AgentDriver

CREDENTIAL_PATH = "~/.local/share/opencode/auth.json"

DEFAULT_MODEL = "opencode/muse-spark-1.3-contributor-free"

INSTALL_VERSION = "2.0.2"


class OpenCodeStreamKind(StrEnum):
    """Known run --format json event types; everything else is passthrough."""

    TEXT = "text"
    STEP_FINISH = "step_finish"
    PASSTHROUGH = "passthrough"


class OpenCodeStreamEvent(BaseModel):
    """One classified run JSONL line; raw keeps the original line verbatim."""

    model_config = ConfigDict(extra="forbid")

    kind: OpenCodeStreamKind
    text: str | None = None
    raw: str


class OpenCodeProgress(BaseModel):
    """Counts over parsed events for status display on the todo."""

    model_config = ConfigDict(extra="forbid")

    text_chars: int = Field(default=0, ge=0)
    steps_finished: int = Field(default=0, ge=0)
    passthrough: int = Field(default=0, ge=0)


def parse_stream_line(line: str) -> OpenCodeStreamEvent:
    """Classify one run JSONL line; unknown shapes pass through untouched."""
    stripped = line.strip()
    try:
        payload: object = json.loads(stripped)
    except json.JSONDecodeError:
        return OpenCodeStreamEvent(kind=OpenCodeStreamKind.PASSTHROUGH, raw=line)
    if not isinstance(payload, Mapping):
        return OpenCodeStreamEvent(kind=OpenCodeStreamKind.PASSTHROUGH, raw=line)
    mapping: Mapping[str, Any] = payload
    event_type = mapping.get("type")
    if event_type == OpenCodeStreamKind.TEXT:
        part = mapping.get("part")
        if isinstance(part, Mapping):
            part_text = part.get("text")
            if isinstance(part_text, str):
                return OpenCodeStreamEvent(kind=OpenCodeStreamKind.TEXT, text=part_text, raw=line)
    elif event_type == OpenCodeStreamKind.STEP_FINISH:
        return OpenCodeStreamEvent(kind=OpenCodeStreamKind.STEP_FINISH, raw=line)
    return OpenCodeStreamEvent(kind=OpenCodeStreamKind.PASSTHROUGH, raw=line)


def parse_stream_transcript(transcript: str) -> list[OpenCodeStreamEvent]:
    """Parse newline-delimited run JSONL; blank lines are skipped."""
    return [parse_stream_line(line) for line in transcript.splitlines() if line.strip()]


def summarize_events(events: list[OpenCodeStreamEvent]) -> OpenCodeProgress:
    """Count parsed events into a status summary."""
    progress = OpenCodeProgress()
    for event in events:
        if event.kind is OpenCodeStreamKind.TEXT:
            progress.text_chars += len(event.text or "")
        elif event.kind is OpenCodeStreamKind.STEP_FINISH:
            progress.steps_finished += 1
        else:
            progress.passthrough += 1
    return progress


class OpenCodeDriver(AgentDriver):
    """OpenCode CLI over `opencode run --format json` with Zen file auth."""

    agent_kind: ClassVar[AgentKind] = AgentKind.OPENCODE

    credential_path: ClassVar[str] = CREDENTIAL_PATH

    default_model: ClassVar[str] = DEFAULT_MODEL

    install_bin: ClassVar[str] = "opencode"
    install_package: ClassVar[str] = "@opencode/cli"
    install_version: ClassVar[str] = INSTALL_VERSION

    @classmethod
    def _base(cls) -> str:
        """Plain opencode invocation; no env shadow var verified, so none stripped."""
        return f'PATH="{cls.install_prefix}/bin:$PATH" opencode'

    @classmethod
    def _model_flag(cls, model: str | None) -> str:
        """-m passthrough; callers may override the observed Zen free default."""
        return f"-m {shlex.quote(model or cls.default_model)}"

    @classmethod
    def build_start_command(cls, prompt: str, model: str | None = None) -> str:
        """Fresh headless run streaming newline-delimited JSON events."""
        return f"{cls._base()} run --format json {cls._model_flag(model)} {shlex.quote(prompt)}"

    @classmethod
    def build_message_command(cls, text: str, model: str | None = None) -> str:
        """Follow-up against the most recent session via -c."""
        return f"{cls._base()} run --format json {cls._model_flag(model)} -c {shlex.quote(text)}"

    @classmethod
    def build_resume_command(cls, session_ref: str, text: str, model: str | None = None) -> str:
        """Follow-up against an explicit session id via -s."""
        return (
            f"{cls._base()} run --format json {cls._model_flag(model)} "
            f"-s {shlex.quote(session_ref)} {shlex.quote(text)}"
        )

    @classmethod
    def build_stop_command(cls) -> str:
        """SIGTERM the foreground run; the shell stays green when nothing runs."""
        # serve + run --attach long-running mode NOT implemented: one-shot run
        # per message keeps the ABC contract, so there is no server to stop.
        return 'pkill -TERM -f "opencode run" || true'

    @classmethod
    def sanitized_env(cls, env: Mapping[str, str]) -> dict[str, str]:
        """Copy env unchanged; no key-var shadow of auth.json is verified."""
        return dict(env)

    @classmethod
    def parse_output(cls, transcript: str) -> tuple[list[OpenCodeStreamEvent], OpenCodeProgress]:
        """Parse a run JSONL transcript into events plus a progress summary."""
        events = parse_stream_transcript(transcript)
        return events, summarize_events(events)
