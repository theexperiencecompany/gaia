"""Dumb-pipe persistence for agent lifecycle events pushed from the sandbox.

The receiver authenticates the caller, checks the session belongs to them,
and stores the payload's tail verbatim on the run's tracked todo. A future
supervisor reads the tail; until then this module is storage plus a wake-up
nudge, never a parser.
"""

from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Final

from pydantic import BaseModel

from app.agents.core.background.workflow_platform_delivery import deliver_result_to_platforms
from app.constants.execute import LAB_EVENT_MAX_RAW_BYTES, LAB_LOG_TAIL_MAX_CHARS
from app.constants.todos import TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.decorators.entitlements import SubscriptionRequiredException, is_paid
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.feature_flags import is_agent_lab_enabled
from app.services.todo_activity import record_activity
from app.utils.auth_utils import load_user_context
from app.utils.errors import AppError
from shared.py.wide_events import log

# Claude hook event name → pipe kind. Unknown names fall back to lowercased,
# so a new hook event is stored, never 422d.
HOOK_KIND_BY_EVENT: Final[dict[str, str]] = {
    "Stop": "stop",
    "Notification": "notification",
    "PreToolUse": "pre_tool_use",
    "PostToolUse": "post_tool_use",
    "UserPromptSubmit": "user_prompt_submit",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "SubagentStop": "subagent_stop",
    "PreCompact": "pre_compact",
}

# Kinds that wake the user: questions, completions, failures. Everything else
# (heartbeats, progress chatter) is persist-only — the SILENCE half of the
# todo_run_delivery pattern. Compared case-insensitively; the stored kind keeps
# its original spelling.
LAB_WAKE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "stop",
        "notification",
        "notification_other",
        "question",
        "completion",
        "idle",
        "permission",
        "error",
    }
)

# The lab tail section in log.md: everything from this marker is replaced by
# each event, so the section holds exactly one event's tail, never history.
LAB_TAIL_MARKER: Final[str] = "<!-- lab-tail -->"


class ParsedLabEvent(BaseModel):
    """One normalized lifecycle push: the session, its free-form kind, the raw payload."""

    session_id: str
    kind: str
    raw: dict[str, Any]


class LabEventReceipt(BaseModel):
    """What the receiver hands back for one accepted push: where it was filed."""

    id: str
    todo_id: str


def parse_lab_event_body(body: object) -> ParsedLabEvent:
    """Normalize either accepted shape (canonical or raw hook POST); fails loud only on an unusable body."""
    if not isinstance(body, dict):
        raise AppError(
            message="agent lab event must be a JSON object",
            why="the body is not an object at all",
            fix="push {session_id, kind, raw} or the raw hook payload",
            status_code=422,
            code="agent_lab_event_not_identifiable",
        )
    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise AppError(
            message="agent lab event is missing its identity",
            why="session_id is required on every shape",
            fix="push {session_id, kind, raw} with a valid session token",
            status_code=422,
            code="agent_lab_event_not_identifiable",
        )
    kind = body.get("kind")
    if not isinstance(kind, str) or not kind:
        hook_event = body.get("hook_event_name")
        if not isinstance(hook_event, str) or not hook_event:
            raise AppError(
                message="agent lab event is missing its kind",
                why="neither kind nor hook_event_name names this event",
                fix="push {session_id, kind, raw} or the raw hook payload",
                status_code=422,
                code="agent_lab_event_not_identifiable",
            )
        kind = HOOK_KIND_BY_EVENT.get(hook_event, hook_event.lower())
    raw = body.get("raw")
    if "hook_event_name" in body and not isinstance(raw, dict):
        raw = body
    elif not isinstance(raw, dict):
        raw = {"value": raw} if raw is not None else {}
    return ParsedLabEvent(session_id=session_id, kind=kind, raw=raw)


async def record_lab_event(
    session_id: str, *, user_id: str, kind: str, raw: dict[str, Any]
) -> LabEventReceipt:
    """File one raw lifecycle event onto its run's tracked todo; fails loud on misuse."""
    _reject_oversize(raw)
    if not await is_paid(user_id):
        raise SubscriptionRequiredException()
    if not await is_agent_lab_enabled(user_id):
        raise AppError(
            message="agent lab is disabled for this user",
            why="the AGENT_LAB flag was revoked after the token was minted",
            fix="re-enable the flag, then start a fresh lab run for a live token",
            status_code=403,
            code="agent_lab_disabled",
        )
    todo = await todo_repository.find_by_reference(user_id, session_id)
    if todo is None:
        raise AppError(
            message="no tracked todo carries this lab run",
            why=f"run {session_id} is not recorded on any of the user's todos",
            fix="record its run id on the todo's references",
            status_code=404,
            code="agent_lab_run_unknown",
        )
    tail = _render_tail(session_id, kind, raw)
    duplicate = _tail_matches(todo, session_id, kind, raw)
    await _overwrite_lab_tail(todo, user_id, tail)
    if duplicate:
        note = "duplicate suppressed: identical event already filed, no second nudge"
    else:
        note = await _wake_or_quiet(
            todo, user_id=user_id, session_id=session_id, kind=kind, raw=raw
        )
    await record_activity(
        todo.id,
        user_id,
        TodoActivityEvent.LAB_EVENT_RECEIVED,
        f"lab {kind} received (tail={len(tail)} chars); {note}",
    )
    return LabEventReceipt(id=session_id, todo_id=todo.id)


