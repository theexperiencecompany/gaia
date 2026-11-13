"""Silent writes of what happened outside a comms turn into the comms thread.

No model call: a background run's report, a cancellation, or an exchange answered
without the agent is appended to the conversation's checkpoint, so the chat's next
turn knows it. What GAIA tells the user of a run is written by the outbox.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME
from app.agents.core.graph_manager import GraphManager
from app.agents.core.thread_lock import comms_thread_lock
from app.agents.core.thread_writes import with_message_ids
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


async def record_executor_report(conversation_id: str, result_text: str, msg_type: str) -> None:
    """Append a tracked todo run's report to its chat's comms thread.

    The chat shows the report on screen, so its next turn must know it, whether or not anyone is told.
    """
    # MUST be a HumanMessage: a SystemMessage evicts COMMS_AGENT_PROMPT; an
    # AIMessage makes Gemini return empty.
    tag = AgentTag.EXECUTOR_ERROR if msg_type == "error" else AgentTag.EXECUTOR_RESULT
    report = HumanMessage(
        content=wrap_agent_payload(tag, result_text), name=BACKGROUND_EXECUTOR_NAME
    )
    await _append_to_thread(conversation_id, [report])


async def record_executor_cancellation(
    conversation_id: str,
    task_id: str | None,
    task: str,
) -> None:
    """Append an <executor_cancelled> record to the comms thread's checkpoint.

    Without this, comms' last knowledge of the task stays "Handed to the executor...
    I'm on it", and a later turn believes the work is still running. Silent
    aupdate_state write, no model call. A failed write is logged and swallowed; only a
    thread lock that cannot be taken raises.
    """
    marker = HumanMessage(
        content=wrap_agent_payload(
            AgentTag.EXECUTOR_CANCELLED,
            f"The background task {task_id or '(unknown id)'} ({task[:200]!r}) was "
            "cancelled by the user before it completed. It did NOT finish and will "
            "not deliver results. Do not claim otherwise.",
        ),
        name=BACKGROUND_EXECUTOR_NAME,
    )
    async with comms_thread_lock(conversation_id):
        try:
            comms_graph = await GraphManager.get_graph("comms_agent")
            await comms_graph.aupdate_state(
                {"configurable": {"thread_id": conversation_id}},
                {"messages": with_message_ids([marker])},
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
    """Write messages into the comms thread with a silent aupdate_state, no model call.

    A failed write is logged and swallowed; only a thread lock that cannot be taken raises.
    """
    async with comms_thread_lock(conversation_id):
        try:
            comms_graph = await GraphManager.get_graph("comms_agent")
            # as_node="tools", not "agent": the agent node's should_continue needs
            # a store aupdate_state can't inject; the tools->agent edge needs none.
            await comms_graph.aupdate_state(
                {"configurable": {"thread_id": conversation_id}},
                {"messages": with_message_ids(messages)},
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
