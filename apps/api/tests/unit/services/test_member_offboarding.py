"""Unit tests for app.services.member_offboarding — nothing runs for a removed member."""

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.briefing import DAILY_BRIEFING_WORKFLOW_KEY, WEEKLY_DIGEST_WORKFLOW_KEY
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import TodoUpdate
from app.services.member_offboarding import stop_acting_for_removed_member
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

_MOD = "app.services.member_offboarding"
USER = "member-1"


@dataclass
class Seams:
    deactivate_workflow: AsyncMock
    pause_reminder: AsyncMock
    update_todo: AsyncMock
    disconnect_platform: AsyncMock
    revoke_links: AsyncMock
    finders: tuple[AsyncMock, ...]


@pytest.fixture
def seams() -> Iterator[Seams]:
    owned = [
        SimpleNamespace(id="wf-user", activated=True, system_workflow_key=None),
        SimpleNamespace(
            id="wf-system", activated=True, system_workflow_key="calendar:meeting_prep"
        ),
        SimpleNamespace(
            id="wf-daily", activated=True, system_workflow_key=DAILY_BRIEFING_WORKFLOW_KEY
        ),
        SimpleNamespace(
            id="wf-weekly", activated=False, system_workflow_key=WEEKLY_DIGEST_WORKFLOW_KEY
        ),
    ]

    async def activated(user_id: str, *, excluding_keys: Collection[str]) -> list[SimpleNamespace]:
        return [w for w in owned if w.activated and w.system_workflow_key not in excluding_keys]

    reminders = [SimpleNamespace(id="rem-1")]
    todos = [SimpleNamespace(id="todo-1")]
    with (
        patch(
            f"{_MOD}.workflow_repository.find_activated_for_user",
            new_callable=AsyncMock,
            side_effect=activated,
        ) as find_workflows,
        patch(f"{_MOD}.revoke_all_links_for_user", new_callable=AsyncMock) as revoke_links,
        patch(f"{_MOD}.WorkflowService.deactivate_workflow", new_callable=AsyncMock) as deactivate,
        patch(
            f"{_MOD}.reminder_repository.find_scheduled_for_user",
            new_callable=AsyncMock,
            return_value=reminders,
        ) as find_reminders,
        patch(f"{_MOD}.reminder_scheduler.pause_for_reason", new_callable=AsyncMock) as pause,
        patch(
            f"{_MOD}.todo_repository.find_running_tracked_for_user",
            new_callable=AsyncMock,
            return_value=todos,
        ) as find_todos,
        patch(f"{_MOD}.todo_repository.update", new_callable=AsyncMock) as update_todo,
        patch(
            f"{_MOD}.PlatformLinkService.get_linked_platforms",
            new_callable=AsyncMock,
            return_value={"telegram": {"platformUserId": "t-1"}, "discord": {}},
        ) as find_platforms,
        patch(f"{_MOD}.disconnect_platform_account", new_callable=AsyncMock) as disconnect,
    ):
        yield Seams(
            deactivate,
            pause,
            update_todo,
            disconnect,
            revoke_links,
            (find_workflows, find_reminders, find_todos, find_platforms),
        )


@pytest.mark.unit
class TestStopActingForRemovedMember:
    async def test_every_activated_workflow_is_deactivated_as_member_removed(
        self, seams: Seams
    ) -> None:
        await stop_acting_for_removed_member(USER)

        assert [c.args for c in seams.deactivate_workflow.await_args_list] == [
            ("wf-user", USER),
            ("wf-system", USER),
            ("wf-daily", USER),
        ]
        assert all(
            c.kwargs == {"reason": DeactivationReason.MEMBER_REMOVED}
            for c in seams.deactivate_workflow.await_args_list
        )

    async def test_a_running_brief_is_stopped_too(self, seams: Seams) -> None:
        await stop_acting_for_removed_member(USER)

        stopped = [c.args[0] for c in seams.deactivate_workflow.await_args_list]
        assert "wf-daily" in stopped
        assert "wf-weekly" not in stopped

    async def test_every_link_they_shared_stops_opening(self, seams: Seams) -> None:
        await stop_acting_for_removed_member(USER)

        seams.revoke_links.assert_awaited_once_with(USER)

    async def test_links_that_would_not_revoke_are_named_in_the_error(self, seams: Seams) -> None:
        seams.revoke_links.side_effect = RuntimeError("mongo down")

        with pytest.raises(AppError) as raised:
            await stop_acting_for_removed_member(USER)

        assert raised.value.why == "Could not stop: links"

    async def test_scheduled_reminders_and_tracked_todos_are_paused(self, seams: Seams) -> None:
        await stop_acting_for_removed_member(USER)

        (reminder, reason), _ = seams.pause_reminder.await_args
        assert reminder.id == "rem-1"
        assert reason is DeactivationReason.MEMBER_REMOVED
        seams.update_todo.assert_awaited_once_with(
            "todo-1",
            user_id=USER,
            update=TodoUpdate(pause_reason=DeactivationReason.MEMBER_REMOVED),
        )

    async def test_every_bot_platform_is_unlinked(self, seams: Seams) -> None:
        await stop_acting_for_removed_member(USER)

        assert [c.args for c in seams.disconnect_platform.await_args_list] == [
            (USER, "telegram"),
            (USER, "discord"),
        ]

    async def test_one_failure_stops_nothing_else_and_is_raised_at_the_end(
        self, seams: Seams
    ) -> None:
        seams.deactivate_workflow.side_effect = [RuntimeError("composio down"), None, None]

        with pytest.raises(AppError) as raised:
            await stop_acting_for_removed_member(USER)

        assert raised.value.status_code == 503
        assert raised.value.meta == {"user_id": USER, "failed": ["workflow:wf-user"]}
        assert seams.deactivate_workflow.await_count == 3
        seams.pause_reminder.assert_awaited_once()
        seams.update_todo.assert_awaited_once()
        assert seams.disconnect_platform.await_count == 2

    async def test_only_the_removed_members_own_items_are_looked_up(self, seams: Seams) -> None:
        await stop_acting_for_removed_member(USER)

        for finder in seams.finders:
            finder.assert_awaited_once()
            assert finder.await_args.args == (USER,)

    async def test_a_clean_stop_counts_every_item(self, seams: Seams) -> None:
        async with captured_wide_event() as event:
            await stop_acting_for_removed_member(USER)

        assert event["member_offboarding"] == {"stopped": 8, "failed": 0}

    async def test_what_could_not_stop_is_warned_counted_and_named_in_the_error(
        self, seams: Seams
    ) -> None:
        seams.deactivate_workflow.side_effect = [RuntimeError("composio down"), None, None]
        seams.disconnect_platform.side_effect = [None, ConnectionError("discord down")]

        async with captured_wide_event() as event:
            with pytest.raises(AppError) as raised:
                await stop_acting_for_removed_member(USER)

        error = raised.value
        assert error.code == "member_offboarding_incomplete"
        assert error.message == (
            "The member was removed, but some of their automation is still running"
        )
        assert error.why == "Could not stop: workflow:wf-user, platform:discord"
        assert (
            error.fix == "Remove the member again; each removal retries whatever is still running"
        )
        assert event["member_offboarding"] == {"stopped": 6, "failed": 2}
        assert event["warnings"] == [
            {
                "msg": "[members] could not stop an item for a removed member",
                "user_id": USER,
                "item": item,
                "error": message,
                "error_type": kind,
            }
            for item, message, kind in (
                ("workflow:wf-user", "composio down", "RuntimeError"),
                ("platform:discord", "discord down", "ConnectionError"),
            )
        ]