def _reject_oversize(raw: dict[str, Any]) -> None:
    """Refuse a raw payload over the cap before it touches the budget or the database."""
    if len(json.dumps(raw).encode()) > LAB_EVENT_MAX_RAW_BYTES:
        raise AppError(
            message="agent lab event payload is too large",
            why=f"raw serializes past {LAB_EVENT_MAX_RAW_BYTES} bytes",
            fix="push a summary or a tail slice, not the whole transcript",
            status_code=413,
            code="agent_lab_event_too_large",
        )


def _event_fingerprint(session_id: str, kind: str, raw: dict[str, Any]) -> str:
    """Short stable hash so a re-POSTed identical event is recognizable (the catch-all hook double-fires)."""
    digest = hashlib.sha256(
        json.dumps(
            {"s": session_id, "k": kind.lower(), "r": raw}, sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    return digest[:12]


def _tail_matches(todo: TodoDocument, session_id: str, kind: str, raw: dict[str, Any]) -> bool:
    """Whether the filed lab tail already carries this exact event."""
    content = todo.log_content or ""
    if LAB_TAIL_MARKER not in content:
        return False
    want = _event_fingerprint(session_id, kind, raw)
    return f"[lab:{kind.lower()}#{want}]" in content


def _render_tail(session_id: str, kind: str, raw: dict[str, Any]) -> str:
    """One bounded tail entry: timestamp, kind, fingerprint, and the raw tail."""
    stamp = datetime.now(UTC).isoformat()
    fingerprint = _event_fingerprint(session_id, kind, raw)
    tail = json.dumps(raw, default=str)[:LAB_LOG_TAIL_MAX_CHARS]
    return f"## {stamp} [lab:{kind.lower()}#{fingerprint}] session {session_id}\n```json\n{tail}\n```"


async def _overwrite_lab_tail(todo: TodoDocument, user_id: str, tail: str) -> None:
    """Replace the marked lab section with this event's tail; never append, so a chatty run cannot grow the log."""
    head = (todo.log_content or "").split(LAB_TAIL_MARKER)[0].rstrip()
    content = f"{head}\n\n{LAB_TAIL_MARKER}\n{tail}\n" if head else f"{LAB_TAIL_MARKER}\n{tail}\n"
    updated = await todo_repository.replace_note_fields(
        todo.id, user_id, update=TodoUpdate(log_content=content), expected_updated_at=None
    )
    if updated is None:
        raise AppError(
            message="the lab run's todo vanished mid-write",
            why=f"todo {todo.id} is gone after it was resolved",
            fix="re-push the event once the todo exists again",
            status_code=404,
            code="agent_lab_todo_missing",
        )


async def _wake_or_quiet(
    todo: TodoDocument, *, user_id: str, session_id: str, kind: str, raw: dict[str, Any]
) -> str:
    """Deliver questions/completions to the user's chat; never raises — a lost nudge costs the activity line, not the event."""
    if kind.lower() not in LAB_WAKE_KINDS:
        return f"kept quiet: kind {kind!r} needs no reply"
    if not todo.notify_on_run:
        return "result not sent: delivery is off for this todo"
    user = await load_user_context(user_id)
    if user is None:
        log.warning("lab_event wake skipped: user not found", user_id=user_id)
        return "result not sent: user not found"
    try:
        platform = await deliver_result_to_platforms(
            user=user,
            user_id=user_id,
            notification_text=_lab_wake_text(todo.title, session_id, kind, raw),
            origin=f'agent lab run {session_id} on todo "{todo.title}" (id {todo.id})',
        )
    except Exception as e:
        log.error(
            "lab_event wake delivery failed",
            todo_id=todo.id,
            user_id=user_id,
            error_type=type(e).__name__,
        )
        return "result not sent: delivery failed"
    if platform is None:
        return "result not sent: no linked chat app accepted it"
    return f"result sent on {platform.value}"


def _lab_wake_text(todo_title: str, session_id: str, kind: str, raw: dict[str, Any]) -> str:
    """One short chat message for a wake-worthy event: what happened plus its detail."""
    headline = {
        "stop": "finished",
        "completion": "finished",
        "notification": "needs your input",
        "question": "has a question",
        "permission": "is asking for permission",
        "idle": "went idle",
        "error": "hit an error",
    }.get(kind.lower(), f"sent {kind}")
    detail = raw.get("message") or raw.get("question") or raw.get("text") or ""
    detail = str(detail).strip().replace("\n", " ")[:500]
    text = f'Your agent lab run on "{todo_title}" {headline} (session {session_id}).'
    return f"{text} Detail: {detail}" if detail else text
