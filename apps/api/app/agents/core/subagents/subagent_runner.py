"""Shared logic for subagent invocation, used by delegation.py and executor_tool.py."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
import time
from typing import Any, TypedDict, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot

from app.agents.context.assemble import assemble_context
from app.agents.context.presence_note import presence_note_message
from app.agents.context.section_context import SectionContext, SectionScope
from app.agents.context.tiers import AgentTier
from app.agents.core.background.session import claim_tool_output, note_tool_output_owner
from app.agents.core.background.subagent_channel import SubagentCancel
from app.agents.core.graph_manager import (
    CompiledAgentGraph,
    GraphManager,
    GraphUnavailableError,
)
from app.agents.core.held_replies import HeldReplies
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.llm.lane import AgentRole, dev_option
from app.agents.llm.reasoning import extract_reasoning_delta
from app.agents.prompts.delegation_prompts import SUBAGENT_NARRATION_ONLY_RESULT
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_AUTO_NOTIFY_SECTION,
    WORKFLOW_SILENT_NOTIFY_SECTION,
)
from app.constants.agents import (
    DONE_EVIDENCE_RULE,
    IRREVERSIBLE_APPROVED_BRIEF,
    IRREVERSIBLE_UNAPPROVED_BRIEF,
    NO_ANSWER_NOTICE,
    TIME_HORIZON_BRIEF,
    AgentTag,
    wrap_agent_payload,
)
from app.constants.general import (
    EXECUTOR_INTEGRATION_ID,
    EXECUTOR_THREAD_PREFIX,
    FINISH_TASK_NAME,
)
from app.constants.graphs import GraphName
from app.constants.llm import BUDGET_STOP_METADATA_KEY, EXECUTOR_RECURSION_LIMIT
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import AgentIdentity, AgentLane, AgentThread, build_agent_config
from app.helpers.message_helpers import (
    build_current_time_message,
    create_system_message,
    format_files_list,
)
from app.models.agent_config import AgentConfigurableView
from app.models.agent_models import (
    AgentConfigurable,
    AgentRunnableConfig,
    AgentUserContext,
    StreamChunkMetadata,
    agent_configurable,
    run_analytics_context,
)
from app.models.ownership_models import ExecutorIntent
from app.models.stream_events import ReasoningPayload, ToolOutputPayload
from app.services.chat.chunks import normalize_custom_event
from app.services.files import FileService
from app.services.latency_metrics import observe_subagent_run
from app.utils.agent_utils import IntegrationMetadata, StreamWriterCallable
from app.utils.multimodal import extract_text_content
from app.utils.stream_utils import extract_tool_entries_from_update
from shared.py.wide_events import log


def _finish_task_result(chunk: ToolMessage) -> str | None:
    """Return the finish_task chunk's textual content, or None for any other tool result.

    finish_task carries the final answer in its return value, so the parent handoff
    returns it. Subagents with include_finish_task=False never enter this branch.
    """
    if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
        return chunk.content
    return None


class _MessagesChannel(TypedDict, total=False):
    """The messages channel of a State update or snapshot; its other channels ride along unread."""

    messages: list[AnyMessage]


class SubagentInitialState(TypedDict, total=False):
    """The State channels a subagent run is seeded with; the graph fills in the rest."""

    messages: list[AnyMessage]
    todos: list[object]
    intent: str | None
    integration_usernames: dict[str, str]
    selected_tool_ids: list[str]


@dataclass(frozen=True)
class SubagentOutcome:
    """One graph run's result: its text, or that the user stopped it.

    run_messages are THIS run's tool-bearing messages captured off the
    stream — the agent node's AIMessages (complete tool_calls) and the
    ToolMessages answering them. Workflow handoffs render them into the call
    record the executor transcribes playbook steps from (see call_record).
    """

    text: str
    run_messages: tuple[AnyMessage, ...] = ()
    stopped: bool = False
    #: False when the run ended without an answer; text then says nothing confirms the work.
    answered: bool = True


def subagent_row_id(tool_call_id: str) -> str:
    """Derive a UI subagent-row id that stays STABLE across replays of the same call.

    From tool_call_id (unique per generation, stable in the checkpoint), so a
    paused-and-resumed subagent reuses its row instead of orphaning it and
    emitting a duplicate. A blank id (defensive only) falls back to a fresh uuid.
    """
    if not tool_call_id:
        return str(uuid4())
    return str(uuid5(NAMESPACE_URL, f"subagent_row:{tool_call_id}"))


# eq/repr stay off: instances are compared and printed by identity (a generated
# repr would dump the whole message history in `initial_state`), and __hash__ must
# survive for anything holding a context in a set.
@dataclass(eq=False, repr=False)
class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    subagent_graph: CompiledAgentGraph
    agent_name: str
    config: AgentRunnableConfig
    configurable: AgentConfigurable
    integration_id: str
    initial_state: SubagentInitialState
    user_id: str | None = None
    stream_id: str | None = None
    #: The stream of the turn that dispatched a background run onto its own
    #: stream: a Stop on that turn stops the run too.
    parent_stream_id: str | None = None


@dataclass(frozen=True)
class ThreadSeed:
    """What a worker tier's opening thread is seeded from.

    The tier, the run's configurable, and the identifiers context sections retrieve against.
    """

    tier: AgentTier
    configurable: AgentConfigurable
    user_id: str | None = None
    subagent_id: str | None = None
    retrieval_query: str | None = None
    #: The comms turn's request this thread serves; see SectionContext.request_query.
    request_query: str | None = None


async def build_initial_messages(
    *,
    system_message: SystemMessage,
    agent_name: str,
    task: str,
    seed: ThreadSeed,
) -> list[AnyMessage]:
    """Seed a worker tier's thread: static prompt, context, the task, then the clock.

    system_message must be STATIC (no per-user/per-time content) so the cache
    prefix stays shared across users. seed.retrieval_query defaults to task, but
    callers pass the unenhanced task when task carries hints that would pollute search.
    """
    configurable: AgentConfigurable = seed.configurable
    tier, user_id, subagent_id, retrieval_query = (
        seed.tier,
        seed.user_id,
        seed.subagent_id,
        seed.retrieval_query,
    )

    log.set(agent_prep={"agent_name": agent_name, "task_length": len(task)})

    section_context = SectionContext.from_configurable(
        tier,
        configurable,
        SectionScope(
            query=retrieval_query if retrieval_query is not None else task,
            request_query=seed.request_query,
            user_id=user_id,
            subagent_id=subagent_id,
        ),
    )
    assembled, note = await asyncio.gather(
        assemble_context(section_context),
        _executor_presence_note(section_context, configurable),
    )

    # Current time rides in a HumanMessage so the system_instruction prefix
    # stays stable — minute ticks would otherwise reset the cache boundary
    # at whatever byte position the timestamp occupies.
    time_message = build_current_time_message(
        user_timezone=configurable.get("user_timezone"),
    )

    return [
        system_message,
        *assembled.messages(),
        *([note] if note is not None else []),
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
        time_message,
    ]


async def _executor_presence_note(
    ctx: SectionContext, configurable: AgentConfigurable
) -> HumanMessage | None:
    """Return the executor's surface-change note; every other worker tier gets none."""
    if ctx.tier is not AgentTier.EXECUTOR:
        return None
    return await presence_note_message(
        ctx.user_id,
        configurable.get("presence"),
        ctx.source,
        ctx.execution_mode,
        # Comms voices the result and gets the first-turn note itself.
        opens_thread=False,
        entry_surface=run_analytics_context(configurable).attribution.surface,
    )


