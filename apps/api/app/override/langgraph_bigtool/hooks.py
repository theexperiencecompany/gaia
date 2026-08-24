"""
Hook execution utilities for LangGraph agents.

Provides sync and async hook execution for pre_model, end_graph, etc.
"""

import asyncio
from collections.abc import Awaitable, Callable
import inspect
from typing import Union, cast

from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.override.langgraph_bigtool.utils import State

HookType = Union[
    Callable[[State, RunnableConfig, BaseStore], State],
    Callable[[State, RunnableConfig, BaseStore], Awaitable[State]],
]


async def execute_hooks(
    hooks: list[HookType] | None,
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """Execute hooks sequentially, handling both sync and async hooks.

    Args:
        hooks: List of hook functions to execute
        state: Current agent state
        config: Runnable configuration
        store: LangGraph store instance

    Returns:
        Updated state after all hooks have executed
    """
    if not hooks:
        return state

    for hook in hooks:
        result = hook(state, config, store)
        if inspect.iscoroutine(result):
            state = await result
        else:
            state = result  # type: ignore[assignment]  # inspect.iscoroutine() can't narrow HookType union; sync branch yields State
    return state


def changed_hook_keys(before: State, after: State) -> State:
    """Keys the hook chain changed (by identity) — echoing unchanged channels
    re-serializes the full message list into the checkpoint on every run."""
    if after is before:
        return cast("State", {})
    before_dict = cast("dict[str, object]", before)
    return cast(
        "State",
        {
            key: value
            for key, value in after.items()
            if key not in before_dict or before_dict[key] is not value
        },
    )


def sync_execute_hooks(
    hooks: list[HookType] | None,
    state: State,
    config: RunnableConfig,
    store: BaseStore,
) -> State:
    """Execute hooks in a sync context by running an event loop.

    Args:
        hooks: List of hook functions to execute
        state: Current agent state
        config: Runnable configuration
        store: LangGraph store instance

    Returns:
        Updated state after all hooks have executed
    """
    if not hooks:
        return state

    async def _run_with_hooks() -> State:
        return await execute_hooks(hooks, state, config, store)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        state = loop.run_until_complete(_run_with_hooks())
    finally:
        loop.close()

    return state
