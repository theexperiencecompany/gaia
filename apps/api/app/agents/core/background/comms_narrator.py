"""Silent comms invocation for background-executor results.

The executor's terminal text is never shown to the user directly — it is
handed to the comms agent as internal context (a HumanMessage with an
[EXECUTOR_RESULT]/[EXECUTOR_ERROR] prefix) and comms re-voices it in GAIA's
persona. This module owns that single invocation.
"""

from langchain_core.messages import HumanMessage

from app.agents.core.graph_manager import GraphManager, GraphUnavailableError
from app.agents.prompts.comms_prompts import PLATFORM_DELIVERY_NOTE
from app.constants.agents import EXECUTOR_ERROR_MARKER, EXECUTOR_RESULT_MARKER
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import build_agent_config, execute_graph_silent
from app.utils.agent_utils import strip_internal_agent_markers
from shared.py.wide_events import log


async def narrate_executor_result(
    result_text: str,
    msg_type: str,
    conversation_id: str,
    user: dict,
    returned_note: str = "",
    workflow_id: str | None = None,
) -> str:
    """Invoke the comms graph silently with the executor result as internal context.

    The result is injected as a HumanMessage with a stable prefix so comms
    treats it as ground-truth internal data and re-voices it. Comms applies its
    voice/persona (loaded from the checkpoint) and returns the user-facing text.
    The graph's checkpoint is updated naturally — no manual aupdate_state.

    Returns the comms-generated text, or an empty string on failure.
    """
    prefix = EXECUTOR_ERROR_MARKER if msg_type == "error" else EXECUTOR_RESULT_MARKER
    if workflow_id:
        # Text-only platform delivery: tell comms to restate everything. The
        # card-suppression note (returned_note) is deliberately dropped here —
        # it would tell comms NOT to list data that has no card to fall back on.
        content = f"{PLATFORM_DELIVERY_NOTE}{prefix}\n{result_text}"
    else:
        # Interactive chat: prepend the "already shown as a card" note (if any)
        # so comms doesn't re-narrate data the frontend rendered natively.
        content = (
            f"{returned_note}{prefix}\n{result_text}"
            if returned_note
            else f"{prefix}\n{result_text}"
        )
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
        config = build_agent_config(
            conversation_id=conversation_id,
            user=user,
            agent_name="comms_agent",
        )
        initial_state = {
            "messages": [
                # MUST be a HumanMessage. The message type is load-bearing here:
                #   - SystemMessage: manage_system_prompts_node treats it as the
                #     static-prompt slot and EVICTS COMMS_AGENT_PROMPT, leaving
                #     comms with no persona — so it parrots the raw [EXECUTOR_RESULT]
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
        return strip_internal_agent_markers(notification_text)
    except Exception as e:
        log.error(f"{LogTag.AGENT} narrate_executor_result: failed", error=str(e))
        return ""