@dataclass
class _StreamRun:
    """One drive of execute_subagent_stream: its emitters and its running state.

    Mutable and passed by reference to the per-stream-mode handlers, so the loop
    keeps a single copy of the state every branch accumulates into.
    """

    ctx: SubagentExecutionContext
    stream_writer: StreamWriterCallable | None
    integration_metadata: IntegrationMetadata | None
    subagent_id: str | None
    #: The finish_task return value, which is the answer over anything the run said.
    finish_result: str | None = None
    #: The budget wall's stop text: it answers in place of a model, so no token streams it.
    budget_stop: str | None = None
    held: HeldReplies = field(default_factory=HeldReplies)
    emitted_tool_calls: set[str] = field(default_factory=set)
    tool_ran: bool = False
    run_messages: list[AnyMessage] = field(default_factory=list)
    #: The run's own thread, which build_agent_config stamps on every chunk its model streams.
    thread_id: str | None = field(init=False)

    def __post_init__(self) -> None:
        self.thread_id = AgentConfigurableView.model_validate(self.ctx.configurable).thread_id

    @property
    def complete_message(self) -> str:
        """What the run answered: finish_task's result, the budget stop, else the replies that called no tool."""
        if self.finish_result is not None:
            return self.finish_result
        if self.budget_stop is not None:
            return self.budget_stop
        return self.held.reply_text()


