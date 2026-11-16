"""The comms runner: the one owner of the comms graph, driving one attempt of the conversation step at a time.

A run streams the graph in its own task, in lockstep with the step: after each
event it waits until the step asks for the next one, so an entry absorbed on a
ModelOutput reaches the very next model call through the drain hook.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import TypedDict, cast

from langchain_core.messages import AnyMessage, HumanMessage, ToolCall
from langgraph.constants import CONF
from langgraph.errors import GraphRecursionError
from langgraph.types import StreamMode

from app.agents.core.comms_ledger import still_open
from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.interruption import record_interruption
from app.agents.core.messages import MessageAttachments, MessageScope, human_content
from app.agents.core.nodes.drain_conversation_log import close_feed, feed, open_feed
from app.agents.middleware.runtime_adapter import GaiaAgentState
from app.agents.middleware.summarization import WorkspaceArchivingSummarizationMiddleware
from app.agents.tools.executor_tool import call_executor
from app.constants.agents import TimeHorizon
from app.constants.conversation import (
    COMMS_CANCEL_CONFIRM_SECONDS,
    FALLBACK_HANDOFF_DONE,
    FALLBACK_HANDOFF_OUTCOME,
    FALLBACK_HANDOFF_TASK,
    STILL_OPEN_LINE,
    STILL_OPEN_NOTE_SUFFIX,
    TURN_CONTEXT_ID_SUFFIX,
    WORKFLOW_RUN_REQUEST,
)
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.graphs import GraphName
from app.models.agent_config import StepTurnRef
from app.models.agent_models import AgentConfigurable, AgentRunnableConfig, agent_configurable
from app.models.conversation_log_models import (
    Batch,
    IntegrationConnected,
    LoggedEntry,
    StepClaim,
    UserMessage,
    WorkflowFired,
)
from app.services.analytics_service import agent_run_lifecycle
from app.services.conversation.comms_events import CommsEventMapper, GraphEvent
from app.services.conversation.comms_input import (
    absorbed_messages,
    attempt_messages,
    entry_message_id,
    verbatim_message_ids,
)
from app.services.conversation.ports import (
    NOTHING_KEPT,
    CancelReason,
    Finished,
    FoldPlan,
    Kept,
    RunEvent,
    StepLimitReached,
)
from shared.py.analytics.catalog.agents import AgentRunStarted
from shared.py.analytics.context import AnalyticsContext, analytics_context

_STREAM_MODES: list[StreamMode] = ["messages", "custom", "updates"]


class _ThreadValues(TypedDict, total=False):
    """The checkpoint values a run reads back; only the messages channel matters."""

    messages: list[AnyMessage]


@dataclass(frozen=True)
class CommsTurn:
    """What an attempt carries beyond its log entries: the run config and the turn context around them."""

    config: AgentRunnableConfig
    # The system prompt and context slots, ahead of the inputs.
    opening: Sequence[AnyMessage]
    # The clock, after the inputs.
    closing: Sequence[AnyMessage]
    # Graph state keys beside messages (intent, integration_usernames, ...).
    state: dict[str, object]
    # Who caused the inputs; the run and everything it dispatches are attributed to them.
    analytics: AnalyticsContext
    run_started: AgentRunStarted
    # False for a run that continues its attempt: the attempt is one agent run, counted once.
    counted: bool = True


CommsTurnBuilder = Callable[[StepClaim, Batch], Awaitable[CommsTurn]]


class CommsGraphRun:
    """One attempt on the comms graph: its events, the inputs absorbed into it, and its cancellation."""

    def __init__(
        self,
        claim: StepClaim,
        graph: CompiledAgentGraph,
        config: AgentRunnableConfig,
        turn: CommsTurn,
        state: dict[str, object],
        cancel_confirm_seconds: float,
    ) -> None:
        self._claim = claim
        self._graph = graph
        self._config = config
        self._turn = turn
        configurable: AgentConfigurable = agent_configurable(config)
        self._run_id = configurable["comms_run"]
        self._mapper = CommsEventMapper(claim.user_id, config)
        self._confirm = cancel_confirm_seconds
        self._out: asyncio.Queue[RunEvent | Exception] = asyncio.Queue()
        self._wanted: asyncio.Queue[None] = asyncio.Queue()
        self._sealed = False  # pragma: no mutate — only read as `if self._sealed`
        open_feed(self._run_id)
        self.task = asyncio.create_task(self._drive(state))

    async def events(self) -> AsyncIterator[RunEvent]:
        """Yield the run's events; Finished, or the run's error, only once its task has exited."""
        while True:
            item = await self._out.get()
            if isinstance(item, Finished | Exception):
                await asyncio.wait((self.task,))
                if isinstance(item, Exception):
                    raise item
                yield item
                return
            yield item
            self._wanted.put_nowait(None)

    async def absorb(self, entries: Sequence[LoggedEntry]) -> None:
        """Feed entries to the next model call, never past a Stop; nothing joins once the run is stopping."""
        if self._sealed or self.task.done():
            return
        said = await reframed_messages(self._claim, entries)
        messages, joined = absorbed_messages(entries, said)
        feed(self._run_id, messages)
        configurable: AgentConfigurable = agent_configurable(self._config)
        if (step := configurable.get("conversation_step")) is not None:
            _join(step, joined)
        self._sealed = len(joined) < len(entries)

    async def hand_off(self, claim: StepClaim, messages: Sequence[LoggedEntry]) -> bool:
        """Hand messages the finished run never closed to the executor through call_executor itself."""
        seqs = [logged.seq for logged in messages]
        said = [
            STILL_OPEN_LINE.format(seq=logged.seq, text=logged.entry.text)
            for logged in messages
            if isinstance(logged.entry, UserMessage)
        ]
        call: ToolCall = {
            "name": CALL_EXECUTOR_NAME,
            "args": {
                "task": FALLBACK_HANDOFF_TASK.format(messages="\n".join(said)),
                "for_messages": seqs,
                "acceptance_criteria": [FALLBACK_HANDOFF_DONE.format(seq=seq) for seq in seqs],
                "desired_outcome": FALLBACK_HANDOFF_OUTCOME,
                "time_horizon": TimeHorizon.ONE_SHOT,
            },
            "id": f"fallback:{claim.conversation_id}:{seqs[0]}",
            "type": "tool_call",
        }
        await call_executor.ainvoke(call, config=self._config)
        return not set(seqs) & set(still_open(self._run_id))

    async def cancel(self, reason: CancelReason) -> None:
        """Cancel until the task is done, then record a Stop in the thread; any other reason leaves no trace."""
        self._sealed = True
        while not self.task.done():
            self.task.cancel()
            await asyncio.wait((self.task,), timeout=self._confirm)
        if reason is CancelReason.STOP:
            await record_interruption(self._graph, self._config)

    async def _drive(self, state: dict[str, object]) -> None:
        """Run the attempt; any failure, the lifecycle's own included, reaches events() so the step settles it."""
        try:
            await self._drive_counted(state)
        except GraphRecursionError as error:
            self._out.put_nowait(StepLimitReached(str(error)))
        except Exception as error:  # the step settles a crashed run as failed
            self._out.put_nowait(error)
        finally:
            close_feed(self._run_id)

    async def _drive_counted(self, state: dict[str, object]) -> None:
        turn = self._turn
        # A run that continues its attempt is the same agent run, so it is counted once.
        with (
            analytics_context(turn.analytics),
            agent_run_lifecycle(self._claim.user_id if turn.counted else None, turn.run_started),
        ):
            await self._stream(state)
            *tail, finished = self._mapper.finish()
            for event in tail:
                await self._emit(event)
            self._out.put_nowait(finished)

    async def _stream(self, state: dict[str, object]) -> None:
        # With subgraphs=True every event is a (namespace, mode, payload) triple, and astream is a
        # real async generator, so it supports aclose(); langgraph's overloads express neither.
        stream = cast(
            AsyncGenerator[GraphEvent, None],
            self._graph.astream(
                state, stream_mode=_STREAM_MODES, config=self._config, subgraphs=True
            ),
        )
        try:
            async for raw in stream:
                for event in await self._mapper.map(raw):
                    await self._emit(event)
        finally:
            await stream.aclose()

    async def _emit(self, event: RunEvent) -> None:
        """Hand the step one event and hold the graph until the step asks for the next."""
        self._out.put_nowait(event)
        await self._wanted.get()


