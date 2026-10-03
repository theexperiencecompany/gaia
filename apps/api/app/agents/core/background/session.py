"""Per-stream orchestration state for background executor runs.

One StreamSession per stream_id replaces five parallel module-level dicts
that previously lived in inbox.py; tearing it down drops all state at once.
ExecutorRun is the immutable identity of a single executor run and owns
the tool_data ownership rule (executor_owns_tool_data). Sessions are
intentionally in-process; the executor:busy Redis key is the cross-process
guard for multi-worker deployments.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, AgentConfigurableView
from app.models.chat_models import SourceCategory
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from shared.py.wide_events import current_workflow_execution_id, log


class RunKind(StrEnum):
    """How an executor run was spawned.

    LIVE   — dispatched by call_executor inside a comms run (chat or
             silent/workflow); tool events reach the user over the comms
             stream and the comms path attaches them to its own message.
    QUEUED — a DETACHED run: it owns its own stream and self-publishes its
             results. Materialized by prepare_run_from_item for a HIL approval
             resume or a background-subagent collection wake. The name predates
             the executor queue's removal; nothing is queued.
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
    #: Set with ``done_event`` when the executor's run ended in an error rather
    #: than a result. The silent path reads it so a fire whose executor died is
    #: recorded as failed instead of as the apology comms wrote about it.
    executor_failed: bool = False
    #: Why, when it failed: the executor's own error text, or the wait's.
    executor_failure: str | None = None
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    # Voice-mode streams: the executor's finalize step publishes a TTS-only
    # ``voice_tts`` frame with its narrated answer for the voice agent to speak.
    voice_mode: bool = False
    # ``perf_counter`` of this stream's first executor frame, set once by the
    # writer. A redirect's second run must not inherit the cancelled run's.
    executor_first_frame_perf: float | None = None
    # tool_call_ids already streamed: a nested subagent run's chunks replay
    # into the outer stream too, so a second sighting is always the echo.
    streamed_tool_outputs: set[str] = field(default_factory=set)
    # tool_call_id -> the subagent_id of the run that ANNOUNCED it (None for
    # the executor's own calls) — the one fact that survives the echo above.
    tool_output_owners: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class TodoRun:
    """The tracked todo a background executor run is executing, and what woke it."""

    todo_id: str
    trigger_type: TriggerType


@dataclass(frozen=True)
class RunIdentity:
    """The caller-supplied identity of one executor run.

    Grouped so ExecutorRun.from_configurable takes the run's identity as one
    object beside the LangGraph configurable it reads the rest from.
    """

    conversation_id: str
    task_id: str | None
    user_message_id: str | None
    #: Empty until the run is dispatched: a queued item is written before its
    #: stream exists (``prepare_run_from_item`` mints one at dequeue), and a
    #: run with no stream yet is by definition a queued one.
    stream_id: str = ""
    kind: RunKind = RunKind.QUEUED
    #: The ORIGINAL live turn's bot message id — see ``ExecutorRun.bot_message_id``.
    bot_message_id: str | None = None
    #: ``perf_counter`` stamped by ``call_executor`` at dispatch. Run start
    #: minus this is the queue wait. ``None`` on pre-stamp runs; cleared on
    #: HIL pause re-record (the resume's wait was user time, not queue time).
    t_dispatch_perf: float | None = None
    #: Whether the run waited on the per-conversation busy-lock queue before it
    #: started. Metric-only: a HIL resume is ``RunKind.QUEUED`` (it runs on its
    #: own stream) but never queued on the lock, so it must not label as queued.
    queued: bool = False


def run_user_from_configurable(configurable: AgentConfigurable) -> AuthenticatedUser:
    """Rebuild the user a run acts for from its configurable — the identity a detached run starts from."""
    return _user_from_view(AgentConfigurableView.model_validate(configurable))