def _process_messages_payload(
    run: _StreamRun,
    # "messages"-mode payloads are always (message chunk, metadata); the driver
    # holds them as `object` only because the shape varies per stream mode.
    payload: tuple[BaseMessage, StreamChunkMetadata],
) -> None:
    """Handle one "messages"-mode stream event.

    Emits tool_output for ToolMessages, gated by claim_tool_output: a nested
    subagent's chunks carry the SAME run metadata as ours, so ungated it would
    double-render the result — the claim goes to whichever run announced the call.
    """
    metadata: StreamChunkMetadata
    chunk, metadata = payload
    if metadata.get("silent"):
        return

    # A spawned subagent's chunks share this stream: its reply and finish_task are its own.
    nested = metadata.get("agent_thread_id", run.thread_id) != run.thread_id

    if chunk and isinstance(chunk, AIMessageChunk):
        if not nested:
            run.held.hold(chunk, metadata)

        # Stream reasoning token by token, carrying subagent_id for step nesting
        # (empty for non-reasoning models). Deltas are per chunk; the stream
        # writer coalesces them for the persistence collector, never for publish.
        if run.stream_writer:
            reasoning_delta = extract_reasoning_delta(chunk)
            if reasoning_delta:
                reasoning_payload = ReasoningPayload(
                    content=reasoning_delta, subagent_id=run.subagent_id
                )
                run.stream_writer({"reasoning": reasoning_payload.model_dump(exclude_none=True)})

    # Emit tool_output when ToolMessage arrives. Text-extract block content so
    # inline media (base64 image blocks) never streams to the frontend.
    elif chunk and isinstance(chunk, ToolMessage):
        content_str = extract_text_content(chunk.content)
        if not nested and (finish_result := _finish_task_result(chunk)) is not None:
            run.finish_result = finish_result
        if run.stream_writer and claim_tool_output(
            run.ctx.stream_id or "", chunk.tool_call_id, run.subagent_id
        ):
            tool_output_payload = ToolOutputPayload(
                tool_call_id=chunk.tool_call_id,
                output=content_str,
                subagent_id=run.subagent_id,
            )
            run.stream_writer({"tool_output": tool_output_payload.model_dump(exclude_none=True)})


def _note_budget_stop(run: _StreamRun, messages: Sequence[AnyMessage]) -> None:
    """Keep the budget wall's stop text: it answers in place of a model, so no token streams it."""
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.response_metadata.get(BUDGET_STOP_METADATA_KEY):
            run.budget_stop = extract_text_content(msg.content)


