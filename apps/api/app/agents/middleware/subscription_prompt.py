"""Prompt a todo-bound run to watch what it just started.

When a tracked todo sends an email or books a meeting, the thing it is now
waiting for has an identifier that only exists in the response it just got back.
This middleware notices that moment and appends an instruction to the tool
result, so the model subscribes the todo before moving on.

It creates nothing itself. Whether an outbound message deserves watching is a
judgement — a "thanks, got it" needs no reply-watcher — and which action and
cooldown to use is context only the model has. Arming it here would have to guess
all three, and a wrong guess leaves a junk subscription that fires the todo on
the wrong event. Routing through the ordinary tool instead keeps one creation
path, one validator, and a subscription that appears in the transcript as a
visible call rather than a side effect nobody can see.

The trade is that the model can decline or forget. That is the honest failure
mode: it fails visibly (no tool call in the run) rather than silently (a watch
armed on the wrong thing).

Composio's own ``after_execute`` hooks cannot do this — they are synchronous
``(tool, toolkit, response)`` functions registered at toolkit-load time, with no
request context, so they never learn which todo a run is bound to.
"""

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from shared.py.wide_events import log

# Tools whose success starts something a todo can wait on, and the identifier the
# model should carry into the subscription. Named here rather than inline so the
# set is one list to audit when a provider adds a send tool.
WATCHABLE_SENDS: dict[str, str] = {
    "GMAIL_SEND_EMAIL": "thread_id",
    "GMAIL_REPLY_TO_THREAD": "thread_id",
    "GMAIL_SEND_DRAFT": "thread_id",
    "GOOGLECALENDAR_CREATE_EVENT": "event_id",
    "SLACK_SEND_MESSAGE": "channel",
}

_EXECUTOR_INSTRUCTION = (
    "\n\n[GAIA] That was sent on behalf of tracked todo {todo_id}. If its outcome is "
    "something the todo is now waiting on, call subscribe_todo_to_trigger for that "
    "todo using the {identifier} from this response, so it wakes itself when the "
    "event lands. Skip this if nothing is expected back."
)

_SUBAGENT_INSTRUCTION = (
    "\n\n[GAIA] That was sent on behalf of tracked todo {todo_id}. You cannot "
    "subscribe from here, so include the {identifier} from this response in your "
    "finish_task result and say what the todo is waiting for, so the executor can "
    "set the watch up."
)


class SubscriptionPromptMiddleware(AgentMiddleware):
    """Appends a subscribe instruction after a watchable send in a todo-bound run.

    ``can_subscribe`` is False for provider subagents: their tool set is scoped to
    one integration plus a fixed helper set, so ``subscribe_todo_to_trigger`` is
    not bound there and telling them to call it would be an instruction they
    cannot follow. They are asked to report the identifier upward instead.
    """

    def __init__(self, *, can_subscribe: bool = True) -> None:
        super().__init__()
        self._can_subscribe = can_subscribe

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result

        identifier = WATCHABLE_SENDS.get(request.tool_call.get("name", ""))
        if identifier is None:
            return result

        config = cast(RunnableConfig, getattr(request.runtime, "config", {}) or {})
        todo_id = (config.get("configurable") or {}).get("active_todo_id")
        if not todo_id:
            # An ordinary conversational send, bound to no todo. Nothing to watch.
            return result

        template = _EXECUTOR_INSTRUCTION if self._can_subscribe else _SUBAGENT_INSTRUCTION
        log.info(
            "todo_subscription.prompted",
            todo_id=todo_id,
            tool=request.tool_call.get("name"),
            can_subscribe=self._can_subscribe,
        )
        return _append(result, template.format(todo_id=todo_id, identifier=identifier))


def _append(message: ToolMessage, suffix: str) -> ToolMessage:
    """Add ``suffix`` to a tool result, whichever content shape it carries."""
    if isinstance(message.content, str):
        return message.model_copy(update={"content": message.content + suffix})
    # Block content (media, structured parts): append a text block rather than
    # stringifying the whole thing, which would destroy the blocks.
    blocks = [*message.content, {"type": "text", "text": suffix}]
    return message.model_copy(update={"content": blocks})
