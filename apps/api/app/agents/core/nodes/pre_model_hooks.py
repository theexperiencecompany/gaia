"""The pre-model hook chains every agent tier runs before each LLM call.

Declared here rather than inline at each graph builder so there is one answer to
"what rewrites the message array before the model sees it" — the ordering is
load-bearing (``manage_system_prompts_node`` must run last so it slots whatever
the earlier hooks appended into the leading system block) and it was previously
spelled out at three separate call sites.
"""

from typing import cast

from app.agents.core.background.executor_channel import drain_inbox_hook
from app.agents.core.background.subagent_channel import drain_subagent_inbox_hook
from app.agents.core.nodes.adapt_media import adapt_media_node
from app.agents.core.nodes.executor_status import executor_status_hook
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.override.langgraph_bigtool.hooks import HookType


def comms_pre_model_hooks() -> list[HookType]:
    """Comms: no media adaptation (it holds no media-producing tools), plus the
    live-executor status frame — which must precede ``manage_system_prompts_node``
    so the frame lands inside the system block rather than trailing it."""
    return [
        cast(HookType, filter_messages_node),
        executor_status_hook,
        manage_system_prompts_node,
    ]


def worker_pre_model_hooks(
    todo_hook: HookType | None = None,
    *,
    drains_inbox: bool = False,
    drains_subagent_inbox: bool = False,
) -> list[HookType]:
    """Executor, provider subagents and spawned subagents.

    ``todo_hook`` is ``None`` for spawn (no todo channel) and for authoring-only
    subagents, which must not plan or execute tasks. Like the comms status frame
    it runs BEFORE ``manage_system_prompts_node``, so the message it appends is
    placed by the canonical slot order rather than by its own insert position —
    which otherwise varied with whichever other slots the turn happened to fill.

    Two independent drain channels, and a tier gets at most one:

    - ``drains_inbox`` is the EXECUTOR only — the conversation inbox the user
      steers into. A subagent must not absorb it: work the user addressed to the
      executor would be answered out of a subagent's narrow scope and the
      executor would never learn the user had spoken.
    - ``drains_subagent_inbox`` is a SUBAGENT only — its own mailbox, which only
      the executor writes to (via ``message_subagent``). It carries steers the
      executor deliberately routed to *this* subagent, so the executor stays the
      sole router and nothing is broadcast.
    """
    return [
        cast(HookType, filter_messages_node),
        cast(HookType, adapt_media_node),
        *([todo_hook] if todo_hook is not None else []),
        *([cast(HookType, drain_inbox_hook)] if drains_inbox else []),
        *([cast(HookType, drain_subagent_inbox_hook)] if drains_subagent_inbox else []),
        manage_system_prompts_node,
    ]