async def _process_updates_payload(run: _StreamRun, payload: dict[str, object]) -> None:
    """Handle one "updates"-mode stream event: emit tool_data for the agent node's calls."""
    for node_name, state_update in payload.items():
        # Only emit tool_data from the LLM ("agent") node — pre-model hooks
        # produce "updates" events with historical AIMessages from previous
        # checkpoint runs, and emitting those would replay stale tool cards.
        if node_name != "agent":
            continue
        # The agent node's update is the one place this run's complete
        # tool_calls (exact names + args) appear — "messages" mode only
        # streams them as partial chunks. Captured for the call record.
        if isinstance(state_update, dict):
            agent_update: _MessagesChannel = cast(_MessagesChannel, state_update)
            _note_budget_stop(run, agent_update.get("messages", []))
            announcing = [
                msg for msg in agent_update.get("messages", []) if getattr(msg, "tool_calls", None)
            ]
            run.run_messages.extend(announcing)
            for msg in announcing:
                if isinstance(msg, AIMessage):
                    run.held.mark_announced(msg)
        # Use shared helper to extract and format tool entries
        entries = await extract_tool_entries_from_update(
            state_update=state_update,
            emitted_tool_calls=run.emitted_tool_calls,
            integration_metadata=run.integration_metadata,
            user_id=run.ctx.user_id,
        )
        for tc_id, tool_entry in entries:
            # Announcing the call is what claims its result: "messages" mode
            # will replay this ToolMessage into the outer run's stream too.
            note_tool_output_owner(run.ctx.stream_id or "", tc_id, run.subagent_id)
            if run.stream_writer:
                chunk_data: dict[str, Any] = {"tool_data": tool_entry}
                if run.subagent_id:
                    chunk_data["tool_data"] = {**tool_entry, "subagent_id": run.subagent_id}
                run.stream_writer(chunk_data)


