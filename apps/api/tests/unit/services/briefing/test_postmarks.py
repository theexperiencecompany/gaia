"""Postmarks: a user's collected Air Mail stamps, built from their stamped briefs.

The repository is faked; the real stamp catalogue (cities.json) is read.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.briefing_models import BriefingModel, BriefingPayload, Postmark
from app.services.briefing.postmarks import collected_postmarks

MODULE = "app.services.briefing.postmarks"
USER_ID = "user-1"


def _brief(brief_id: str, date: str, stamp_city: str) -> BriefingModel:
    return BriefingModel(
        id=brief_id,
        user_id=USER_ID,
        date=date,
        payload=BriefingPayload(
            kicker="AIR MAIL",
            date=date,
            headline="Postcard",
            lede="From afar.",
            mood="clear",
            caption="Onward.",
            template_family="postal",
            stamp_city=stamp_city,
        ),
    )


async def test_each_city_counts_once_on_the_day_it_first_arrived() -> None:
    briefs = [
        _brief("brief_1", "2026-09-01", "tokyo"),
        _brief("brief_3", "2026-09-02", "tokyo"),
        _brief("brief_2", "2026-09-04", "lima"),
    ]
    with patch(
        f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=briefs)
    ) as list_stamped:
        result = await collected_postmarks(USER_ID)

    list_stamped.assert_awaited_once_with(USER_ID)
    assert result.total == 85
    assert result.postmarks == [
        Postmark(
            city_slug="tokyo",
            city="Tokyo",
            country="Japan",
            lat=35.68,
            lng=139.69,
            stamp_url="https://res.cloudinary.com/dwhuiazdn/image/upload/briefing/stamps/tokyo.webp",
            date="2026-09-01",
            briefing_id="brief_1",
        ),
        Postmark(
            city_slug="lima",
            city="Lima",
            country="Peru",
            lat=-12.05,
            lng=-77.04,
            stamp_url="https://res.cloudinary.com/dwhuiazdn/image/upload/briefing/stamps/lima.webp",
            date="2026-09-04",
            briefing_id="brief_2",
        ),
    ]


async def test_no_stamped_briefs_is_an_empty_collection_of_the_full_set() -> None:
    with patch(f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=[])):
        result = await collected_postmarks(USER_ID)

    assert (result.total, result.postmarks) == (85, [])


async def test_a_stamp_city_missing_from_the_catalogue_fails_loudly() -> None:
    with (
        patch(
            f"{MODULE}.briefing_repository.list_stamped",
            AsyncMock(return_value=[_brief("brief_1", "2026-09-01", "atlantis")]),
        ),
        pytest.raises(KeyError, match="atlantis"),
    ):
        await collected_postmarks(USER_ID)