class CommsGraphRunner:
    """Starts comms attempts on the conversation's thread, whose id is the conversation id."""

    def __init__(
        self,
        build_turn: CommsTurnBuilder,
        cancel_confirm_seconds: float = COMMS_CANCEL_CONFIRM_SECONDS,
        *,
        history_fold: WorkspaceArchivingSummarizationMiddleware,
    ) -> None:
        self._build_turn = build_turn
        self._confirm = cancel_confirm_seconds
        self._fold = history_fold

    async def start(
        self,
        claim: StepClaim,
        batch: Batch,
        context: Sequence[LoggedEntry],
        ledger: str,
        note: str | None = None,
        *,
        kept: Kept = NOTHING_KEPT,
    ) -> CommsGraphRun:
        """Start an attempt on batch with context as notes, its closing tools writing ledger; a re-sent batch upserts its own messages."""
        graph = await GraphManager.get_graph(GraphName.COMMS)
        turn = replace(await self._build_turn(claim, batch), counted=note is None)
        configurable: AgentConfigurable = {
            **agent_configurable(turn.config),
            "thread_id": claim.conversation_id,
            "comms_run": ledger,
        }
        config = cast(AgentRunnableConfig, {**turn.config, CONF: configurable})
        snapshot = await graph.aget_state(config)
        values: _ThreadValues = cast(_ThreadValues, snapshot.values or {})
        thread = values.get("messages", [])
        said = await reframed_messages(claim, [*context, *batch.waking])
        messages = [
            *_turn_context(turn.opening, batch, 0),
            *attempt_messages(batch, context, thread, said),
            *_turn_context(turn.closing, batch, len(turn.opening)),
            *([] if note is None else [_still_open_message(batch, note)]),
        ]
        # Inputs still owed an answer, and what the user pinned, outlive summarization word for word.
        inputs = kept.owed | set(_answered(batch.waking))
        verbatim = verbatim_message_ids(thread, inputs, kept.pinned)
        state = {**turn.state, "messages": messages, "verbatim_message_ids": verbatim}
        return CommsGraphRun(claim, graph, config, turn, state, self._confirm)

    async def plan_fold(self, conversation_id: str, user_id: str, kept: Kept) -> FoldPlan | None:
        """Summarize the thread's oldest turns past its budget, writing nothing; None under it."""
        graph = await GraphManager.get_graph(GraphName.COMMS)
        config = _thread_config(conversation_id, user_id)
        thread = await _thread(graph, config)
        state = GaiaAgentState(
            messages=thread,
            verbatim_message_ids=verbatim_message_ids(thread, kept.owed, kept.pinned),
        )
        fold = await self._fold.afold(state, config)
        if fold is None:
            return None
        return FoldPlan(tuple(m.id for m in thread), tuple(fold))

    async def apply_fold(self, claim: StepClaim, plan: FoldPlan) -> bool:
        """Write the planned fold under the step's claim; False when a turn wrote the thread since."""
        graph = await GraphManager.get_graph(GraphName.COMMS)
        config = _thread_config(claim.conversation_id, claim.user_id)
        if tuple(m.id for m in await _thread(graph, config)) != plan.thread:
            return False
        # as_node="tools" as record_interruption writes: the next turn's input starts a fresh run.
        await graph.aupdate_state(config, {"messages": list(plan.messages)}, as_node="tools")
        return True