def _user_from_view(view: AgentConfigurableView) -> AuthenticatedUser:
    # A bare identity (no auth path produced it — see AuthenticatedUser.auth_provider).
    # An absent identity key rebuilds as "", one carried as None stays None.
    present = view.model_fields_set
    return AuthenticatedUser(
        user_id=view.user_id or "",
        email=view.email if "email" in present else "",
        name=view.user_name if "user_name" in present else "",
        # Carry the home timezone forward so the comms re-voicing run reads the
        # user's zone via build_agent_config instead of silently falling back to UTC.
        timezone=view.user_timezone,
    )


@dataclass(frozen=True)
class ExecutorRun:
    """Immutable context for one background executor run."""

    stream_id: str
    conversation_id: str
    user: AuthenticatedUser
    kind: RunKind
    task_id: str | None
    user_message_id: str | None
    #: The ORIGINAL live turn's bot message id, present only for a HIL
    #: pause/resume (see ``executor_runner._record_pause``); a plain queued
    #: dispatch mints a fresh message keyed on ``task_id`` instead.
    bot_message_id: str | None = None
    workflow_id: str | None = None
    #: The workflow execution this run belongs to. Read off the workflow task's
    #: wide event at construction (it exists nowhere else), so the executor's
    #: own boundary can carry it and the ledger can attribute its calls to the run.
    workflow_execution_id: str | None = None
    workflow_title: str = ""
    workflow_notify_on_completion: bool = True
    active_todo_id: str | None = None
    #: Set only on a tracked todo's own scheduled/triggered run: its result goes
    #: through todo delivery, never into a conversation (the run's has none).
    todo_run: TodoRun | None = None
    #: Where the turn that spawned this run came from. Defaults to background
    #: work, matching ``build_agent_config``: the only callers that leave the
    #: source unset are the silent background paths.
    source_category: SourceCategory = SourceCategory.BG
    #: Dispatch stamp carried from ``RunIdentity`` — see its field comment.
    t_dispatch_perf: float | None = None
    #: Busy-lock queue origin, carried from ``RunIdentity`` — see its comment.
    queued: bool = False

    @classmethod
    def from_configurable(
        cls,
        configurable: AgentConfigurable,
        *,
        identity: RunIdentity,
        workflow_execution_id: str | None = None,
    ) -> "ExecutorRun":
        """Build the run context from a LangGraph configurable dict.

        workflow_execution_id is the stored one when rebuilding from a queue
        item or HIL resume record (those rebuild in a context with no workflow
        boundary); a live dispatch leaves it unset and reads the execution in
        flight off the boundary it is being built in.
        """
        view = AgentConfigurableView.model_validate(configurable)
        return cls(
            stream_id=identity.stream_id,
            conversation_id=identity.conversation_id,
            user=_user_from_view(view),
            kind=identity.kind,
            task_id=identity.task_id,
            user_message_id=identity.user_message_id,
            bot_message_id=identity.bot_message_id,
            workflow_id=view.workflow_id,
            workflow_execution_id=workflow_execution_id or current_workflow_execution_id(),
            workflow_title=view.workflow_title,
            workflow_notify_on_completion=view.workflow_notify_on_completion,
            active_todo_id=view.active_todo_id,
            source_category=SourceCategory(view.source_category or SourceCategory.BG.value),
            t_dispatch_perf=identity.t_dispatch_perf,
            queued=identity.queued,
        )

    @property
    def identity(self) -> RunIdentity:
        """Return this run's identity, in the shape a stored run item is written from."""
        return RunIdentity(
            stream_id=self.stream_id,
            conversation_id=self.conversation_id,
            kind=self.kind,
            task_id=self.task_id,
            user_message_id=self.user_message_id,
            bot_message_id=self.bot_message_id,
            t_dispatch_perf=self.t_dispatch_perf,
            queued=self.queued,
        )

    @property
    def is_queued(self) -> bool:
        return self.kind is RunKind.QUEUED

    @property
    def render_message_id(self) -> str | None:
        """The chat message this run's frames render into: the live turn's, a resumed turn's, or its own placeholder."""
        return self.bot_message_id or (self.task_id if self.is_queued else None)

    @property
    def renders_native_cards(self) -> bool:
        """Whether this run's items reach the user as cards rather than as words.

        Only first-party clients render tool cards. A bot conversation gets plain
        text over its platform API and a scheduled workflow gets a notification,
        so telling comms "these items are already on the user's screen" there
        suppresses the only copy of the data the user would ever see.
        """
        return self.source_category is SourceCategory.UI

    @property
    def executor_owns_tool_data(self) -> bool:
        """Whether this run persists its own tool_data.

        The real axis is live-streamed vs background-detached: live-streamed
        attaches tool_data to the comms message; background-detached has no
        comms consumer, so the executor self-persists.
        """
        return self.kind is RunKind.QUEUED or self.workflow_id is not None


