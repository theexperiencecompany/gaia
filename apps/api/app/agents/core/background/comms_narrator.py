"""Silent comms invocation for background-executor results.

The executor's terminal text is never shown to the user directly — it is
handed to the comms agent as internal context (a HumanMessage framed in an
<executor_result>/<executor_error> tag) and comms re-voices it in GAIA's
persona. This module owns that single invocation.
"""

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME
from app.agents.core.graph_manager import GraphManager, GraphUnavailableError
from app.agents.llm.lane import AgentRole
from app.agents.prompts.comms_prompts import INTERACTIVE_DELIVERY_NOTE, PLATFORM_DELIVERY_NOTE
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTurn,
    build_agent_config,
    execute_graph_silent,
)
from app.models.agent_models import agent_user_context
from app.models.user_models import AuthenticatedUser
from app.utils.agent_utils import strip_internal_agent_tags
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.wide_events import log


async def narrate_executor_result(
    result_text: str,
    msg_type: str,
    conversation_id: str,
    user: AuthenticatedUser,
    returned_note: str = "",
    workflow_id: str | None = None,
) -> str:
    """Invoke the comms graph silently with the executor result as internal context.

    Injected as a HumanMessage framed in a stable tag so comms treats it as
    ground-truth and re-voices it in its own persona. Returns the
    comms-generated text, or an empty string on failure.
    """
    tag = AgentTag.EXECUTOR_ERROR if msg_type == "error" else AgentTag.EXECUTOR_RESULT
    result_block = wrap_agent_payload(tag, result_text)
    if workflow_id:
        # Text-only platform delivery: tell comms to restate everything. The
        # card-suppression note (returned_note) is deliberately dropped here —
        # it would tell comms NOT to list data that has no card to fall back on.
        content = f"{PLATFORM_DELIVERY_NOTE}{result_block}"
    else:
        # Interactive chat: prepend the "already shown as a card" note (if any)
        # so comms doesn't re-narrate data the frontend rendered natively, plus
        # the bubble-split instruction at the seam where the reply is written.
        content = f"{returned_note}{INTERACTIVE_DELIVERY_NOTE}{result_block}"
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
    except GraphUnavailableError as e:
        # Degrade contract: background narration must never crash the executor
        # flow — drop the narration but log the real cause loudly.
        log.error(
            f"{LogTag.AGENT} narrate_executor_result: comms_agent graph unavailable, dropping narration",
            error=str(e),
            conversation_id=conversation_id,
            msg_type=msg_type,
        )
        return ""
    try:
        user_preferences, writing_style = onboarding_preferences(user.onboarding)
        # A fresh background task with no parent configurable to inherit from, so
        # build_agent_config resolves its own comms lane and stamps plan_type —
        # matching the interactive comms path and keeping the budget wall enforced.
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=conversation_id,
                user=agent_user_context(user),
                agent_name="comms_agent",
            ),
            lane=AgentLane(role=AgentRole.COMMS),
            turn=AgentTurn(
                user_preferences=user_preferences,
                writing_style=writing_style,
            ),
        )
        initial_state = {
            "messages": [
                # MUST be a HumanMessage: a SystemMessage evicts
                # COMMS_AGENT_PROMPT; an AIMessage makes Gemini return empty.
                HumanMessage(
                    content=content,
                    name=BACKGROUND_EXECUTOR_NAME,
                ),
            ],
        }
        notification_text, _ = await execute_graph_silent(comms_graph, initial_state, config)
        return strip_internal_agent_tags(notification_text)
    except Exception as e:
        log.error(f"{LogTag.AGENT} narrate_executor_result: failed", error=str(e))
        return ""


async def record_executor_cancellation(
    conversation_id: str,
    task_id: str | None,
    task: str,
) -> None:
    """Append an <executor_cancelled> record to the comms thread's checkpoint.

    Without this, comms' last knowledge of the task stays "Task accepted...
    I'm on it", and a later turn believes the work is still running. Silent
    aupdate_state write, no model call. Best-effort.
    """
    marker = HumanMessage(
        content=wrap_agent_payload(
            AgentTag.EXECUTOR_CANCELLED,
            f"The background task {task_id or '(unknown id)'} ({task[:200]!r}) was "
            "cancelled by the user before it completed. It did NOT finish and will "
            "not deliver results — do not claim otherwise.",
        ),
        name=BACKGROUND_EXECUTOR_NAME,
    )
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        await comms_graph.aupdate_state(
            {"configurable": {"thread_id": conversation_id}},
            {"messages": [marker]},
            as_node="tools",
        )
        log.info(
            f"{LogTag.AGENT} Recorded executor cancellation in comms checkpoint",
            conversation_id=conversation_id,
            task_id=task_id,
        )
    except Exception as e:  # cancel finalize must proceed regardless
        log.error(
            f"{LogTag.AGENT} Failed to record executor cancellation",
            conversation_id=conversation_id,
            task_id=task_id,
            error=str(e),
        )


async def record_platform_delivery(conversation_id: str, text: str) -> None:
    """Append a message delivered straight to a platform chat to that conversation's checkpoint.

    Bot-delivered workflow results bypass the graph, but the next bot turn
    reads history from the checkpoint — without this write GAIA has no memory
    of results it just delivered. Silent aupdate_state, no model call.
    Best-effort: the message is already sent.
    """
    if not text.strip():
        return
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        # as_node="tools", not "agent": the agent node's should_continue needs
        # a ``store`` aupdate_state can't inject, raising "Missing required
        # config key 'store'". The tools->agent edge needs no store.
        await comms_graph.aupdate_state(
            {"configurable": {"thread_id": conversation_id}},
            {"messages": [AIMessage(content=text)]},
            as_node="tools",
        )
        log.info(
            f"{LogTag.AGENT} Recorded platform delivery in conversation thread",
            conversation_id=conversation_id,
        )
    except Exception as e:  # delivery already happened; never break the caller
        log.error(
            f"{LogTag.AGENT} Failed to record platform delivery in conversation thread",
            conversation_id=conversation_id,
            error=str(e),
        )
