"""get_profile_timezone: the one place a user's home timezone is read from their profile.

It replaced three resolvers (the trigger gate's, memory's and agent config's); each case
below is one of those callers' inputs.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories.users import user_repository
from app.services import user_service
from app.utils.timezone import Timezone

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"


def _profile(timezone: str | None) -> AsyncMock:
    return AsyncMock(return_value=SimpleNamespace(timezone=timezone))


class TestGetProfileTimezone:
    @pytest.mark.parametrize(
        ("stored", "expected"),
        [
            ("Asia/Kolkata", "Asia/Kolkata"),
            ("+05:30", "+05:30"),
            ("UTC", "UTC"),
            (None, "UTC"),
            ("", "UTC"),
            ("Not/AZone", "UTC"),
        ],
    )
    async def test_the_stored_zone_or_utc(self, stored: str | None, expected: str) -> None:
        with patch.object(user_repository, "get", _profile(stored)):
            tz = await user_service.get_profile_timezone(USER_ID)

        assert tz == Timezone.parse(expected)

    async def test_a_user_with_no_profile_is_utc(self) -> None:
        with patch.object(user_repository, "get", AsyncMock(return_value=None)):
            assert (await user_service.get_profile_timezone(USER_ID)).is_utc

    async def test_an_id_that_cannot_name_a_profile_is_utc_without_a_read(self) -> None:
        read = _profile("Asia/Kolkata")
        with patch.object(user_repository, "get", read):
            tz = await user_service.get_profile_timezone("test-mem-notanobjectid")

        assert tz.is_utc
        read.assert_not_awaited()

    async def test_a_failed_profile_read_propagates_instead_of_becoming_utc(self) -> None:
        down = AsyncMock(side_effect=ConnectionError("mongo down"))
        with (
            patch.object(user_repository, "get", down),
            pytest.raises(ConnectionError, match="mongo down"),
        ):
            await user_service.get_profile_timezone(USER_ID)
