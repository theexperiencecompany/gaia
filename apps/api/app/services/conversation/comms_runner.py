"""The comms runner: the one owner of the comms graph, driving one attempt of the conversation step at a time.

A run streams the graph in its own task, in lockstep with the step: after each
event it waits until the step asks for the next one, so an entry absorbed on a
ModelOutput reaches the very next model call through the drain hook.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast
from uuid import uuid4

from langchain_core.messages import AnyMessage
from langgraph.constants import CONF
from langgraph.types import StreamMode

from app.agents.core.graph_manager import CompiledAgentGraph, GraphManager
from app.agents.core.interruption import record_interruption
from app.agents.core.messages import MessageAttachments, MessageScope, human_content
from app.agents.core.nodes.drain_conversation_log import close_feed, feed, open_feed
from app.constants.conversation import (
    COMMS_CANCEL_CONFIRM_SECONDS,
    TURN_CONTEXT_ID_SUFFIX,
    WORKFLOW_RUN_REQUEST,
)
from app.constants.graphs import GraphName
from app.models.agent_models import AgentConfigurable, AgentRunnableConfig, agent_configurable
from app.models.conversation_log_models import (
    Batch,
    LoggedEntry,
    StepClaim,
    UserMessage,
    WorkflowFired,
)
from app.services.conversation.comms_events import CommsEventMapper, GraphEvent
from app.services.conversation.comms_input import (
    absorbed_messages,
    attempt_messages,
    entry_message_id,
)
from app.services.conversation.ports import CancelReason, Finished, RunEvent

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


CommsTurnBuilder = Callable[[StepClaim, Batch], Awaitable[CommsTurn]]


class CommsGraphRun:
    """One attempt on the comms graph: its events, the inputs absorbed into it, and its cancellation."""

    def __init__(
        self,
        claim: StepClaim,
        graph: CompiledAgentGraph,
        config: AgentRunnableConfig,
        state: dict[str, object],
        cancel_confirm_seconds: float,
    ) -> None:
        self._claim = claim
        self._graph = graph
        self._config = config
        configurable: AgentConfigurable = agent_configurable(config)
        self._run_id = configurable["comms_run"]
        self._mapper = CommsEventMapper(claim.user_id)
        self._confirm = cancel_confirm_seconds
        self._out: asyncio.Queue[RunEvent | Exception] = asyncio.Queue()
        self._wanted: asyncio.Queue[None] = asyncio.Queue()
        self._sealed = False
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
        messages, stopped = absorbed_messages(entries, said)
        feed(self._run_id, messages)
        self._sealed = stopped

    async def cancel(self, reason: CancelReason) -> None:
        """Cancel until the task is done, then record a Stop in the thread; any other reason leaves no trace."""
        self._sealed = True
        while not self.task.done():
            self.task.cancel()
            await asyncio.wait((self.task,), timeout=self._confirm)
        if reason is CancelReason.STOP:
            await record_interruption(self._graph, self._config)

    async def _drive(self, state: dict[str, object]) -> None:
        try:
            await self._stream(state)
            *tail, finished = self._mapper.finish()
            for event in tail:
                await self._emit(event)
            self._out.put_nowait(finished)
        except Exception as error:  # the step settles a crashed run as failed
            self._out.put_nowait(error)
        finally:
            close_feed(self._run_id)

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
    ) -> None:
        self._build_turn = build_turn
        self._confirm = cancel_confirm_seconds

    async def start(
        self, claim: StepClaim, batch: Batch, context: Sequence[LoggedEntry]
    ) -> CommsGraphRun:
        """Start an attempt on batch with context as notes; a re-sent batch upserts its own messages."""
        graph = await GraphManager.get_graph(GraphName.COMMS)
        turn = await self._build_turn(claim, batch)
        configurable: AgentConfigurable = {
            **agent_configurable(turn.config),
            "thread_id": claim.conversation_id,
            "comms_run": uuid4().hex,
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
        ]
        return CommsGraphRun(
            claim, graph, config, {**turn.state, "messages": messages}, self._confirm
        )


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
    return {entry.id: content for entry, content in zip(reframed, contents, strict=True)}


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