# ── Session registry ─────────────────────────────────────────────────

_sessions: dict[str, StreamSession] = {}


def create_session(stream_id: str, kind: RunKind) -> StreamSession:
    """Create (or replace) the session for a stream.

    A new session is a new run: whatever a previous waiter gave up on under
    this id is forgotten.
    """
    session = StreamSession(stream_id=stream_id, kind=kind)
    _sessions[stream_id] = session
    if stream_id in _abandoned:
        _abandoned.remove(stream_id)
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

#: Streams whose waiter gave up on the executor, oldest first. Bounded because
#: nothing else ever forgets a stream id; a finalize for one of these skips
#: delivery instead of answering a run that was already closed as failed.
_ABANDONED_REMEMBERED = 1024
_abandoned: deque[str] = deque(maxlen=_ABANDONED_REMEMBERED)


def mark_executor_spawned(stream_id: str) -> None:
    """Record that call_executor spawned a background task for this stream."""
    session = get_or_create_session(stream_id)
    session.executor_spawned = True
    session.executor_first_frame_perf = None  # new incarnation, new first frame


def signal_executor_done(
    stream_id: str, *, failed: bool = False, reason: str | None = None
) -> None:
    """Wake any waiter blocked on the executor finishing for this stream."""
    session = _sessions.get(stream_id)
    if session is not None:
        session.executor_failed = failed
        session.executor_failure = reason if failed else None
        session.done_event.set()


def mark_executor_failed(stream_id: str, reason: str) -> None:
    """Record that the executor failed without finishing (the waiter gave up).

    The stream is also marked abandoned, outside the session: the waiter tears
    the session down right after, and the executor's own finalize, whenever it
    comes, has to find out that nobody is listening any more.
    """
    session = _sessions.get(stream_id)
    if session is not None:
        session.executor_failed = True
        session.executor_failure = reason
    _abandoned.append(stream_id)


def executor_abandoned(stream_id: str) -> bool:
    """Whether the run that waited on this executor gave up on it."""
    return stream_id in _abandoned


def executor_failed(stream_id: str) -> bool:
    """Whether the executor this stream spawned ended in an error."""
    session = _sessions.get(stream_id)
    return bool(session and session.executor_failed)


def executor_failure(stream_id: str) -> str | None:
    """Why the executor failed, when it did."""
    session = _sessions.get(stream_id)
    return session.executor_failure if session is not None else None


def note_tool_output_owner(stream_id: str, tool_call_id: str, subagent_id: str | None) -> None:
    """Record which run announced this call, so only it may stream the result."""
    session = _sessions.get(stream_id)
    if session is None or not tool_call_id:
        return
    session.tool_output_owners.setdefault(tool_call_id, subagent_id)


def claim_tool_output(stream_id: str, tool_call_id: str, subagent_id: str | None = None) -> bool:
    """Claim the right to stream this tool result, once per stream.

    Returns True for the owning caller and False for every echo. Fails open
    when the stream has no session. A run that did not announce the call is
    always the echo, regardless of arrival order.
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
