"""Prompting a todo-bound run to watch what it just sent.

The two tiers matter. A Gmail send runs inside a provider subagent, whose tool
set is scoped to its integration — ``subscribe_todo_to_trigger`` is not bound
there, so telling it to call the tool would be an instruction it cannot follow
and the watch would never be armed. It is asked to report the identifier upward
instead.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import ToolMessage
import pytest

from app.agents.middleware.factory import (
    create_middleware_stack,
    create_subagent_middleware,
)
from app.agents.middleware.subscription_prompt import (
    WATCHABLE_SENDS,
    SubscriptionPromptMiddleware,
)

pytestmark = pytest.mark.unit

TODO_ID = "todo-1"
SENT = "Sent. thread_id=18c9f0a1"


def _request(tool: str, *, todo_id: str | None = TODO_ID) -> SimpleNamespace:
    configurable = {"user_id": "user-1"}
    if todo_id:
        configurable["active_todo_id"] = todo_id
    return SimpleNamespace(
        tool_call={"name": tool, "args": {}, "id": "call-1"},
        runtime=SimpleNamespace(config={"configurable": configurable}),
    )


def _handler(message: ToolMessage) -> AsyncMock:
    return AsyncMock(return_value=message)


def _result(content: object = SENT, *, status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call-1", status=status)


class TestExecutorTier:
    async def test_a_send_from_a_todo_bound_run_is_told_to_subscribe(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(_request("GMAIL_SEND_EMAIL"), _handler(_result()))

        assert SENT in out.content
        assert "subscribe_todo_to_trigger" in out.content
        assert TODO_ID in out.content
        assert "thread_id" in out.content

    async def test_a_calendar_event_is_told_to_watch_the_event_id(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(
            _request("GOOGLECALENDAR_CREATE_EVENT"), _handler(_result())
        )

        assert "event_id" in out.content

    @pytest.mark.parametrize("tool", sorted(WATCHABLE_SENDS))
    async def test_every_watchable_send_prompts(self, tool: str) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(_request(tool), _handler(_result()))

        assert "[GAIA]" in out.content


class TestSubagentTier:
    async def test_it_is_asked_to_report_upward_not_to_call_a_tool_it_lacks(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=False)

        out = await middleware.awrap_tool_call(_request("GMAIL_SEND_EMAIL"), _handler(_result()))

        assert "finish_task" in out.content
        assert "subscribe_todo_to_trigger" not in out.content
        assert "thread_id" in out.content


class TestWhenItStaysOutOfTheWay:
    async def test_a_send_with_no_active_todo_is_untouched(self) -> None:
        # An ordinary conversational email. Arming a watch here is the failure
        # the active-todo gate exists to prevent.
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(
            _request("GMAIL_SEND_EMAIL", todo_id=None), _handler(_result())
        )

        assert out.content == SENT

    async def test_a_failed_send_is_untouched(self) -> None:
        # Nothing was sent, so there is nothing to wait for.
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(
            _request("GMAIL_SEND_EMAIL"), _handler(_result("boom", status="error"))
        )

        assert out.content == "boom"

    async def test_an_unwatchable_tool_is_untouched(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)

        out = await middleware.awrap_tool_call(_request("GMAIL_FETCH_EMAILS"), _handler(_result()))

        assert out.content == SENT

    async def test_a_non_tool_message_result_passes_through(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)
        command = object()

        out = await middleware.awrap_tool_call(
            _request("GMAIL_SEND_EMAIL"), AsyncMock(return_value=command)
        )

        assert out is command

    async def test_a_missing_config_does_not_raise(self) -> None:
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)
        request = SimpleNamespace(
            tool_call={"name": "GMAIL_SEND_EMAIL", "args": {}, "id": "call-1"},
            runtime=SimpleNamespace(config=None),
        )

        out = await middleware.awrap_tool_call(request, _handler(_result()))

        assert out.content == SENT


class TestBlockContent:
    async def test_block_content_gains_a_text_block_rather_than_being_flattened(self) -> None:
        # Stringifying block content to append would destroy the blocks.
        middleware = SubscriptionPromptMiddleware(can_subscribe=True)
        blocks = [{"type": "text", "text": SENT}]

        out = await middleware.awrap_tool_call(
            _request("GMAIL_SEND_EMAIL"), _handler(_result(blocks))
        )

        assert isinstance(out.content, list)
        assert out.content[0] == blocks[0]
        assert "subscribe_todo_to_trigger" in out.content[-1]["text"]


class TestItIsActuallyWiredIn:
    """A middleware nobody builds into a stack is a middleware that never runs."""

    @staticmethod
    def _find(stack) -> SubscriptionPromptMiddleware | None:
        return next(
            (mw for mw in stack if isinstance(mw, SubscriptionPromptMiddleware)), None
        )

    def test_the_executor_stack_can_subscribe(self) -> None:
        found = self._find(create_middleware_stack(agent_name="executor_agent"))

        assert found is not None
        assert found._can_subscribe is True

    def test_the_provider_subagent_stack_cannot(self) -> None:
        # Its tools are scoped to one integration, so the subscribe tool is absent.
        found = self._find(create_subagent_middleware(enable_subagent=False))

        assert found is not None
        assert found._can_subscribe is False
