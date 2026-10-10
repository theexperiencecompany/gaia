"""Pre-model hook: tell comms what the chat's browser task is doing.

A browser task outlives the turn that started it, and the user answers it in
chat: "done", "stop", "use the blue one". Comms is the one reader of those
words, so each turn answering the user's message gets a <browser_task> frame
saying whether the task runs or waits on the user, and for what. Like the
executor status frame it shapes this call only, never the checkpoint.
"""

from typing import cast

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import BROWSER_TASK_MARKER
from app.constants.agents import AgentTag, wrap_agent_payload
from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import State
from app.services.browser.chat_task import ChatBrowserTasks, chat_browser_tasks, user_message_turn
from shared.py.wide_events import log


async def browser_task_status_hook(
    state: State, config: RunnableConfig, _store: BaseStore
) -> State:
    """Append a <browser_task> frame while a browser task this chat controls has not ended."""
    try:
        turn = user_message_turn(agent_configurable(config))
        if turn is None:
            return state
        tasks = await chat_browser_tasks(turn)
        if not tasks.running:
            return state
        frame = SystemMessage(
            content=wrap_agent_payload(AgentTag.BROWSER_TASK, describe_browser_tasks(tasks)),
            additional_kwargs={BROWSER_TASK_MARKER: True},
        )
        return cast(State, {**state, "messages": [*state.get("messages", []), frame]})
    except Exception as e:  # a status frame must never break the turn
        log.error(f"{LogTag.AGENT} browser_task_status_hook failed", error_type=type(e).__name__)
        return state


def describe_browser_tasks(tasks: ChatBrowserTasks) -> str:
    """Write the frame's facts: each task, and whether it runs or waits on the user."""
    lines: list[str] = []
    for job in tasks.running:
        paused = tasks.paused
        if paused is not None and paused.job_id == job.job_id:
            lines.append(
                "Paused, waiting for the user to finish a step in the live view: "
                f"{paused.reason}. Task: {job.task}"
            )
        else:
            lines.append(f"Running. Task: {job.task}")
    return "\n".join(lines)