def _finalize_run(run: _StreamRun) -> SubagentOutcome:
    """Return the outcome a drained stream produced."""
    if not run.complete_message:
        log.warning("subagent_ended_without_answer", subagent_name=run.ctx.agent_name)
        return SubagentOutcome(
            text=NO_ANSWER_NOTICE.format(name=f"The {run.ctx.agent_name} run"),
            run_messages=tuple(run.run_messages),
            answered=False,
        )

    # A worker that only narrated did no work: say so, so its delegator re-issues it.
    # The executor is nobody's delegate; its words are its answer (collection runs report).
    if (
        run.ctx.integration_id != EXECUTOR_INTEGRATION_ID
        and run.budget_stop is None
        and not run.tool_ran
        and not run.emitted_tool_calls
    ):
        log.warning("subagent_returned_narration_only", subagent_name=run.ctx.agent_name)
        final_message = SUBAGENT_NARRATION_ONLY_RESULT.format(
            name=run.ctx.agent_name, text=run.complete_message
        )
    else:
        final_message = run.complete_message
    initial_state: SubagentInitialState = run.ctx.initial_state
    log.set(
        subagent={
            "name": run.ctx.agent_name,
            "provider": run.ctx.integration_id,
            "response_length": len(final_message),
            "messages_count": len(initial_state.get("messages", [])),
        }
    )
    return SubagentOutcome(text=final_message, run_messages=tuple(run.run_messages))


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer: StreamWriterCallable | None = None,
    integration_metadata: IntegrationMetadata | None = None,
    subagent_id: str | None = None,
) -> SubagentOutcome:
    """Execute a subagent with streaming and tool tracking.

    Stream events: "updates" emits tool_data on a tool call, "messages" streams
    content and emits tool_output on a ToolMessage, "custom" forwards progress
    events to the parent.
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    run = _StreamRun(
        ctx=ctx,
        stream_writer=stream_writer,
        integration_metadata=integration_metadata,
        subagent_id=subagent_id,
    )

    # Inject the UUID subagent_id into configurable so nested spawn_subagent
    # tool calls can read the correct parent_subagent_id via
    # configurable.get("subagent_id").
    run_config = ctx.config
    if subagent_id:
        base_configurable = agent_configurable(ctx.config)
        run_config = {
            **ctx.config,
            "configurable": {**base_configurable, "subagent_id": subagent_id},
        }

    # The executor addresses a cancel to this subagent by its own thread_id.
    run_configurable: AgentConfigurable = agent_configurable(ctx.config)
    subagent_thread_id = run_configurable.get("thread_id")
    cancel = SubagentCancel(subagent_thread_id) if subagent_thread_id else None

    # Labelled by integration id: per-call
    # uuids and user-made MCPs would each mint unbounded series.
    label = (
        "custom_mcp"
        if ctx.agent_name.startswith("custom_mcp_")
        else ctx.integration_id or ctx.agent_name or "unknown"
    )
    cancelled = False
    segment_start = time.perf_counter()
    try:
        async for event in ctx.subagent_graph.astream(
            ctx.initial_state,
            stream_mode=["messages", "custom", "updates"],
            # build_agent_config returns an AgentRunnableConfig, but run_config may be
            # rebuilt above as a dict spread, which mypy widens back to a plain dict.
            config=cast(RunnableConfig, run_config),
            # Persist checkpoints only on run exit (this path is one unit of work),
            # collapsing O(steps) writes to one. The comms graph driver keeps
            # "async" — its mid-run checkpoints are needed.
            durability="exit",
        ):
            if await _stream_cancelled(ctx):
                log.info(
                    f"{LogTag.AGENT} Subagent stream cancelled by user", stream_id=ctx.stream_id
                )
                cancelled = True
                break

            # Handle 2-tuple format only (no subgraphs)
            if len(event) != 2:
                continue
            # A list `stream_mode` makes astream yield (mode, payload) tuples, which
            # langgraph's own overload return type does not express.
            stream_mode, payload = cast(tuple[str, object], event)

            # Targeted cancel from the executor, checked once per superstep (one
            # redis read per reasoning step). Returns a clean cancelled result so
            # the executor learns it stopped; the executor and siblings keep running.
            if (
                stream_mode == "updates"
                and ctx.stream_id
                and cancel
                and await cancel.is_requested()
            ):
                await cancel.clear()
                log.info(f"{LogTag.AGENT} Subagent cancelled by executor", stream_id=ctx.stream_id)
                outcome = _finalize_run(run)
                observe_subagent_run(
                    time.perf_counter() - segment_start, subagent_id=label, status="cancelled"
                )
                # What the run said so far, not the finished-run text: that one says
                # nothing was confirmed or tells the executor to re-issue what it just stopped.
                return replace(
                    outcome,
                    text=wrap_agent_payload(
                        AgentTag.SUBAGENT_CANCELLED,
                        run.complete_message or "Stopped by the executor before finishing.",
                    ),
                )

            await _consume_stream_event(run, stream_mode, payload)
    except Exception:
        observe_subagent_run(time.perf_counter() - segment_start, subagent_id=label, status="error")
        raise

    outcome = replace(_finalize_run(run), stopped=cancelled)
    observe_subagent_run(
        time.perf_counter() - segment_start,
        subagent_id=label,
        status="cancelled" if cancelled else "success",
    )
    return outcome


async def _stream_cancelled(ctx: SubagentExecutionContext) -> bool:
    """Whether the user stopped this run's stream, or the turn that dispatched it."""
    for stream_id in (ctx.stream_id, ctx.parent_stream_id):
        if stream_id and await stream_manager.is_cancelled(stream_id):
            return True
    return False


