"""ClaudeDriver: drives Claude Code headlessly inside the user's sandbox."""

from collections.abc import Mapping
from enum import StrEnum
import json
import shlex
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.agent_lab_models import AgentKind
from app.services.agent_lab.driver import AgentDriver
from app.services.agent_lab.sandbox_setup import build_seed_command as build_lab_seed_command

_ENV_STRIP_PREFIX = "env -u ANTHROPIC_API_KEY"

CREDENTIAL_PATH = "~/.claude/.credentials.json"

INSTALL_VERSION = "2.1.286"


class ClaudeStreamKind(StrEnum):
    """Known stream-json event kinds; everything else is passthrough."""

    TEXT = "text"
    ERROR = "error"
    PERMISSION_DENIED = "permission_denied"
    PASSTHROUGH = "passthrough"


class ClaudeStreamEvent(BaseModel):
    """One classified stream-json line; raw keeps the original line verbatim."""

    model_config = ConfigDict(extra="forbid")

    kind: ClaudeStreamKind
    text: str | None = None
    raw: str


class ClaudeProgress(BaseModel):
    """Counts over parsed events for status display on the todo."""

    model_config = ConfigDict(extra="forbid")

    text_chars: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    permission_denials: int = Field(default=0, ge=0)
    passthrough: int = Field(default=0, ge=0)


def _contains_value(payload: object, target: str) -> bool:
    """Recursively check for an exact string value anywhere in a JSON payload."""
    if isinstance(payload, str):
        return payload == target
    if isinstance(payload, Mapping):
        return any(_contains_value(value, target) for value in payload.values())
    if isinstance(payload, list):
        return any(_contains_value(item, target) for item in payload)
    return False


def _extract_text(payload: Mapping[str, Any]) -> str | None:
    """Pull human text from representative envelopes; None when the shape is unknown."""
    part = payload.get("part")
    if isinstance(part, Mapping):
        part_text = part.get("text")
        if isinstance(part_text, str):
            return part_text
    top_text = payload.get("text")
    if isinstance(top_text, str):
        return top_text
    return None


def parse_stream_line(line: str) -> ClaudeStreamEvent:
    """Classify one stream-json line; unknown shapes pass through untouched."""
    stripped = line.strip()
    try:
        payload: object = json.loads(stripped)
    except json.JSONDecodeError:
        return ClaudeStreamEvent(kind=ClaudeStreamKind.PASSTHROUGH, raw=line)
    if not isinstance(payload, Mapping):
        return ClaudeStreamEvent(kind=ClaudeStreamKind.PASSTHROUGH, raw=line)
    mapping: Mapping[str, Any] = payload
    if _contains_value(mapping, "permission_denied"):
        return ClaudeStreamEvent(
            kind=ClaudeStreamKind.PERMISSION_DENIED, text=_extract_text(mapping), raw=line
        )
    if mapping.get("type") == "error" or mapping.get("is_error") is True or "error" in mapping:
        detail = mapping.get("error")
        text = detail if isinstance(detail, str) else _extract_text(mapping)
        return ClaudeStreamEvent(kind=ClaudeStreamKind.ERROR, text=text, raw=line)
    text = _extract_text(mapping)
    if text is not None:
        return ClaudeStreamEvent(kind=ClaudeStreamKind.TEXT, text=text, raw=line)
    return ClaudeStreamEvent(kind=ClaudeStreamKind.PASSTHROUGH, raw=line)


def parse_stream_transcript(transcript: str) -> list[ClaudeStreamEvent]:
    """Parse newline-delimited stream-json; blank lines are skipped."""
    return [parse_stream_line(line) for line in transcript.splitlines() if line.strip()]


def summarize_events(events: list[ClaudeStreamEvent]) -> ClaudeProgress:
    """Count parsed events into a status summary."""
    progress = ClaudeProgress()
    for event in events:
        if event.kind is ClaudeStreamKind.TEXT:
            progress.text_chars += len(event.text or "")
        elif event.kind is ClaudeStreamKind.ERROR:
            progress.errors += 1
        elif event.kind is ClaudeStreamKind.PERMISSION_DENIED:
            progress.permission_denials += 1
        else:
            progress.passthrough += 1
    return progress


class ClaudeDriver(AgentDriver):
    """Claude Code over `claude -p --output-format stream-json` with OAuth-safe env."""

    agent_kind: ClassVar[AgentKind] = AgentKind.CLAUDE

    credential_path: ClassVar[str] = CREDENTIAL_PATH

    install_bin: ClassVar[str] = "claude"
    install_package: ClassVar[str] = "@anthropic-ai/claude-code"
    install_version: ClassVar[str] = INSTALL_VERSION

    lab_hooks_enabled: ClassVar[bool] = True

    @classmethod
    def build_seed_command(cls, events_url: str, token: str) -> str | None:
        """Seed the lifecycle-push hooks fragment into the sandbox (additive to start)."""
        return build_lab_seed_command(events_url, token)

    @classmethod
    def _base(cls) -> str:
        """Claude invocation with the API-key shadow removed so OAuth applies."""
        return f'PATH="{cls.install_prefix}/bin:$PATH" {_ENV_STRIP_PREFIX} claude'

    @classmethod
    def build_start_command(cls, prompt: str) -> str:
        """Fresh headless run streaming newline-delimited JSON events."""
        return f"{cls._base()} -p {shlex.quote(prompt)} --output-format stream-json"

    @classmethod
    def build_message_command(cls, text: str) -> str:
        """Follow-up against the most recent session via --continue."""
        return f"{cls._base()} -p {shlex.quote(text)} --output-format stream-json --continue"

    @classmethod
    def build_resume_command(cls, session_ref: str, text: str) -> str:
        """Follow-up against an explicit session id via --resume."""
        return (
            f"{cls._base()} -p {shlex.quote(text)} "
            f"--output-format stream-json --resume {shlex.quote(session_ref)}"
        )

    @classmethod
    def build_stop_command(cls) -> str:
        """SIGTERM the foreground run; the shell stays green when nothing runs."""
        return 'pkill -TERM -f "claude -p" || true'

    @classmethod
    def build_stop_session_command(cls, session_ref: str) -> str:
        """Stop a background session while keeping its conversation resumable."""
        return f"{cls._base()} stop {shlex.quote(session_ref)}"

    @classmethod
    def sanitized_env(cls, env: Mapping[str, str]) -> dict[str, str]:
        """Copy env minus ANTHROPIC_API_KEY so pasted OAuth login is not shadowed."""
        stripped = dict(env)
        stripped.pop("ANTHROPIC_API_KEY", None)
        return stripped

    @classmethod
    def parse_output(cls, transcript: str) -> tuple[list[ClaudeStreamEvent], ClaudeProgress]:
        """Parse a stream-json transcript into events plus a progress summary."""
        events = parse_stream_transcript(transcript)
        return events, summarize_events(events)
