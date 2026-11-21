"""Unit tests for tracked_todo recurrence + timezone resolution.

Covers the recently-refactored timezone code paths in
app.workers.tasks.tracked_todo_tasks:

- _load_user_with_tz resolves the user's home zone via Timezone.parse
  and falls back to Timezone.utc() on a missing user or exception.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import AuthenticatedUser
from app.utils import auth_utils
from app.utils.timezone import Timezone
from app.workers.tasks.tracked_todo_tasks import _load_user_with_tz


def _user_context(*, timezone: str | None) -> Callable[[str], AuthenticatedUser]:
    """Build the user load_user_context returns for whichever user id it is asked for."""
    return lambda user_id: AuthenticatedUser(user_id=user_id, timezone=timezone)


LOAD_USER = "app.utils.auth_utils.load_user_context"


# ---------------------------------------------------------------------------
# _load_user_with_tz
# ---------------------------------------------------------------------------


class TestLoadUserWithTz:
    async def test_offset_timezone_resolved(self):
        with patch(LOAD_USER, new=AsyncMock(side_effect=_user_context(timezone="+05:30"))):
            user_data, tz = await _load_user_with_tz("user1")

        assert isinstance(tz, Timezone)
        assert tz.value == "+05:30"
        assert user_data.user_id == "user1"

    async def test_iana_timezone_resolved(self):
        with patch(LOAD_USER, new=AsyncMock(side_effect=_user_context(timezone="Asia/Kolkata"))):
            _user_data, tz = await _load_user_with_tz("user1")

        assert tz.value == "Asia/Kolkata"

    async def test_missing_timezone_falls_back_to_utc(self):
        with patch(LOAD_USER, new=AsyncMock(side_effect=_user_context(timezone=None))):
            user_data, tz = await _load_user_with_tz("user1")

        assert tz.value == "UTC"
        assert user_data.user_id == "user1"

    @pytest.mark.regression
    async def test_a_missing_owner_is_refused_not_fabricated(self):
        with (
            patch(LOAD_USER, new=AsyncMock(return_value=None)),
            pytest.raises(auth_utils.OwnerNotFoundError),
        ):
            await _load_user_with_tz("user1")

    @pytest.mark.regression
    async def test_a_failed_load_propagates(self):
        with (
            patch(LOAD_USER, new=AsyncMock(side_effect=RuntimeError("DB down"))),
            pytest.raises(RuntimeError, match="DB down"),
        ):
            await _load_user_with_tz("user1")