async def _consume_stream_event(run: _StreamRun, stream_mode: str, payload: object) -> None:
    """One (mode, payload) event off the subagent's stream, into the run's state.

    The payload's shape is decided by the mode, which is why the driver holds it
    untyped: each branch narrows it to the shape that mode is documented to carry.
    """
    if stream_mode == "updates":
        await _process_updates_payload(run, cast(dict[str, object], payload))
        return

    if stream_mode == "messages":
        chunk_and_metadata = cast(tuple[BaseMessage, StreamChunkMetadata], payload)
        _process_messages_payload(run, chunk_and_metadata)
        if isinstance(chunk_and_metadata[0], ToolMessage):
            run.tool_ran = True
            run.run_messages.append(chunk_and_metadata[0])
        return

    if stream_mode == "custom" and run.stream_writer:
        run.stream_writer(normalize_custom_event(cast(dict[str, object], payload)))


def _snapshot_messages(snapshot: StateSnapshot) -> list[AnyMessage]:
    """Return the messages a checkpoint holds. Empty means the thread has never run."""
    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, dict):
        return []
    state: _MessagesChannel = cast(_MessagesChannel, values)
    messages = state.get("messages")
    return messages if isinstance(messages, list) else []


async def thread_messages(ctx: SubagentExecutionContext) -> list[AnyMessage]:
    """Read back what this run's thread holds right now, from its checkpoint.

    The authoritative record of what actually reached the model: a run that died
    mid-call committed nothing, and only the checkpoint can tell that apart from
    a call that landed.
    """
    return _snapshot_messages(await ctx.subagent_graph.aget_state(cast(RunnableConfig, ctx.config)))


def _render_intent(intent: ExecutorIntent) -> str:
    lines = [
        f"Outcome the user actually wants: {intent.desired_outcome.strip()}",
        f"Time horizon: {TIME_HORIZON_BRIEF[intent.time_horizon]}",
    ]
    defaults = [d.strip() for d in intent.defaults_assumed if d.strip()]
    if defaults:
        lines.append("Defaults assumed (name them in your report):")
        lines.extend(f"- {d}" for d in defaults)
    lines.append(
        IRREVERSIBLE_APPROVED_BRIEF
        if intent.irreversible_approved
        else IRREVERSIBLE_UNAPPROVED_BRIEF
    )
    return "\n".join(lines)


def compose_executor_brief(
    task: str,
    acceptance_criteria: list[str],
    *,
    verbatim_request: str | None = None,
    last_run: str | None = None,
    playbook_check: str | None = None,
    intent: ExecutorIntent | None = None,
) -> str:
    """Fold the intent, definition-of-done (and verbatim request, previous run) into the brief.

    last_run is a workflow's rendered previous run — its memory now that
    checkpoint threads drop before each fire. playbook_check rides in the brief
    (not the result's narration, since comms can't reach write_playbook) and goes
    last so it reads as the closing instruction.
    """
    criteria = [c.strip() for c in acceptance_criteria if c and c.strip()]
    parts: list[str] = []
    if verbatim_request:
        parts.append(f"Original request (verbatim):\n{verbatim_request.strip()}")
    parts.append(task)
    if last_run:
        parts.append(last_run.strip())
    if intent is not None:
        parts.append(_render_intent(intent))
    if criteria:
        lines = "\n".join(f"- {c}" for c in criteria)
        parts.append(
            "Definition of done (every item must be true before you finish):\n"
            f"{lines}\n{DONE_EVIDENCE_RULE}"
        )
    if playbook_check:
        parts.append(playbook_check.strip())
    return "\n\n".join(parts)


