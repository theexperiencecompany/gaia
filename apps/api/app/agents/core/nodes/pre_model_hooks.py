"""The pre-model hook chains every agent tier runs before each LLM call.

Declared here rather than inline at each graph builder so there is one answer to
"what rewrites the message array before the model sees it" — the ordering is
load-bearing (manage_system_prompts_node must run last so it slots whatever
the earlier hooks appended into the leading system block) and it was previously
spelled out at three separate call sites.
"""

from typing import cast

from app.agents.core.background.executor_channel import drain_inbox_hook
from app.agents.core.background.subagent_channel import drain_subagent_inbox_hook
from app.agents.core.nodes.adapt_media import adapt_media_node
from app.agents.core.nodes.browser_task_status import browser_task_status_hook
from app.agents.core.nodes.executor_status import executor_status_hook
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.hooks import HookType


def comms_pre_model_hooks() -> list[HookType]:
    """Comms: no media adaptation, plus the live-executor and browser-task status frames.

    Must precede manage_system_prompts_node so the frames land inside the
    system block rather than trailing it.
    """
    return [
        cast(HookType, filter_messages_node),
        executor_status_hook,
        browser_task_status_hook,
        manage_system_prompts_node,
    ]


def worker_pre_model_hooks(
    todo_hook: HookType | None = None,
    *,
    drains_inbox: bool = False,
    drains_subagent_inbox: bool = False,
) -> list[HookType]:
    """Executor, provider subagents and spawned subagents.

    todo_hook is None for spawn and authoring-only subagents. Runs BEFORE
    manage_system_prompts_node so appended messages take the canonical slot
    order. drains_inbox is executor-only, drains_subagent_inbox is
    subagent-only; a tier gets at most one.
    """
    return [
        cast(HookType, filter_messages_node),
        cast(HookType, adapt_media_node),
        *([todo_hook] if todo_hook is not None else []),
        *([cast(HookType, drain_inbox_hook)] if drains_inbox else []),
        *([cast(HookType, drain_subagent_inbox_hook)] if drains_subagent_inbox else []),
        manage_system_prompts_node,
    ]
