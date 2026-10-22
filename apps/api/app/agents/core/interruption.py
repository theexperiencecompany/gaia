"""Record a user interruption into the conversation's checkpointer thread.

When a user cancels a stream, the graph run stops between supersteps and the
checkpoint is left as if the turn simply ended: any tool calls the model had
emitted sit unanswered, and nothing tells the model — on the next turn — that
it was cut off. filter_messages_node then strips the unanswered calls, so
the evidence of the interruption is erased entirely.

record_interruption closes that gap after the run has stopped:

1. Every dangling tool call in the latest checkpoint gets a synthetic
   ToolMessage marking it as interrupted (which also keeps the transcript
   well-formed for providers that reject unanswered tool calls).
2. A [Request interrupted by user] human message is appended so the model
   sees the turn boundary for what it was.
"""

from typing import TypedDict, cast

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from app.agents.core.thread_writes import with_message_ids
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, agent_configurable
from shared.py.wide_events import log

INTERRUPTION_MARKER = (
    "[The user pressed stop and interrupted your previous response before it "
    "completed. It was cut off by the user's choice — if it comes up, say it was "
    "stopped/interrupted; do not invent another explanation.]"
)
INTERRUPTED_TOOL_RESULT = (
    "[Tool call interrupted: the user stopped the response before this tool finished.]"
)

# additional_kwargs source tag; filter/pruning hooks must leave these alone.
INTERRUPTION_SOURCE = "interruption"


def _interrupted_tool_messages(messages: list[AnyMessage], answered: set[str]) -> list[ToolMessage]:
    """One error ToolMessage per AI tool call the cancelled run left unanswered."""
    backfill: list[ToolMessage] = []
    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue
        tool_calls: list[ToolCall] = msg.tool_calls
        for tc in tool_calls:
            if tc["id"] and tc["id"] not in answered:
                backfill.append(
                    ToolMessage(
                        content=INTERRUPTED_TOOL_RESULT,
                        tool_call_id=tc["id"],
                        name=tc["name"],
                        status="error",
                    )
                )
    return backfill


def build_interruption_messages(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Build the synthetic messages that record an interruption, or [] to no-op.

    Returns one error ToolMessage per dangling tool call plus the
    interruption marker. Returns [] when the last committed message is a
    completed assistant reply with nothing dangling — a cancel that landed
    after the run effectively finished needs no marker.
    """
    if not messages:
        return []

    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    backfill = _interrupted_tool_messages(messages, answered)

    last = messages[-1]
    run_looks_complete = (
        not backfill and isinstance(last, AIMessage) and bool(getattr(last, "content", ""))
    )
    if run_looks_complete:
        return []

    marker = HumanMessage(
        content=INTERRUPTION_MARKER,
        additional_kwargs={"lc_source": INTERRUPTION_SOURCE},
    )
    return [*backfill, marker]


class _GraphValues(TypedDict, total=False):
    """The checkpoint values read back here; only the messages channel matters."""

    messages: list[AnyMessage]


async def record_interruption(graph: CompiledStateGraph, config: RunnableConfig) -> None:
    """Write the interruption record into the thread's checkpoint.

    Must be called after the cancelled run has actually stopped (the astream
    generator closed), so the checkpoint read here is the run's final state.
    """
    state = await graph.aget_state(config)
    values: _GraphValues = cast("_GraphValues", state.values or {}) if state else {}
    updates = build_interruption_messages(values.get("messages", []))
    if not updates:
        return

    # as_node="tools": the reducer only appends, but attributing the write to
    # the tool node keeps the checkpoint's node history coherent.
    await graph.aupdate_state(config, {"messages": with_message_ids(updates)}, as_node="tools")
    configurable: AgentConfigurable = agent_configurable(config)
    log.info(
        f"{LogTag.AGENT} Recorded user interruption in checkpoint",
        thread_id=configurable.get("thread_id"),
        backfilled_tool_calls=len(updates) - 1,
    )
