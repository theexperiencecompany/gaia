"""A user's quiet hours: when they end, and the class of a message that broke through them."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import time_machine

from app.constants.notifications import ProactiveMessageClass
from app.models.quiet_hours_models import QuietHours
from app.models.user_models import UserDocument
from app.services.quiet_hours import message_class, quiet_hours_end


@pytest.fixture
def owner() -> Iterator[AsyncMock]:
    user = UserDocument(
        id="user-1",
        timezone="Asia/Kolkata",
        quiet_hours=QuietHours(enabled=True, start_hour=17, end_hour=19),
    )
    with patch("app.services.quiet_hours.user_repository.get", AsyncMock(return_value=user)) as get:
        yield get


class TestQuietHoursEnd:
    async def test_inside_the_users_own_window_it_is_when_that_window_ends(
        self, owner: AsyncMock
    ) -> None:
        # 12:00 UTC is 17:30 in Kolkata, inside their 17-19 window, which ends 13:30 UTC.
        with time_machine.travel(datetime(2026, 10, 14, 12, 0, tzinfo=UTC), tick=False):
            end = await quiet_hours_end("user-1")

        assert end == datetime(2026, 10, 14, 13, 30, tzinfo=UTC)
        owner.assert_awaited_once_with("user-1")

    async def test_outside_the_window_there_is_nothing_to_wait_for(self, owner: AsyncMock) -> None:
        with time_machine.travel(datetime(2026, 10, 14, 6, 0, tzinfo=UTC), tick=False):
            end = await quiet_hours_end("user-1")

        assert end is None


@pytest.mark.parametrize(
    ("broke_through", "expected"),
    [(True, ProactiveMessageClass.URGENT), (False, ProactiveMessageClass.ROUTINE)],
)
def test_only_a_message_that_broke_through_quiet_hours_is_urgent(
    broke_through: bool, expected: ProactiveMessageClass
) -> None:
    assert message_class(broke_through) is expected