def _thread_config(conversation_id: str, user_id: str) -> AgentRunnableConfig:
    configurable: AgentConfigurable = {"thread_id": conversation_id, "user_id": user_id}
    return cast(AgentRunnableConfig, {CONF: configurable})


async def _thread(graph: CompiledAgentGraph, config: AgentRunnableConfig) -> list[AnyMessage]:
    snapshot = await graph.aget_state(config)
    values: _ThreadValues = cast(_ThreadValues, snapshot.values or {})
    return values.get("messages", [])


def _still_open_message(batch: Batch, note: str) -> HumanMessage:
    anchor = entry_message_id(batch.waking[0].entry.id)
    return HumanMessage(content=note, id=f"{anchor}{STILL_OPEN_NOTE_SUFFIX}")


def step_turn_ref(claim: StepClaim, batch: Batch) -> StepTurnRef:
    """Return what the attempt's run and the work it dispatches carry of the attempt."""
    return {
        "epoch": claim.epoch,
        "batch_start": batch.start,
        "cause_through": batch.end,
        "answers": _answered(batch.waking),
        "asked": _asks(batch.waking),
    }


def _join(step: StepTurnRef, joined: Sequence[LoggedEntry]) -> None:
    """Extend the run's own step ref in place, so work its tools dispatch from now on answers the joiners too."""
    if joined:
        step["cause_through"] = joined[-1].seq
        step["answers"] = [*step["answers"], *_answered(joined)]
        step["asked"] = step["asked"] or _asks(joined)