async def prepare_executor_execution(
    task: str,
    configurable: AgentConfigurable,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare execution context for the executor agent.

    Like the platform-subagent prepare flow but resolves the graph via
    GraphManager, uses executor-specific prompts, and injects direct handoff
    hints when selected_tool/tool_category is known. Returns (ctx, None), or
    (None, error) on failure.
    """
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    # Deterministic executor thread, derived purely from the conversation thread
    # so it reconstructs from the conversation id alone — the executor (and its
    # spawned subagents) retains history across call_executor calls in this conversation.
    executor_thread_id = f"{EXECUTOR_THREAD_PREFIX}{thread_id}"

    # VFS session stays pinned to the conversation thread so files written by
    # one executor call are visible to the next.
    vfs_session_id = configurable.get("vfs_session_id") or thread_id

    # Load executor graph. Degrade contract: comms must still receive a
    # tool-result string, so log the real cause loudly and return the error.
    try:
        executor_graph = await GraphManager.get_graph(GraphName.EXECUTOR)
    except GraphUnavailableError as e:
        log.error(
            f"{LogTag.AGENT} prepare_executor_execution: executor_agent graph unavailable",
            error=str(e),
        )
        return None, "Executor agent not available"

    # Build user dict for config
    user: AgentUserContext = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=thread_id,
            user=user,
            agent_name="executor_agent",
        ),
        lane=AgentLane(
            role=AgentRole.EXECUTOR,
            # DEV-ONLY: the switcher's executor pick, stashed by comms. Present only
            # in development; otherwise the executor inherits comms's lane.
            dev_option=dev_option(configurable.get("dev_executor_model")),
        ),
        thread=AgentThread(
            thread_id=executor_thread_id,
            base_configurable=configurable,
            subagent_id="executor_agent",  # Use agent_name as the memory namespace id
            vfs_session_id=vfs_session_id,
            recursion_limit=EXECUTOR_RECURSION_LIMIT,
        ),
    )
    new_configurable = agent_configurable(config)

    # Create system message (executor-specific).
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # When comms provides a known tool_category, hint the executor to go straight
    # to activate_integration(...) and skip the ChromaDB discovery call — removes
    # one redundant round-trip where comms already knows the category.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    resolved_category = get_subagent_by_id(tool_category) if tool_category else None
    if tool_category and resolved_category:
        tool_hint = f"the '{selected_tool}' tool" if selected_tool else "the user's request"
        enhanced_task = (
            f"{task}\n\n"
            f"DIRECT EXECUTION HINT: This request should be handled by "
            f"'{tool_category}'. Skip retrieve_tools discovery and directly "
            f'call activate_integration(integration_id="{tool_category}"), then '
            f"act on {tool_hint} yourself with its tools."
        )
        log.set(
            executor_prep={
                "direct_hint_applied": True,
                "tool_category": tool_category,
                "selected_tool": selected_tool,
            }
        )

    # The executor owns send_notification but only sees the task text comms
    # writes, so inject the notification mode here (keyed off this run's own
    # configurable) rather than depend on comms forwarding the rule. Skip if already present.
    if configurable.get("workflow_id") and "NOTIFICATIONS:" not in enhanced_task:
        notification_section = (
            WORKFLOW_AUTO_NOTIFY_SECTION
            if configurable.get("workflow_notify_on_completion", True)
            else WORKFLOW_SILENT_NOTIFY_SECTION
        )
        enhanced_task = f"{enhanced_task}\n{notification_section}"

    # Surface uploaded files so the executor (which holds the file tools) can act
    # on them directly, rather than depending on comms to hand-copy paths —
    # comms has no file tools of its own.
    if user_id and thread_id:
        uploaded_files = await FileService.list_conversation_files(thread_id, user_id)
        if uploaded_files and (
            files_block := format_files_list(uploaded_files, conversation_id=thread_id)
        ):
            enhanced_task = f"{enhanced_task}\n\n{files_block}"

    # The unenhanced task keeps the DIRECT EXECUTION HINT out of semantic search;
    # request_query lets the executor reuse the recall comms made on the same message.
    messages = await build_initial_messages(
        system_message=system_message,
        agent_name="executor_agent",
        task=enhanced_task,
        seed=ThreadSeed(
            tier=AgentTier.EXECUTOR,
            configurable=new_configurable,
            user_id=user_id,
            retrieval_query=task,
            request_query=configurable.get("user_request"),
        ),
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id=EXECUTOR_INTEGRATION_ID,
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None
