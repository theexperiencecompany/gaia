"""Unit tests for the trigger-subscription dispatch ARQ task.

The task fans one fired trigger out to every subscribed todo and task. It resolves each
GAIA trigger name independently for todos (a handler can own several), so the names run
concurrently and one failing consumer must neither cancel nor strand the others.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.trigger_dispatch_tasks import dispatch_to_subscribers
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_MOD = "app.workers.tasks.trigger_dispatch_tasks"

_ArgTuple = tuple[str, str | None, str | None, dict[str, Any]]


@pytest.fixture(autouse=True)
def task_dispatch() -> Iterator[AsyncMock]:
    with patch(f"{_MOD}.dispatch_event_to_tasks", AsyncMock(return_value=0)) as dispatch:
        yield dispatch


class TestDispatchToSubscribers:
    async def test_the_tasks_get_the_event_once_with_its_occurrence(
        self, task_dispatch: AsyncMock
    ) -> None:
        task_dispatch.return_value = 1
        payload = {"id": "evt_9"}

        with patch(f"{_MOD}.dispatch_to_subscribed_todos", AsyncMock(return_value=0)):
            result = await dispatch_to_subscribers(
                {}, ["gmail_new_message", "gmail_poll_inbox"], "ti_1", "user-1", payload, "occ-1"
            )

        assert result == "fired:1"
        task_dispatch.assert_awaited_once_with(
            ["gmail_new_message", "gmail_poll_inbox"],
            "ti_1",
            "user-1",
            payload,
            occurrence="occ-1",
        )

    async def test_each_name_is_dispatched_with_the_full_unaltered_arg_tuple(self) -> None:
        # Exact four-positional signature: captures (trigger_name, trigger_id,
        # user_id, payload) verbatim, so a nulled, dropped, or reordered
        # argument either changes the recorded tuple or raises before recording.
        calls: list[_ArgTuple] = []
        payload = {"event": "gmail.new", "id": "evt_9"}

        async def fake_dispatch(
            trigger_name: str,
            trigger_id: str | None,
            user_id: str | None,
            payload_arg: dict[str, Any],
        ) -> int:
            calls.append((trigger_name, trigger_id, user_id, payload_arg))
            return {"gmail_new_message": 2, "gmail_poll_inbox": 1}[trigger_name]

        with patch(f"{_MOD}.dispatch_to_subscribed_todos", new=fake_dispatch):
            result = await dispatch_to_subscribers(
                {}, ["gmail_new_message", "gmail_poll_inbox"], "ti_1", "user-1", payload
            )

        assert result == "fired:3"
        assert calls == [
            ("gmail_new_message", "ti_1", "user-1", payload),
            ("gmail_poll_inbox", "ti_1", "user-1", payload),
        ]

    async def test_a_failing_name_is_isolated_and_logged_without_stranding_the_rest(self) -> None:
        async def fake_dispatch(trigger_name: str, *_: object) -> int:
            if trigger_name == "boom":
                raise RuntimeError("kaboom")
            return 2

        with patch(f"{_MOD}.dispatch_to_subscribed_todos", new=fake_dispatch):
            async with captured_wide_event() as event:
                result = await dispatch_to_subscribers(
                    {}, ["gmail_new_message", "boom", "slack_new_message"], "ti_1", "user-1", {}
                )

        # Both healthy names still fired (2 each); the raising one is excluded.
        assert result == "fired:4"
        (error,) = event["errors"]
        assert error["msg"] == "subscriber_dispatch.failed"
        assert error["consumer"] == "boom"
        assert error["trigger_id"] == "ti_1"
        assert error["error"] == "kaboom"
        assert error["error_type"] == "RuntimeError"

    async def test_the_dispatch_context_is_stamped_on_the_wide_event(self) -> None:
        async def fake_dispatch(*_: object) -> int:
            return 0

        with patch(f"{_MOD}.dispatch_to_subscribed_todos", new=fake_dispatch):
            async with captured_wide_event() as event:
                await dispatch_to_subscribers({}, ["gmail_new_message"], "ti_1", "user-1", {})

        assert event["component"] == "trigger_subscription"
        assert event["operation"] == "dispatch"
        assert event["trigger_id"] == "ti_1"
        assert event["user_id"] == "user-1"
        assert event["trigger_names"] == ["gmail_new_message"]
