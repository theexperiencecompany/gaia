"""Write a message that bypassed the agent graph into a conversation's checkpoint.

A message GAIA delivered without running the comms graph (a proactive platform
post, a button answered in place) is invisible to the next turn unless it is
appended to the thread that turn reads. Kept apart from the narrator so the
delivery paths that write here do not pull in the agent stack.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.core.graph_manager import GraphManager
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def record_platform_delivery(conversation_id: str, text: str) -> None:
    """Append a message delivered straight to a platform chat to that conversation's checkpoint.

    Bot-delivered workflow results bypass the graph, but the next bot turn
    reads history from the checkpoint; without this write GAIA has no memory
    of results it just delivered. Best-effort: the message is already sent.
    """
    if text.strip():
        await _append_to_thread(conversation_id, [AIMessage(content=text)])


async def record_exchange_in_thread(conversation_id: str, user_message: str, reply: str) -> None:
    """Append an exchange answered without running the agent to that conversation's checkpoint.

    A button that decides a paused browser task never enters the graph, so the
    thread that later voices the run's result still held the original request
    and reported the step the user had cancelled as unfinished.
    """
    await _append_to_thread(
        conversation_id, [HumanMessage(content=user_message), AIMessage(content=reply)]
    )


async def _append_to_thread(conversation_id: str, messages: list[BaseMessage]) -> None:
    """Write messages into the comms thread with a silent aupdate_state, no model call; never raises."""
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        # as_node="tools", not "agent": the agent node's should_continue needs
        # a store aupdate_state can't inject; the tools->agent edge needs none.
        await comms_graph.aupdate_state(
            {"configurable": {"thread_id": conversation_id}},
            {"messages": messages},
            as_node="tools",
        )
        log.info(
            f"{LogTag.AGENT} Recorded messages in conversation thread",
            conversation_id=conversation_id,
        )
    except Exception as e:  # what it records already reached the user; never break the caller
        log.error(
            f"{LogTag.AGENT} Failed to record messages in conversation thread",
            conversation_id=conversation_id,
            error=str(e),
        )
