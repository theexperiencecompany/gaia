"""Unit tests for app.services.outbox.dormancy: when a user counts as having gone away."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.outbox_attention import DORMANT_AFTER_SECONDS
from app.services.outbox.dormancy import is_dormant

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
WINDOW = timedelta(seconds=DORMANT_AFTER_SECONDS)
HAS_MESSAGE = "app.services.outbox.dormancy.conversation_repository.has_user_message_since"


@pytest.mark.unit
class TestIsDormant:
    async def test_a_new_account_with_no_presence_or_messages_is_not_dormant(self):
        with patch(HAS_MESSAGE, AsyncMock(return_value=False)):
            assert not await is_dormant("u1", None, NOW - timedelta(hours=1), NOW)

    async def test_an_old_account_with_no_presence_or_messages_is_dormant(self):
        with patch(HAS_MESSAGE, AsyncMock(return_value=False)):
            assert await is_dormant("u1", None, NOW - WINDOW - timedelta(days=1), NOW)

    async def test_an_account_older_than_the_window_whose_presence_is_recent_is_not_dormant(self):
        seen = int((NOW - timedelta(days=1)).timestamp())
        with patch(HAS_MESSAGE, AsyncMock(return_value=False)):
            assert not await is_dormant("u1", seen, NOW - WINDOW * 3, NOW)

    async def test_an_account_with_no_recorded_creation_is_judged_on_activity_alone(self):
        with patch(HAS_MESSAGE, AsyncMock(return_value=False)):
            assert await is_dormant("u1", None, None, NOW)
