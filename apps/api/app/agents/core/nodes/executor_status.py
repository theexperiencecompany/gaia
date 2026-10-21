"""Pre-model hook: tell comms, every turn, whether its background work is really running.

The comms thread's only trace of a dispatch is the hand-off tool result from the
turn that made it, and a run that died, or whose result never reached the chat,
leaves that hand-off looking pending forever. This hook reads the live state (the
busy lock, its holder's liveness, the background subagents) and states it twice
for THIS model call only: on the open hand-off itself, where the model reads the
history, and in a status frame carrying the run's progress. Hook returns shape the
per-call input, not the checkpoint (see manage_system_prompts), so neither ever
accumulates in the thread. Runs BEFORE manage_system_prompts_node, which slots
the frame into the system block.
"""

from typing import cast

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME, EXECUTOR_STATUS_MARKER
from app.agents.core.background.executor_progress import describe_progress, read_progress
from app.agents.core.background.executor_queue import read_executor_activity
from app.agents.core.background.running_registry import RunningSubagents
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.executor_activity_models import ExecutorActivity
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log


def _has_dispatched(messages: list[AnyMessage]) -> bool:
    return any(
        isinstance(message, AIMessage)
        and any(call["name"] == CALL_EXECUTOR_NAME for call in message.tool_calls)
        for message in messages
    )


def _open_handoff(messages: list[AnyMessage]) -> int | None:
    """Index of the latest hand-off no result, error or cancel record has answered, or None."""
    executor_calls = {
        call["id"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"] == CALL_EXECUTOR_NAME
    }
    open_index: int | None = None
    for index, message in enumerate(messages):
        if isinstance(message, ToolMessage) and message.tool_call_id in executor_calls:
            open_index = index
        elif message.name == BACKGROUND_EXECUTOR_NAME:
            open_index = None
    return open_index


def _handoff_status(activity: ExecutorActivity, subagents_running: int) -> str:
    if activity is ExecutorActivity.RUNNING or subagents_running:
        return (
            "[Status now: still running. Anything the user adds to it goes through "
            "call_executor, which hands it to this run.]"
        )
    if activity is ExecutorActivity.DEAD:
        return "[Status now: ended. It stopped before it finished and delivered no result.]"
    # Ended on its own terms, so its checkpoint was written: unlike a dead run, the
    # executor can say what it did. A run that died wrote nothing (durability="exit").
    return (
        "[Status now: ended, but its result never reached this chat. What it did is in "
        "the executor's own history, so call_executor can find out.]"
    )


def _with_handoff_status(messages: list[AnyMessage], status: str) -> list[AnyMessage]:
    index = _open_handoff(messages)
    if index is None or not isinstance(messages[index].content, str):
        return messages
    handoff = messages[index]
    annotated = handoff.model_copy(update={"content": f"{handoff.content}\n\n{status}"})
    return [*messages[:index], annotated, *messages[index + 1 :]]


def _status_text(activity: ExecutorActivity, task_id: str, subagents_running: int) -> str:
    task = f"task_id: {task_id or 'unknown'}"
    if activity is ExecutorActivity.RUNNING or subagents_running:
        return f"Background work is running right now ({task}). Its result has not arrived yet."
    if activity is ExecutorActivity.DEAD:
        return (
            f"No background work is running. The last task ({task}) stopped before it "
            "finished, and its result will not arrive."
        )
    return (
        "No background work is running right now. Every earlier hand-off in this chat has "
        "finished or stopped, even one whose result you have not seen."
    )


async def executor_status_hook(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Append the conversation's live background-work status frame."""
    try:
        configurable: AgentConfigurable = agent_configurable(config)
        thread_id = configurable.get("thread_id")
        if not thread_id or not redis_cache.client:
            return state

        # The narrated run still holds the busy lock. Its flag decides, never a message
        # name: narration triggers persist in the thread, and a scan for one silences
        # every later turn of the conversation.
        if configurable.get("is_result_narration"):
            return state
        messages = state.get("messages", [])

        snapshot = await read_executor_activity(thread_id)
        subagents = await RunningSubagents(thread_id).live()
        running = snapshot.activity is ExecutorActivity.RUNNING or bool(subagents)
        # A chat that never handed work off has no status worth a line of context.
        if (
            not running
            and snapshot.activity is ExecutorActivity.IDLE
            and not _has_dispatched(messages)
        ):
            return state

        text = _status_text(snapshot.activity, snapshot.task_id, len(subagents))
        if snapshot.activity is ExecutorActivity.RUNNING:
            progress = describe_progress(await read_progress(thread_id, snapshot.holder))
            if progress:
                text = f"{text} What it has done so far:\n{progress}"
        status = SystemMessage(content=text, additional_kwargs={EXECUTOR_STATUS_MARKER: True})
        annotated = _with_handoff_status(
            messages, _handoff_status(snapshot.activity, len(subagents))
        )
        return cast(State, {**state, "messages": [*annotated, status]})
    except Exception as e:  # a status frame must never break the turn
        log.error(f"{LogTag.AGENT} executor_status_hook failed", error_type=type(e).__name__)
        return state
