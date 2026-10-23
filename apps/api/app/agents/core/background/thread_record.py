"""Write a message that bypassed the agent graph into a conversation's checkpoint.

A message GAIA delivered without running the comms graph (a proactive platform
post, a button answered in place) is invisible to the next turn unless it is
appended to the thread that turn reads. Kept apart from the narrator so the
delivery paths that write here do not pull in the agent stack.
"""

import hashlib
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.agents.core.background.executor_queue import break_holder_lock, try_acquire_lock
from app.agents.core.graph_manager import GraphManager
from app.agents.core.thread_writes import with_message_ids
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    PROACTIVE_RECORD_JOB_PREFIX,
    PROACTIVE_RECORD_LOCK_HOLDER,
    PROACTIVE_RECORD_RETRY_DELAY,
    PROACTIVE_RECORD_TASK,
)
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


async def record_platform_delivery(conversation_id: str, text: str) -> None:
    """Append a message delivered straight to a platform chat to that conversation's checkpoint.

    Bot-delivered workflow results bypass the graph, but the next bot turn
    reads history from the checkpoint; without this write GAIA has no memory
    of results it just delivered. While a run or an interrupt holds the thread
    the write is handed to a retrying job instead of racing it.
    """
    if not text.strip():
        return
    try:
        recorded = await try_record_platform_delivery(conversation_id, text)
    except Exception:  # the message is already sent: the retrying job below takes over
        log.warning(
            f"{LogTag.AGENT} Recording a delivered message failed; retrying in a job",
            conversation_id=conversation_id,
        )
        recorded = False
    if not recorded:
        await enqueue_worker_job(
            await RedisPoolManager.get_pool(),
            PROACTIVE_RECORD_TASK,
            conversation_id,
            text,
            _job_id=_record_job_id(conversation_id, text),
            _defer_by=PROACTIVE_RECORD_RETRY_DELAY,
        )


async def try_record_platform_delivery(conversation_id: str, text: str) -> bool:
    """Write text under the conversation's executor lock; False when a run or interrupt holds it.

    Taking the same lock a run takes serialises the write against executor
    runs, and a pending interrupt (an approval the run is parked on) must find
    its checkpoint exactly as it left it when it resumes.
    """
    holder = f"{PROACTIVE_RECORD_LOCK_HOLDER}:{uuid4()}"
    if not await try_acquire_lock(f"{EXECUTOR_BUSY_PREFIX}{conversation_id}", holder):
        return False
    try:
        comms_graph = await GraphManager.get_graph("comms_agent")
        state = await comms_graph.aget_state({"configurable": {"thread_id": conversation_id}})
        if any(task.interrupts for task in state.tasks):
            return False
        await _append_to_thread(conversation_id, [AIMessage(content=text)])
        return True
    finally:
        await break_holder_lock(conversation_id, holder)


def _record_job_id(conversation_id: str, text: str) -> str:
    """One retry job per conversation and message, however many times it is handed over."""
    digest = hashlib.sha256(f"{conversation_id}|{text}".encode()).hexdigest()[:32]
    return f"{PROACTIVE_RECORD_JOB_PREFIX}{digest}"


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
            {"messages": with_message_ids(messages)},
            as_node="tools",
        )
        log.info(
            f"{LogTag.AGENT} Recorded messages in conversation thread",
            conversation_id=conversation_id,
        )
    except Exception:  # what it records already reached the user; never break the caller
        log.error(
            f"{LogTag.AGENT} Failed to record messages in conversation thread",
            conversation_id=conversation_id,
        )
