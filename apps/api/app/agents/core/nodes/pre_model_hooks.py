"""The pre-model hook chains every agent tier runs before each LLM call.

Declared here rather than inline at each graph builder so there is one answer to
"what rewrites the message array before the model sees it" — the ordering is
load-bearing (manage_system_prompts_node must run last so the request it builds
is the one the model sees) and it was previously spelled out at three separate
call sites. No hook adds per-call context: what a turn needs is written into the
thread when the turn starts, so each request extends the previous one.
"""

from typing import cast

from app.agents.core.background.executor_channel import drain_inbox_hook
from app.agents.core.background.subagent_channel import drain_subagent_inbox_hook
from app.agents.core.nodes.adapt_media import adapt_media_node
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.hooks import HookType


def comms_pre_model_hooks() -> list[HookType]:
    """Comms: no media adaptation; its live-work status rides the turn context."""
    return [cast(HookType, filter_messages_node), manage_system_prompts_node]


def worker_pre_model_hooks(
    *,
    drains_inbox: bool = False,
    drains_subagent_inbox: bool = False,
) -> list[HookType]:
    """Executor, the workflow authoring subagent and spawned subagents.

    drains_inbox is executor-only, drains_subagent_inbox is subagent-only; a
    tier gets at most one. A drained message is committed to the thread by the
    model node, so the next request still begins with this one.
    """
    return [
        cast(HookType, filter_messages_node),
        cast(HookType, adapt_media_node),
        *([cast(HookType, drain_inbox_hook)] if drains_inbox else []),
        *([cast(HookType, drain_subagent_inbox_hook)] if drains_subagent_inbox else []),
        manage_system_prompts_node,
    ]
