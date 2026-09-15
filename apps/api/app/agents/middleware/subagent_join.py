"""Force the executor to collect background subagents before its turn can end.

wait_for_subagents is model-invoked, but collection must not be
model-discretionary: an executor that finishes with subagents still in
flight, or parked on a HIL approval, strands them. When the model produces a
turn-ending response while background work is uncollected, this after-model
hook rewrites its tool calls to a single wait_for_subagents call, routing to
the join before the model can finish for real.

The rewrite mutates the response message in place: acall_model returns the
same object handed to after-model hooks, and the messages reducer appends —
a returned state update could not replace the message's tool calls.
"""

from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.core.background.bg_results import has_bg_subagent_results
from app.agents.core.background.session import get_pending_subagents
from app.constants.general import FINISH_TASK_NAME, WAIT_FOR_SUBAGENTS_NAME
from app.constants.log_tags import LogTag
from app.services.hil.approvals_store import list_parked_subagents_for_conversation
from shared.py.wide_events import log


class SubagentJoinMiddleware(AgentMiddleware):
    """Executor-only: never let a turn end while background subagents are uncollected."""

    async def aafter_model(
        self,
        state: AgentState[Any],
        runtime: Runtime[Any],
    ) -> dict[str, Any] | None:
        del runtime  # config comes from the graph context var
        response = _latest_ai_message(state)
        if response is None or not _is_turn_ending(response):
            return None

        configurable = (get_config() or {}).get("configurable", {}) or {}
        stream_id = str(configurable.get("stream_id") or "")
        conversation_id = str(configurable.get("conversation_id") or "")
        if not stream_id or not conversation_id:
            return None
        # Still-running subagents never force a join: their landing queues a
        # collection turn (see enqueue_collection_run) instead of trapping the
        # executor in a blocking-poll loop for long-running work.
        if get_pending_subagents(stream_id) > 0:
            return None
        # Everything has landed — force the join only if something is actually
        # uncollected. Collection is then instant (results ready) or a deliberate
        # pause (parked approvals); it never blocks on running work.
        uncollected = await has_bg_subagent_results(conversation_id)
        if not uncollected and configurable.get("execution_mode") != "background":
            uncollected = bool(await list_parked_subagents_for_conversation(conversation_id))
        if not uncollected:
            return None

        dropped = [call.get("name", "") for call in response.tool_calls]
        log.info(
            f"{LogTag.AGENT} Forcing subagent collection: model tried to end the turn with uncollected background subagents",
            forced_tool=WAIT_FOR_SUBAGENTS_NAME,
            dropped_calls=dropped,
            conversation_id=conversation_id,
        )
        # In-place rewrite (see module docstring). finish_task, if present, is
        # dropped — the model re-finishes after the join returns the results.
        response.tool_calls = [
            {"name": WAIT_FOR_SUBAGENTS_NAME, "args": {}, "id": f"join_{uuid4().hex[:12]}"}
        ]
        return None


def _latest_ai_message(state: AgentState[Any]) -> AIMessage | None:
    messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", [])
    if not messages:
        return None
    last = messages[-1]
    return last if isinstance(last, AIMessage) else None


def _is_turn_ending(response: AIMessage) -> bool:
    """Return whether the response ends the turn: no tool calls, or only finish_task."""
    if not response.tool_calls:
        return True
    return all(call.get("name") == FINISH_TASK_NAME for call in response.tool_calls)