def _asks(entries: Sequence[LoggedEntry]) -> bool:
    return any(
        isinstance(logged.entry, UserMessage | WorkflowFired | IntegrationConnected)
        for logged in entries
    )


def _answered(entries: Sequence[LoggedEntry]) -> list[str]:
    return [
        logged.entry.id
        for logged in entries
        if isinstance(logged.entry, UserMessage | WorkflowFired)
    ]


async def reframed_messages(claim: StepClaim, entries: Sequence[LoggedEntry]) -> dict[str, str]:
    """Return, per user message that carries more than text, what the model reads, built as a chat turn builds it.

    Its files are listed, and a pinned tool, a workflow, a calendar event or a replied-to message reframe its text;
    a workflow fire reads as its workflow's run request with its steps and trigger.
    """
    reframed = [
        logged.entry
        for logged in entries
        if isinstance(logged.entry, WorkflowFired)
        or (isinstance(logged.entry, UserMessage) and _reframes(logged.entry))
    ]
    scope = MessageScope(user_id=claim.user_id, conversation_id=claim.conversation_id)
    contents = await asyncio.gather(*(human_content(scope, *_framing(entry)) for entry in reframed))
    pairs = zip(reframed, contents, strict=True)  # pragma: no mutate — one result per input
    return {entry.id: content for entry, content in pairs}


def _framing(entry: UserMessage | WorkflowFired) -> tuple[MessageAttachments, str]:
    """Return what reframes an input and the words it reframes; a workflow fire asks to run its workflow."""
    if isinstance(entry, UserMessage):
        return _attachments(entry), entry.text
    run = entry.run
    attachments = MessageAttachments(
        selected_workflow=run.workflow, trigger_context=run.trigger.model_dump()
    )
    return attachments, WORKFLOW_RUN_REQUEST.format(title=run.workflow.title)


def _reframes(message: UserMessage) -> bool:
    return bool(
        message.file_ids
        or message.selected_tool
        or message.selected_workflow
        or message.selected_calendar_event
        or message.reply_to_message
    )


def _attachments(message: UserMessage) -> MessageAttachments:
    return MessageAttachments(
        selected_tool=message.selected_tool,
        tool_category=message.tool_category,
        selected_workflow=message.selected_workflow,
        selected_calendar_event=message.selected_calendar_event,
        reply_to_message=message.reply_to_message,
        currently_uploaded_file_ids=list(message.file_ids),
    )


def _turn_context(messages: Sequence[AnyMessage], batch: Batch, first: int) -> list[AnyMessage]:
    """Give the turn context ids keyed on the batch's oldest input, so a restart replaces it in place."""
    anchor = entry_message_id(batch.waking[0].entry.id)
    return [
        message.model_copy(update={"id": f"{anchor}{TURN_CONTEXT_ID_SUFFIX}:{first + index}"})
        for index, message in enumerate(messages)
    ]
