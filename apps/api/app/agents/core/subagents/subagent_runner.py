"""Shared logic for subagent invocation, used by handoff_tools.py and
executor_tool.py.

Lives here (rather than in handoff_tools.py) so those modules import from it,
avoiding a cyclic dependency.
"""

from dataclasses import dataclass
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from langchain_core.messages import (
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot, interrupt

from app.agents.context.assemble import assemble_context
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.agents.core.background.session import claim_tool_output, note_tool_output_owner
from app.agents.core.graph_manager import (
    CompiledAgentGraph,
    GraphManager,
    GraphUnavailableError,
)
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.llm.lane import AgentRole, dev_option
from app.agents.prompts.workflow_prompts import (
    WORKFLOW_AUTO_NOTIFY_SECTION,
    WORKFLOW_SILENT_NOTIFY_SECTION,
)
from app.constants.general import FINISH_TASK_NAME
from app.constants.hil import LANGGRAPH_INTERRUPT_KEY
from app.constants.llm import EXECUTOR_RECURSION_LIMIT
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.helpers.agent_helpers import build_agent_config
from app.helpers.message_helpers import (
    build_current_time_message,
    create_system_message,
    format_files_list,
)
from app.models.agent_models import (
    AgentConfigurable,
    AgentRunnableConfig,
    AgentUserContext,
    agent_configurable,
)
from app.models.stream_events import ReasoningPayload, ToolOutputPayload
from app.services.chat.chunks import normalize_custom_event
from app.services.files import FileService
from app.utils.agent_utils import IntegrationMetadata, StreamWriterCallable
from app.utils.multimodal import extract_text_content
from app.utils.stream_utils import extract_tool_entries_from_update
from shared.py.wide_events import log


def _capture_finish_task_content(chunk: ToolMessage, current_message: str) -> str:
    """Return the finish_task chunk's textual content if applicable.

    `finish_task` (when used by a subagent) carries the final answer in its
    return value. Capture it as the complete message so the parent handoff
    returns the actual content rather than the literal "Task completed"
    fallback. Subagents with include_finish_task=False terminate via a
    normal AIMessage and never enter this branch.
    """
    if chunk.name == FINISH_TASK_NAME and isinstance(chunk.content, str):
        return chunk.content
    return current_message


def _extract_reasoning_delta(chunk: AIMessageChunk) -> str:
    """Pull this chunk's reasoning ("thinking") text, model-agnostic.

    ChatOpenRouter surfaces reasoning as standard ``reasoning`` content blocks;
    other providers (DeepSeek-style) put it in ``additional_kwargs.reasoning_content``.
    Returns "" when the chunk carries no thinking (e.g. non-reasoning models), so
    the caller emits nothing for them.
    """
    parts: list[str] = []
    for block in getattr(chunk, "content_blocks", None) or []:
        block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if block_type == "reasoning":
            text = (
                block.get("reasoning")
                if isinstance(block, dict)
                else getattr(block, "reasoning", "")
            )
            if text:
                parts.append(text)
    if not parts:
        fallback = (getattr(chunk, "additional_kwargs", None) or {}).get("reasoning_content")
        if fallback:
            parts.append(fallback if isinstance(fallback, str) else str(fallback))
    return "".join(parts)


@dataclass(frozen=True)
class SubagentOutcome:
    """One graph run's result: its text, or the HIL approval it paused on.

    ``interrupt`` carries the payload the gate passed to ``interrupt()``. When it
    is set the graph is checkpointed mid-run and ``text`` is meaningless — the
    caller must bubble the pause up rather than treat it as an answer.
    """

    text: str
    interrupt: dict[str, Any] | None = None

    @property
    def paused(self) -> bool:
        return self.interrupt is not None


def subagent_row_id(tool_call_id: str) -> str:
    """A UI subagent-row id that is STABLE across replays of the same call.

    Derived from the tool_call_id (unique per LLM generation, stable in the
    checkpoint) so a subagent that pauses for approval and resumes reuses its row
    instead of minting a new uuid each replay — which would orphan the paused row
    (left spinning forever) and emit a duplicate for the resumed run. A blank id
    (only defensive — real calls always carry one) falls back to a fresh uuid.
    """
    if not tool_call_id:
        return str(uuid4())
    return str(uuid5(NAMESPACE_URL, f"subagent_row:{tool_call_id}"))


def resume_for_gate(interrupt_payload: dict[str, Any]) -> object:
    """The decision belonging to the subagent gate now paused.

    A synchronous spawn/handoff drives its subagent imperatively, bubbling each HIL
    pause up with ``interrupt()``. When the executor resumes, ``recover_from_checkpoint``
    fast-forwards the subagent to its LATEST parked gate, but the executor replays its
    ``interrupt()`` resume list positionally from zero — so for a task that gated several
    calls in sequence, the first values replayed belong to gates the subagent already ran.
    Feeding one of those to the current gate would apply an earlier decision to a later
    action. Each resume payload carries its own ``approval_id`` (see
    ``resolution._dispatch_resume``); skip any that is not this gate's.

    Only skips a payload whose ``approval_id`` is present and differs from the paused
    gate's — a payload without one (or a matching one) is delivered as-is, so this can
    never over-consume the list and strand the decision.
    """
    target = interrupt_payload.get("approval_id") if isinstance(interrupt_payload, dict) else None
    decision = interrupt(interrupt_payload)
    while (
        target is not None
        and isinstance(decision, dict)
        and decision.get("approval_id") is not None
        and decision.get("approval_id") != target
    ):
        decision = interrupt(interrupt_payload)
    return decision


class SubagentExecutionContext:
    """Container for all data needed to execute a subagent."""

    def __init__(
        self,
        subagent_graph: CompiledAgentGraph,
        agent_name: str,
        config: AgentRunnableConfig,
        configurable: AgentConfigurable,
        integration_id: str,
        initial_state: dict[str, Any],
        user_id: str | None = None,
        stream_id: str | None = None,
    ) -> None:
        self.subagent_graph = subagent_graph
        self.agent_name = agent_name
        self.config = config
        self.configurable = configurable
        self.integration_id = integration_id
        self.initial_state = initial_state
        self.user_id = user_id
        self.stream_id = stream_id


async def build_initial_messages(
    *,
    system_message: SystemMessage,
    tier: AgentTier,
    agent_name: str,
    configurable: AgentConfigurable,
    task: str,
    user_id: str | None = None,
    subagent_id: str | None = None,
    retrieval_query: str | None = None,
    integration_id: str | None = None,
) -> list[AnyMessage]:
    """Seed a worker tier's thread, in canonical slot order.

    Args:
        system_message: The STATIC system message. Must carry no per-user or
            per-time content — that is what keeps the cache prefix shared
            across every user on this tier.
        tier: Which tier is seeding, which decides the sections it gets.
        agent_name: Stamped on the human turn as visibility metadata.
        task: The task text the agent acts on.
        retrieval_query: What the volatile sections retrieve against. Defaults
            to ``task``, but callers set it to the original unenhanced task when
            ``task`` carries injected hints that would pollute semantic search.
        integration_id: For a provider subagent, the underlying integration id
            — what provider metadata and custom instructions are looked up by.
    """
    log.set(agent_prep={"agent_name": agent_name, "task_length": len(task)})

    assembled = await assemble_context(
        SectionContext.from_configurable(
            tier,
            configurable,
            query=retrieval_query if retrieval_query is not None else task,
            user_id=user_id,
            subagent_id=subagent_id,
            integration_id=integration_id,
        )
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
        HumanMessage(
            content=task,
            additional_kwargs={"visible_to": {agent_name}},
        ),
        time_message,
    ]


def _with_current_time(resume: Command, configurable: AgentConfigurable) -> Command:
    """Re-clock a resumed run.

    A resume replaces ``initial_state``, so the fresh time message
    ``build_initial_messages`` would have added never reaches the graph and the
    thread keeps the clock from when it STARTED. A HIL approval pause can leave
    that hours stale — long enough for the model to act on the wrong day.

    Appending it is safe even mid tool-call: ``manage_system_prompts_node`` lifts
    the latest time message to the tail of the conversation (so the
    AIMessage/ToolMessage pairing is untouched) and drops the older copy.
    """
    update = {**resume.update} if isinstance(resume.update, dict) else {}
    update["messages"] = [
        *update.get("messages", []),
        build_current_time_message(user_timezone=configurable.get("user_timezone")),
    ]
    return Command(resume=resume.resume, update=update, goto=resume.goto, graph=resume.graph)


def _process_messages_payload(
    # "messages"-mode payloads are always (message chunk, metadata); the driver
    # above holds them as `Any` only because the shape varies per stream mode.
    payload: tuple[BaseMessage, dict[str, Any]],
    complete_message: str,
    stream_writer: StreamWriterCallable | None,
    subagent_id: str | None,
    stream_id: str,
) -> str:
    """Handle one "messages"-mode stream event, returning the updated message.

    Accumulates AI content, streams reasoning deltas, and emits tool_output for
    ToolMessages — all gated on a non-silent payload and an available writer.

    ``claim_tool_output`` keeps each result to one emission per stream. A
    subagent invoked from a tool of this graph is a nested run, and "messages"
    mode carries its chunks up to this stream annotated with the *inner* run's
    metadata — same ``langgraph_node``, same ``langgraph_checkpoint_ns`` — so
    nothing about the payload distinguishes it from our own. Ungated, the
    executor re-emits every result the subagent already reported, and the second
    copy carries no ``subagent_id``, so the client renders it a second time
    outside the subagent's row. The "updates" branch has the equivalent
    protection in its ``node_name != "agent"`` gate, which is why tool_data
    never doubled and only tool_output did.

    The claim goes to whichever run ANNOUNCED the call (``note_tool_output_owner``,
    in the "updates" branch), not to whichever looks first: both drivers race for
    the same ToolMessage, and on a slow machine the executor won and published the
    untagged copy. A call nobody announced still fails open, so a HIL resume — where
    the announcement happened in the run before the pause — keeps its result rather
    than trading a duplicate card for a missing one.
    """
    chunk, metadata = payload
    if metadata.get("silent"):
        return complete_message

    # Accumulate AI response content
    if chunk and isinstance(chunk, AIMessageChunk):
        content = chunk.text if hasattr(chunk, "text") else str(chunk.content)
        if content:
            complete_message += content

        # Stream the model's thinking interleaved with tool events, so the
        # UI can show what it reasoned about between each step. Carries the
        # subagent_id so the client nests it in the right step (same routing
        # as tool_data/tool_output). Empty for non-reasoning models.
        if stream_writer:
            reasoning_delta = _extract_reasoning_delta(chunk)
            if reasoning_delta:
                reasoning_payload = ReasoningPayload(
                    content=reasoning_delta, subagent_id=subagent_id
                )
                stream_writer({"reasoning": reasoning_payload.model_dump(exclude_none=True)})

    # Emit tool_output when ToolMessage arrives. Text-extract block content so
    # inline media (base64 image blocks) never streams to the frontend.
    elif chunk and isinstance(chunk, ToolMessage):
        content_str = extract_text_content(chunk.content)
        complete_message = _capture_finish_task_content(chunk, complete_message)
        if stream_writer and claim_tool_output(stream_id, chunk.tool_call_id, subagent_id):
            tool_output_payload = ToolOutputPayload(
                tool_call_id=chunk.tool_call_id,
                output=content_str,
                subagent_id=subagent_id,
            )
            stream_writer({"tool_output": tool_output_payload.model_dump(exclude_none=True)})

    return complete_message


async def execute_subagent_stream(
    ctx: SubagentExecutionContext,
    stream_writer: StreamWriterCallable | None = None,
    integration_metadata: IntegrationMetadata | None = None,
    subagent_id: str | None = None,
    resume: Command | None = None,
) -> SubagentOutcome:
    """Execute (or resume) a subagent with streaming and tool tracking.

    Stream event flow:
        - "updates": emit tool_data with complete args when a tool is called
        - "messages": stream content, emit tool_output when a ToolMessage arrives
        - "custom": forward custom events (progress, etc.) to the parent

    ``resume`` continues a thread already paused on a HIL ``interrupt()`` instead
    of starting from ``ctx.initial_state``. When the run pauses, the returned
    outcome carries the approval payload and the caller must bubble it up.
    """
    log.set(subagent={"name": ctx.agent_name, "provider": ctx.integration_id})
    complete_message = ""
    emitted_tool_calls: set[str] = set()
    tool_ran = False
    pending_approvals: list[dict[str, Any]] = []

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

    if resume is not None:
        resume = await _address_resume(ctx.subagent_graph, cast(RunnableConfig, run_config), resume)
        if resume is None:
            # The thread has already consumed this decision. Running it would execute
            # nothing and return empty, which the caller cannot tell apart from a
            # finished task — an empty outcome says "nothing to deliver" outright.
            return SubagentOutcome(text="")

    async for event in ctx.subagent_graph.astream(
        _with_current_time(resume, ctx.configurable) if resume is not None else ctx.initial_state,
        stream_mode=["messages", "custom", "updates"],
        # build_agent_config returns an AgentRunnableConfig, but run_config may be
        # rebuilt above as a dict spread, which mypy widens back to a plain dict.
        config=cast(RunnableConfig, run_config),
        # Persist checkpoints only when this executor/subagent run exits, not
        # after every step (langgraph's default durability="async"). The
        # executor/subagent path is a single logical unit of work whose
        # intermediate steps never need to survive a mid-run crash — only the
        # final state must be durable so the next turn on the same thread
        # resumes with full context. This collapses O(steps) checkpoint writes
        # per run to one, cutting Postgres checkpoint churn. The comms graph
        # driver keeps "async" (its mid-run checkpoints are needed).
        durability="exit",
    ):
        # Check for cancellation
        if ctx.stream_id and await stream_manager.is_cancelled(ctx.stream_id):
            log.info(f"{LogTag.AGENT} Subagent stream cancelled by user", stream_id=ctx.stream_id)
            break

        # Handle 2-tuple format only (no subgraphs)
        if len(event) != 2:
            continue
        # A list `stream_mode` makes astream yield (mode, payload) tuples, which
        # langgraph's own overload return type does not express.
        stream_mode, payload = cast(tuple[str, Any], event)

        if stream_mode == "updates":
            # The run paused. Record the approval and KEEP DRAINING — never break.
            #
            # Under durability="exit" the run-exit save is the only checkpoint write
            # there is, and abandoning the generator early skips it: the writes of
            # every task that COMPLETED in the interrupting step are lost, so those
            # tasks re-run on resume. That is how an ungated tool call beside a gated
            # one used to execute twice. Verified in isolation — break + "exit" is the
            # only combination that loses them; either alone is fine.
            if LANGGRAPH_INTERRUPT_KEY in payload:
                # ONE event per paused task, so two gated calls in a message arrive as
                # two events. Accumulate: the caller stamps re-dispatch context onto
                # every id here, and an approval left out of that can never be applied.
                pending_approvals.extend(interrupt_values(payload[LANGGRAPH_INTERRUPT_KEY]))
                log.info(f"{LogTag.HIL} Subagent paused on approval", agent=ctx.agent_name)
                continue
            for node_name, state_update in payload.items():
                # Only emit tool_data from the LLM ("agent") node.
                # Pre-model hooks (filter_messages_node, manage_system_prompts_node,
                # etc.) produce "updates" events containing historical AIMessages
                # with tool_calls from previous checkpoint runs — emitting those
                # would replay stale tool cards into the current stream.
                if node_name != "agent":
                    continue
                # Use shared helper to extract and format tool entries
                entries = await extract_tool_entries_from_update(
                    state_update=state_update,
                    emitted_tool_calls=emitted_tool_calls,
                    integration_metadata=integration_metadata,
                )
                for tc_id, tool_entry in entries:
                    # Announcing the call is what claims its result: "messages" mode
                    # will replay this ToolMessage into the outer run's stream too.
                    note_tool_output_owner(ctx.stream_id or "", tc_id, subagent_id)
                    if stream_writer:
                        chunk_data: dict[str, Any] = {"tool_data": tool_entry}
                        if subagent_id:
                            chunk_data["tool_data"] = {**tool_entry, "subagent_id": subagent_id}
                        stream_writer(chunk_data)
            continue

        if stream_mode == "messages":
            complete_message = _process_messages_payload(
                payload, complete_message, stream_writer, subagent_id, ctx.stream_id or ""
            )
            if isinstance(payload[0], ToolMessage):
                tool_ran = True
            continue

        if stream_mode == "custom":
            if stream_writer:
                stream_writer(normalize_custom_event(payload))

    # A pause is not a result: the narration-only heuristic below would misread a
    # half-finished run as "planning text" and tell the parent to re-issue it.
    if pending_approvals:
        return SubagentOutcome(text=complete_message, interrupt=merge_approvals(pending_approvals))

    # A subagent that only narrated and never ran a tool didn't do the work — return
    # an actionable signal so the parent re-issues the handoff instead of treating the
    # planning text as the result.
    if not tool_ran and not emitted_tool_calls and complete_message:
        log.warning("subagent_returned_narration_only", subagent_name=ctx.agent_name)
        final_message = (
            f"The {ctx.agent_name} subagent ended without running any tool — it only "
            f'produced planning text: "{complete_message}". Re-issue the handoff with an '
            "explicit instruction to perform the action."
        )
    else:
        final_message = complete_message or "Task completed"
    log.set(
        subagent={
            "name": ctx.agent_name,
            "provider": ctx.integration_id,
            "response_length": len(final_message),
            "messages_count": len(ctx.initial_state.get("messages", [])),
        }
    )
    return SubagentOutcome(text=final_message)


def _snapshot_messages(snapshot: StateSnapshot) -> list[AnyMessage]:
    """The messages a checkpoint holds. Empty means the thread has never run."""
    values = getattr(snapshot, "values", None) or {}
    messages = values.get("messages") if isinstance(values, dict) else None
    return messages if isinstance(messages, list) else []


def _final_text_from_snapshot(snapshot: StateSnapshot) -> str:
    messages = _snapshot_messages(snapshot)
    if not messages:
        return ""
    content = getattr(messages[-1], "content", "")
    return content if isinstance(content, str) else str(content or "")


async def recover_from_checkpoint(ctx: SubagentExecutionContext) -> SubagentOutcome | None:
    """What this subagent's own thread already holds, or ``None`` if it never ran.

    Three states, and conflating the last two is how a completed subagent gets driven a
    second time:

    * **Parked** (``snapshot.next``) — mid-run on a HIL interrupt. Returned as a paused
      outcome so the caller bubbles the approval up. A paused outcome with an empty
      payload means the interrupt is unreadable, which downstream treats as a malformed
      approval and fails the run rather than act.
    * **Finished** — no pending work but state on the thread. Returned as its
      checkpointed final answer: re-running would repeat every action it took.
    * **Never ran** — no state at all. ``None``, so the caller starts it normally.
    """
    snapshot = await ctx.subagent_graph.aget_state(cast(RunnableConfig, ctx.config))
    if snapshot.next:
        return SubagentOutcome(
            text="", interrupt=interrupt_payload(getattr(snapshot, "interrupts", ()) or ())
        )
    if not _snapshot_messages(snapshot):
        return None
    return SubagentOutcome(text=_final_text_from_snapshot(snapshot) or "Task completed.")


async def _address_resume(
    graph: CompiledAgentGraph, config: RunnableConfig, resume: Command
) -> Command | None:
    """Aim a resume at the one interrupt it answers, or ``None`` if there is none left.

    A bare ``Command(resume=value)`` feeds the next interrupt positionally, and
    LangGraph refuses it outright once a thread holds more than one pending
    interrupt — which is the ordinary case here, because two destructive calls
    in one AI message both reach the gate in a single node pass and both park.
    Left bare, the user approves, the dispatch raises, the approved action never
    runs, LangGraph's own error text reaches them, and the second approval stays
    pending forever with every retry re-entering the same failure.

    ``None`` means the thread has already consumed this decision and finished: a
    resume dispatched at it would run no node at all, and the caller would read the
    empty result as a completed task and tell the user an action succeeded that this
    run never performed. The sweep re-dispatches any decision it cannot prove reached
    a run (``list_decided_unresumed``), so a crash between resuming and stamping the
    record puts a second, redundant resume on a thread that is already done.

    The interrupts are read from the live checkpoint rather than from anything
    recorded at pause time: the id has to match the interrupt that is actually
    pending now, and a stored copy can only disagree with it.

    Falls through unchanged when the thread holds exactly one interrupt, or when none
    of them carries this decision's ``approval_id`` — a bare resume is correct in the
    first case, and in the second there is nothing better to do than let the existing
    path report the mismatch.
    """
    snapshot = await graph.aget_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts and not snapshot.next:
        log.error(
            f"{LogTag.HIL} Resume arrived for a thread with no pending work; "
            "the decision was already applied and this run has nothing to do",
            approval_id=str(_approval_id_of(resume) or ""),
        )
        return None

    approval_id = _approval_id_of(resume)
    if not approval_id or len(interrupts) < 2:
        return resume
    payload = resume.resume

    for item in interrupts:
        value = getattr(item, "value", None)
        interrupt_id = getattr(item, "id", None)
        if interrupt_id and isinstance(value, dict) and value.get("approval_id") == approval_id:
            log.info(
                f"{LogTag.HIL} Addressing resume to its interrupt",
                approval_id=str(approval_id),
                pending_interrupts=len(interrupts),
            )
            return Command(resume={interrupt_id: payload}, update=resume.update, goto=resume.goto)

    log.warning(
        f"{LogTag.HIL} No pending interrupt matches this decision",
        approval_id=str(approval_id),
        pending_interrupts=len(interrupts),
    )
    return resume


def _approval_id_of(resume: Command) -> str | None:
    """Which gate this decision answers, when the payload carries one."""
    payload = resume.resume
    if not isinstance(payload, dict):
        return None
    approval_id = payload.get("approval_id")
    return str(approval_id) if approval_id else None


def interrupt_payload(raw: object) -> dict[str, Any]:
    """The HIL payload inside LangGraph Interrupt object(s) — from a stream event's
    ``__interrupt__`` tuple or a state snapshot's ``interrupts``.

    Carries EVERY pending approval, not just the first. Two destructive calls in one AI
    message park two tasks in the same step, and the caller stamps re-dispatch context
    onto each id this returns (``executor_runner._record_pause``). Returning only the
    first left the second with no ``resume_item`` at all, so approving it raised
    ``ApprovalNotResumable`` and the decision could never be applied.

    The first payload's own fields stay at the top level, so callers that read a single
    approval (``resume_for_gate``) are unaffected; ``approval_ids`` is what the batch
    readers use. ``{}`` when no object carries a dict value (downstream treats that as
    malformed → deny).
    """
    return merge_approvals(interrupt_values(raw))


def interrupt_values(raw: object) -> list[dict[str, Any]]:
    """The dict payloads inside one or more LangGraph ``Interrupt`` objects."""
    items = raw if isinstance(raw, (list, tuple)) else (raw,)
    return [
        value
        for value in (getattr(item, "value", item) for item in items)
        if isinstance(value, dict)
    ]


def merge_approvals(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold several pending approvals into one payload carrying ALL their ids.

    The first payload's own fields stay at the top level, so callers reading a single
    approval (``resume_for_gate``) are unaffected; ``approval_ids`` is what the batch
    readers use (``executor_runner._paused_approval_ids``).
    """
    if not payloads:
        return {}
    ids = [str(payload["approval_id"]) for payload in payloads if payload.get("approval_id")]
    if len(ids) < 2:
        return payloads[0]
    return {**payloads[0], "approval_ids": ids}


def compose_executor_brief(
    task: str,
    acceptance_criteria: list[str],
    *,
    verbatim_request: str | None = None,
) -> str:
    """Fold the definition-of-done (and verbatim request) into the executor brief."""
    criteria = [c.strip() for c in acceptance_criteria if c and c.strip()]
    parts: list[str] = []
    if verbatim_request:
        parts.append(f"Original request (verbatim):\n{verbatim_request.strip()}")
    parts.append(task)
    if criteria:
        lines = "\n".join(f"- {c}" for c in criteria)
        parts.append(f"Definition of done (every item must be true before you finish):\n{lines}")
    return "\n\n".join(parts)


async def prepare_executor_execution(
    task: str,
    configurable: AgentConfigurable,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, str | None]:
    """Prepare execution context for the executor agent.

    Like the platform-subagent prepare flow but resolves the graph via
    GraphManager, uses executor-specific prompts, and injects direct handoff
    hints when selected_tool/tool_category is known.

    Returns (SubagentExecutionContext, None) on success, or (None, error) on
    failure.
    """
    user_id = configurable.get("user_id")
    thread_id = configurable.get("thread_id", "")

    # Deterministic executor thread, derived purely from the conversation
    # thread so it can be reconstructed from the conversation id alone. The
    # executor (and the subagents it spawns, whose threads are derived from
    # this one) retains its history across call_executor invocations within
    # the same conversation.
    executor_thread_id = f"executor_{thread_id}"

    # VFS session stays pinned to the conversation thread so files written by
    # one executor call are visible to the next.
    vfs_session_id = configurable.get("vfs_session_id") or thread_id

    # Load executor graph. Degrade contract: comms must still receive a
    # tool-result string, so log the real cause loudly and return the error.
    try:
        executor_graph = await GraphManager.get_graph("executor_agent")
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

    # Build config
    config = await build_agent_config(
        conversation_id=thread_id,
        user=user,
        thread_id=executor_thread_id,
        base_configurable=configurable,
        agent_name="executor_agent",
        role=AgentRole.EXECUTOR,
        # DEV-ONLY: the switcher's executor pick, stashed by comms. Present only
        # in development; otherwise the executor inherits comms's lane.
        dev_option=dev_option(configurable.get("dev_executor_model")),
        subagent_id="executor_agent",  # Use agent_name as the memory namespace id
        vfs_session_id=vfs_session_id,
        recursion_limit=EXECUTOR_RECURSION_LIMIT,
    )
    new_configurable = agent_configurable(config)

    # Create system message (executor-specific)
    system_message = create_system_message(
        user_id=user_id,
        agent_type="executor",
        user_name=configurable.get("user_name"),
    )

    # When comms provides a known tool_category, hint the executor to go
    # straight to handoff(subagent_id=...) and skip the ChromaDB discovery
    # call. We do NOT pre-bind tools — the target subagent still does its own
    # retrieval. This only removes one redundant round-trip where comms
    # already knows the category.
    enhanced_task = task
    tool_category = configurable.get("tool_category")
    selected_tool = configurable.get("selected_tool")
    if tool_category and get_subagent_by_id(tool_category):
        tool_hint = f"the '{selected_tool}' tool" if selected_tool else "the user's request"
        enhanced_task = (
            f"{task}\n\n"
            f"DIRECT EXECUTION HINT: This request should be handled by "
            f"'{tool_category}'. Skip retrieve_tools discovery and directly "
            f'call handoff(subagent_id="{tool_category}", task="{task}") to '
            f"route {tool_hint}."
        )
        log.set(
            executor_prep={
                "direct_hint_applied": True,
                "tool_category": tool_category,
                "selected_tool": selected_tool,
            }
        )

    # Workflow runs: the executor owns send_notification, but it only sees the
    # task text comms writes. Inject the notification mode here, keyed off the
    # run's own configurable, so the no-double-notify guarantee never depends
    # on comms forwarding the rule. Skip if the task already carries the section
    # (format_workflow_execution_message embeds it) to avoid duplicating it.
    if configurable.get("workflow_id") and "NOTIFICATIONS:" not in enhanced_task:
        notification_section = (
            WORKFLOW_AUTO_NOTIFY_SECTION
            if configurable.get("workflow_notify_on_completion", True)
            else WORKFLOW_SILENT_NOTIFY_SECTION
        )
        enhanced_task = f"{enhanced_task}\n{notification_section}"

    # Surface the conversation's uploaded files so the executor — which holds the
    # read/bash/search_uploaded_files tools — can act on them directly, rather than
    # depending on comms to hand-copy paths into the task. Comms can't use these
    # paths itself (it has no file tools); the executor is where file work happens.
    if user_id and thread_id:
        uploaded_files = await FileService.list_conversation_files(thread_id, user_id)
        if uploaded_files and (
            files_block := format_files_list(uploaded_files, conversation_id=thread_id)
        ):
            enhanced_task = f"{enhanced_task}\n\n{files_block}"

    # Build messages using shared helper.
    # Pass original task as retrieval_query so memory/context semantic search
    # is not polluted by the DIRECT EXECUTION HINT injected into enhanced_task.
    messages = await build_initial_messages(
        system_message=system_message,
        tier=AgentTier.EXECUTOR,
        agent_name="executor_agent",
        configurable=new_configurable,
        task=enhanced_task,
        user_id=user_id,
        retrieval_query=task,
    )

    return SubagentExecutionContext(
        subagent_graph=executor_graph,
        agent_name="executor_agent",
        config=config,
        configurable=new_configurable,
        integration_id="executor",
        initial_state={"messages": messages, "todos": []},
        user_id=user_id,
        stream_id=stream_id,
    ), None
