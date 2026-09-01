"""Silent comms invocation for background-executor results.

The executor's terminal text is never shown to the user directly — it is
handed to the comms agent as internal context (a HumanMessage framed in an
``<executor_result>``/``<executor_error>`` tag) and comms re-voices it in GAIA's
persona. This module owns that single invocation.
"""

from langchain_core.messages import AIMessage, HumanMessage

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

    The result is injected as a HumanMessage framed in a stable tag so comms
    treats it as ground-truth internal data and re-voices it. Comms applies its
    voice/persona (loaded from the checkpoint) and returns the user-facing text.
    The graph's checkpoint is updated naturally — no manual aupdate_state.

    Returns the comms-generated text, or an empty string on failure.
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
        user_preferences, writing_style = onboarding_preferences(user.get("onboarding"))
        # A fresh background task with no parent configurable to inherit from, so
        # build_agent_config resolves its own comms lane and stamps plan_type —
        # matching the interactive comms path and keeping the budget wall enforced.
        config = await build_agent_config(
            identity=AgentIdentity(
                conversation_id=conversation_id,
                user=user,
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
                # MUST be a HumanMessage. The message type is load-bearing here:
                #   - SystemMessage: manage_system_prompts_node treats it as the
                #     static-prompt slot and EVICTS COMMS_AGENT_PROMPT, leaving
                #     comms with no persona — so it parrots the raw <executor_result>
                #     instead of speaking in GAIA's voice.
                #   - AIMessage: Gemini sees a trailing assistant turn as already
                #     answered and returns an empty completion.
                #   - HumanMessage: not a system message, so it's immune to the
                #     prompt pruning (the checkpoint's persona survives) and Gemini
                #     treats it as a turn to respond to. This is how it worked
                #     before the HumanMessage→SystemMessage regression.
                HumanMessage(
                    content=content,
                    name="background_executor",
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
    """Append an ``<executor_cancelled>`` record to the comms thread's checkpoint.

    Without this, a cancelled executor leaves comms' last knowledge of the task
    as the 'Task accepted... I'm on it' tool result — on any later turn the
    model believes the work is still running (or quietly done). This is a
    silent context write via ``aupdate_state``: no model call, no user-facing
    message. Best-effort — a failure here must not break the cancel path.
    """
    marker = HumanMessage(
        content=wrap_agent_payload(
            AgentTag.EXECUTOR_CANCELLED,
            f"The background task {task_id or '(unknown id)'} ({task[:200]!r}) was "
            "cancelled by the user before it completed. It did NOT finish and will "
            "not deliver results — do not claim otherwise.",
        ),
        name="background_executor",
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
    """Append a message delivered straight to a platform chat (outside any comms
    turn) to that conversation's checkpoint thread.

    Workflow results pushed into the user's Telegram/WhatsApp sessions are saved
    to MongoDB and sent by the bots without passing through the graph — but the
    next bot turn reads its history from the checkpoint, so without this write
    GAIA has no memory of results it just delivered. Silent ``aupdate_state``
    write, no model call. Best-effort: the message is already sent, so a failure
    here must not break delivery.
    """
    if not text.strip():
        return
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        # as_node="tools", not "agent": aupdate_state evaluates as_node's outgoing
        # edges to compute the next tasks, and the agent node's should_continue
        # branch requires a ``store`` that aupdate_state cannot inject — so writing
        # as "agent" raises "Missing required config key 'store'" and the record
        # is lost. The tools->agent edge is unconditional and needs no store, so
        # the write lands; the AIMessage is appended by the reducer either way.
        # Mirrors record_executor_cancellation.
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
