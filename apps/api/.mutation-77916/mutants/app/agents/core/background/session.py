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

from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable
from app.models.user_models import AuthenticatedUser
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
    # Integrations with a background handoff in flight this run. Guards against a
    # second concurrent handoff to the same integration, whose subagent would share
    # the deterministic checkpoint thread id and corrupt it. (Results live in Redis —
    # see ``bg_results`` — because they must survive the executor's approval pause.)
    bg_integrations: set[str] = field(default_factory=set)
    # Voice-mode streams: the executor's finalize step publishes a TTS-only
    # ``voice_tts`` frame with its narrated answer for the voice agent to speak.
    voice_mode: bool = False
    # tool_call_ids whose result has already been streamed on this stream. A
    # subagent handed off to from an executor tool is a *nested* run, and
    # langgraph's "messages" mode replays its chunks into the outer run's stream
    # carrying the inner run's metadata — same node, same checkpoint namespace —
    # so neither the payload nor its metadata says which run it belongs to. Both
    # drivers would emit a tool_output for it, and only the subagent's copy
    # carries a subagent_id, so the client renders the second one outside the
    # subagent's row. A tool_call_id is unique per call, so a second sighting is
    # always the echo — but arrival order does not say which sighting is the
    # subagent's, so the owner below decides rather than whoever looks first.
    streamed_tool_outputs: set[str] = field(default_factory=set)
    # tool_call_id -> the subagent_id of the run that ANNOUNCED it (None for the
    # executor's own calls). "updates" mode does not carry nested runs, so only
    # the owning driver ever announces a call, and it does so before any result
    # exists. That makes this the one fact that survives the echo.
    tool_output_owners: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutorRun:
    """Immutable context for one background executor run."""

    stream_id: str
    conversation_id: str
    user: AuthenticatedUser
    kind: RunKind
    task_id: str | None
    user_message_id: str | None
    #: The ORIGINAL live turn's bot message id, present only when this run is a
    #: HIL pause/resume of that turn's executor — see ``executor_runner._record_pause``.
    #: A plain queued (busy-lock) dispatch never carries this, so its result still
    #: mints a fresh message keyed on ``task_id``.
    bot_message_id: str | None = None
    workflow_id: str | None = None
    workflow_title: str = ""
    workflow_notify_on_completion: bool = True

    @classmethod
    def from_configurable(
        cls,
        configurable: AgentConfigurable,
        *,
        stream_id: str,
        conversation_id: str,
        kind: RunKind,
        task_id: str | None,
        user_message_id: str | None,
        bot_message_id: str | None = None,
    ) -> "ExecutorRun":
        """Build the run context from a LangGraph ``configurable`` dict."""
        return cls(
            stream_id=stream_id,
            conversation_id=conversation_id,
            user={
                "user_id": configurable.get("user_id", ""),
                "email": configurable.get("email", ""),
                "name": configurable.get("user_name", ""),
                # Carry the home timezone forward so the comms re-voicing run
                # reads the user's zone via build_agent_config instead of
                # silently falling back to UTC.
                "timezone": configurable.get("user_timezone"),
            },
            kind=kind,
            task_id=task_id,
            user_message_id=user_message_id,
            bot_message_id=bot_message_id,
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
        log.warning(
            f"{LogTag.AGENT} Implicit session creation — registration ordering gap",
            stream_id=stream_id,
        )
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


def note_tool_output_owner(stream_id: str, tool_call_id: str, subagent_id: str | None) -> None:
    """Record which run announced this call, so only it may stream the result."""
    session = _sessions.get(stream_id)
    if session is None or not tool_call_id:
        return
    session.tool_output_owners.setdefault(tool_call_id, subagent_id)


def claim_tool_output(stream_id: str, tool_call_id: str, subagent_id: str | None = None) -> bool:
    """Claim the right to stream this tool result, once per stream.

    Returns True for the owning caller and False for every echo. Fails open when
    the stream has no session (a bare driver run, or any caller outside the
    background machinery): with nowhere to record the claim there is nothing to
    echo it either, so suppressing would only drop the sole copy.

    A run that did not announce the call is always the echo, however early it
    looks. Deciding on arrival order instead let the outer driver — which sees
    the nested run's ToolMessage but has no ``subagent_id`` — win on a slow
    machine and publish the result untagged, stranding the card outside the
    subagent's row. An unannounced call still fails open, so a HIL resume (whose
    announcement happened in the run before the pause) keeps streaming.
    """
    session = _sessions.get(stream_id)
    if session is None or not tool_call_id:
        return True
    owner = session.tool_output_owners.get(tool_call_id, subagent_id)
    if owner != subagent_id:
        return False
    if tool_call_id in session.streamed_tool_outputs:
        return False
    session.streamed_tool_outputs.add(tool_call_id)
    return True


def get_pending_subagents(stream_id: str) -> int:
    """Return number of pending background subagents for a stream."""
    session = _sessions.get(stream_id)
    return session.pending_subagents if session else 0


def claim_bg_integration(stream_id: str, integration_id: str) -> bool:
    """Claim the one background-handoff slot for an integration this run.

    ``False`` means one is already in flight — the caller must fall back to a
    blocking handoff, because a second detached subagent for the same integration
    would share its deterministic checkpoint thread id.
    """
    session = get_or_create_session(stream_id)
    if integration_id in session.bg_integrations:
        return False
    session.bg_integrations.add(integration_id)
    return True


def release_bg_integration(stream_id: str, integration_id: str) -> None:
    """Release an integration's background-handoff slot (task finished or parked)."""
    session = _sessions.get(stream_id)
    if session is not None:
        session.bg_integrations.discard(integration_id)


def has_bg_integration(stream_id: str, integration_id: str) -> bool:
    """Whether a background handoff for this integration is in flight this run."""
    session = _sessions.get(stream_id)
    return bool(session and integration_id in session.bg_integrations)
