"""Per-stream orchestration state for background executor runs.

One ``StreamSession`` per ``stream_id`` replaces the five parallel
module-level dicts that previously lived in ``inbox.py`` (spawned flags,
done events, subagent counters, subagent results, tool-event collectors).
Tearing down a session drops all of its state at once — there is no
per-dict cleanup to forget.

``ExecutorRun`` is the immutable identity of a single executor run: how it
was spawned (``RunKind``), which conversation/user it belongs to, and its
workflow context. It owns the tool_data ownership rule
(``executor_owns_tool_data``) so terminal handlers consult one source of
truth instead of re-deriving ``is_queued or workflow_id`` ad hoc.

Sessions are intentionally in-process (asyncio primitives cannot cross
process boundaries); the ``executor:busy`` Redis key remains the
cross-process guard for multi-worker deployments.
"""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from shared.py.wide_events import log


class RunKind(StrEnum):
    """How an executor run was spawned.

    LIVE   — dispatched by ``call_executor`` inside a comms run (chat or
             silent/workflow); tool events reach the user over the comms
             stream and the comms path attaches them to its own message.
    QUEUED — popped from the per-conversation executor queue; the run has
             its own ``queued_*`` stream and self-publishes its results.
    """

    LIVE = "live"
    QUEUED = "queued"


@dataclass
class StreamSession:
    """All per-stream orchestration state, in one place."""

    stream_id: str
    kind: RunKind
    executor_spawned: bool = False
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    pending_subagents: int = 0
    subagent_results: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutorRun:
    """Immutable context for one background executor run."""

    stream_id: str
    conversation_id: str
    user: dict
    kind: RunKind
    task_id: str | None
    user_message_id: str | None
    workflow_id: str | None = None
    workflow_title: str = ""
    workflow_notify_on_completion: bool = True

    @classmethod
    def from_configurable(
        cls,
        configurable: dict[str, Any],
        *,
        stream_id: str,
        conversation_id: str,
        kind: RunKind,
        task_id: str | None,
        user_message_id: str | None,
    ) -> "ExecutorRun":
        """Build the run context from a LangGraph ``configurable`` dict."""
        return cls(
            stream_id=stream_id,
            conversation_id=conversation_id,
            user={
                "user_id": configurable.get("user_id", ""),
                "email": configurable.get("email", ""),
                "name": configurable.get("user_name", ""),
            },
            kind=kind,
            task_id=task_id,
            user_message_id=user_message_id,
            workflow_id=configurable.get("workflow_id"),
            workflow_title=configurable.get("workflow_title", ""),
            workflow_notify_on_completion=configurable.get("workflow_notify_on_completion", True),
        )

    @property
    def is_queued(self) -> bool:
        return self.kind is RunKind.QUEUED

    @property
    def executor_owns_tool_data(self) -> bool:
        """Whether this run persists its own tool_data.

        The real axis is live-streamed vs background-detached, NOT "is it a
        workflow":
          - live-streamed (chat): a comms stream attaches the executor's
            tool_data to the comms message, so the executor must NOT also persist
            it (single ownership prevents duplicate cards);
          - background-detached (queued, scheduled workflow): no comms consumer
            attaches cards, so the executor self-persists.

        ``workflow_id is not None`` stands in for "background-detached" only
        because every workflow run today is silent/scheduled. When a live
        *interactive* workflow lands (streamed from the workflow page like chat),
        it must be dispatched as ``RunKind.LIVE`` and this ``workflow_id`` clause
        dropped — otherwise it would self-persist instead of streaming.
        """
        return self.kind is RunKind.QUEUED or self.workflow_id is not None


# ── Session registry ─────────────────────────────────────────────────

_sessions: dict[str, StreamSession] = {}


def create_session(stream_id: str, kind: RunKind) -> StreamSession:
    """Create (or replace) the session for a stream."""
    session = StreamSession(stream_id=stream_id, kind=kind)
    _sessions[stream_id] = session
    return session


def get_session(stream_id: str) -> StreamSession | None:
    """Return the session for a stream, or None."""
    return _sessions.get(stream_id)


def get_or_create_session(stream_id: str, kind: RunKind = RunKind.LIVE) -> StreamSession:
    """Return the session, creating one if missing.

    Implicit creation preserves the old dicts' auto-vivify behavior but is
    logged: in a correctly ordered flow the session is always registered
    (chat stream / silent agent / queue pop) before anything touches it.
    """
    session = _sessions.get(stream_id)
    if session is None:
        log.warning("Implicit session creation — registration ordering gap", stream_id=stream_id)
        session = create_session(stream_id, kind)
    return session


def teardown_session(stream_id: str) -> None:
    """Drop all orchestration state for a stream. Safe to call multiple times."""
    _sessions.pop(stream_id, None)


# ── Executor lifecycle helpers ───────────────────────────────────────


def mark_executor_spawned(stream_id: str) -> None:
    """Record that call_executor spawned a background task for this stream."""
    get_or_create_session(stream_id).executor_spawned = True


def was_executor_spawned(stream_id: str) -> bool:
    """Return True if call_executor successfully spawned for this stream."""
    session = _sessions.get(stream_id)
    return bool(session and session.executor_spawned)


def signal_executor_done(stream_id: str) -> None:
    """Wake any waiter blocked on the executor finishing for this stream."""
    session = _sessions.get(stream_id)
    if session is not None:
        session.done_event.set()


# ── Background subagent coordination ─────────────────────────────────
# Incremented by handoff(background=True), decremented by
# run_subagent_background. wait_for_subagents polls the counter and drains
# the results once it hits zero.


def increment_pending_subagents(stream_id: str) -> int:
    """Increment pending background subagent count. Returns new count."""
    session = get_or_create_session(stream_id)
    session.pending_subagents += 1
    return session.pending_subagents


def decrement_pending_subagents(stream_id: str) -> int:
    """Decrement pending background subagent count. Returns new count (min 0)."""
    session = _sessions.get(stream_id)
    if session is None:
        return 0
    session.pending_subagents = max(0, session.pending_subagents - 1)
    return session.pending_subagents


def get_pending_subagents(stream_id: str) -> int:
    """Return number of pending background subagents for a stream."""
    session = _sessions.get(stream_id)
    return session.pending_subagents if session else 0


def append_bg_subagent_result(stream_id: str, agent: str, result: str) -> None:
    """Append a background subagent's final result for this stream."""
    get_or_create_session(stream_id).subagent_results.append({"agent": agent, "message": result})


def drain_bg_subagent_results(stream_id: str) -> list[dict[str, str]]:
    """Return and clear all collected background subagent results for this stream."""
    session = _sessions.get(stream_id)
    if session is None:
        return []
    results = list(session.subagent_results)
    session.subagent_results.clear()
    return results
