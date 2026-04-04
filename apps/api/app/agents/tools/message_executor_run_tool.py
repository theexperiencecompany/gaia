"""message_executor_run tool — comms agent sends a message to a running executor task.

Pushes to the executor inbox queue by task_id (returned from call_executor).
The executor's check_subagent_inbox pre-model hook drains it before each LLM
turn and injects the message into state.

Use this when the user sends a follow-up message or clarification while an
executor task is already running — comms can forward context directly.

Raises if the executor inbox is not registered (executor already completed or
task_id is invalid).
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.inbox import get_executor_inbox_by_task_id
from shared.py.wide_events import log


@tool
async def message_executor_run(
    config: RunnableConfig,
    task_id: Annotated[
        str,
        "The task_id returned by call_executor when the executor run was started.",
    ],
    message: Annotated[
        str,
        "Message to send to the running executor. Will be injected before its next LLM turn.",
    ],
) -> str:
    """Send a message to an already-running executor task identified by task_id.

    Use this when the user provides follow-up context or clarification while
    the executor is still running. The executor will receive the message before
    its next LLM invocation.

    Raises an error if the executor run has already completed or the task_id
    is not found.
    """
    queue = get_executor_inbox_by_task_id(task_id)
    if queue is None:
        raise RuntimeError(
            f"Executor run '{task_id}' is not registered. "
            "It may have already completed or the task_id is invalid."
        )

    await queue.put({"type": "comms_message", "message": message})
    log.info(f"message_executor_run: message queued for task_id={task_id!r}")
    return f"Message sent to executor run '{task_id}'."
