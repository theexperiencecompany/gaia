"""Pre-model hook: tell comms about a live background executor run.

While an executor runs, the comms thread's only trace of it is the stale
'Task accepted... I'm on it' tool result from the dispatching turn. If the
user sends a new message mid-run ("what are you doing?", "did that finish?"),
the model has no way to know the task is still in flight.

This hook reads the per-conversation executor busy lock and, when held,
appends a system status line for THIS model call only. Hook returns shape the
per-call input, not the checkpoint (see manage_system_prompts), so the status
never accumulates in the thread — it simply reflects the lock each turn.
Runs BEFORE manage_system_prompts_node, which slots it into the system block.
"""

from typing import cast

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME, EXECUTOR_STATUS_MARKER
from app.agents.core.background.executor_queue import decode_raw_item, parse_lock_value
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log


async def executor_status_hook(state: State, config: RunnableConfig, store: BaseStore) -> State:  # noqa: ARG001 -- execute_hooks() passes state/config/store positionally
    """Append a live-executor status frame when the busy lock is held."""
    try:
        configurable = agent_configurable(config)
        thread_id = configurable.get("thread_id")
        if not thread_id or not redis_cache.client:
            return state

        messages = state.get("messages", [])
        # Skip during result narration. When comms is silently re-voicing a finished
        # executor result (the trigger is a HumanMessage named BACKGROUND_EXECUTOR_NAME),
        # that task's busy lock is still held — the runner frees it just AFTER delivery.
        # Injecting "STILL RUNNING" here contradicts the very result being delivered,
        # which can make the model return an empty narration that then falls back to
        # the raw executor text leaking to the user.
        if messages and messages[-1].name == BACKGROUND_EXECUTOR_NAME:
            return state

        raw = await redis_cache.client.get(f"{EXECUTOR_BUSY_PREFIX}{thread_id}")
        if raw is None:
            return state

        _, task_id = parse_lock_value(decode_raw_item(raw))
        status = SystemMessage(
            content=(
                "A background task you dispatched in this conversation is STILL "
                f"RUNNING right now (task_id: {task_id or 'unknown'}). Its results "
                "have not arrived yet — do not claim it finished, and do not "
                "dispatch the same task again. If the user asks about it, tell "
                "them it's in progress."
            ),
            additional_kwargs={EXECUTOR_STATUS_MARKER: True},
        )
        return cast(State, {**state, "messages": [*messages, status]})
    except Exception as e:  # a status frame must never break the turn
        log.error(f"{LogTag.AGENT} executor_status_hook failed", error_type=type(e).__name__)
        return state
