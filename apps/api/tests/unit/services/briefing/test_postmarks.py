"""Postmarks: a user's collected Air Mail stamps, built from their stamped briefs.

The repository is faked; the real stamp catalogue (cities.json) is read.
"""

from unittest.mock import AsyncMock, patch

from tests.helpers import captured_wide_event

from app.config.settings import settings
from app.models.briefing_models import (
    BriefingModel,
    BriefingMood,
    BriefingPayload,
    EditionImage,
    EditionRender,
    Postmark,
)
from app.services.briefing.postmarks import collected_postmarks

MODULE = "app.services.briefing.postmarks"
USER_ID = "user-1"
_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/"
_PAPER = [0.1, 0.05, 0.9, 0.95]


def _unsigned(postmark: Postmark) -> Postmark:
    """Cut each edition URL's signature, which changes with the day it is issued."""
    if postmark.edition is None:
        return postmark
    url = postmark.edition.image_url.split("?t=")[0] + "?t="
    return postmark.model_copy(
        update={"edition": postmark.edition.model_copy(update={"image_url": url})}
    )


def _brief(brief_id: str, date: str, stamp_city: str) -> BriefingModel:
    return BriefingModel(
        id=brief_id,
        user_id=USER_ID,
        date=date,
        edition=EditionRender(key=f"key-{brief_id}", fold=0.31, paper=[0.1, 0.05, 0.9, 0.95]),
        payload=BriefingPayload(
            kicker="AIR MAIL",
            date=date,
            headline="Postcard",
            lede="From afar.",
            mood=BriefingMood.CLEAR,
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
    assert [_unsigned(p) for p in result.postmarks] == [
        Postmark(
            city_slug="tokyo",
            city="Tokyo",
            country="Japan",
            lat=35.68,
            lng=139.69,
            stamp_url="https://res.cloudinary.com/dwhuiazdn/image/upload/briefing/stamps/tokyo.webp",
            date="2026-09-01",
            briefing_id="brief_1",
            edition=EditionImage(
                image_url=f"{_EDITION_URL}key-brief_1/png?t=", fold=0.31, paper=_PAPER
            ),
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
            edition=EditionImage(
                image_url=f"{_EDITION_URL}key-brief_2/png?t=", fold=0.31, paper=_PAPER
            ),
        ),
    ]


async def test_a_postmark_carries_its_briefs_edition_so_the_stamp_opens_without_fetching_it() -> (
    None
):
    briefs = [_brief("brief_1", "2026-09-01", "tokyo")]
    with patch(f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=briefs)):
        result = await collected_postmarks(USER_ID)

    [tokyo] = result.postmarks
    assert tokyo.edition is not None
    assert tokyo.edition.image_url.startswith(f"{_EDITION_URL}key-brief_1/png?t=")
    assert (tokyo.edition.fold, tokyo.edition.paper) == (0.31, _PAPER)


async def test_no_stamped_briefs_is_an_empty_collection_of_the_full_set() -> None:
    with patch(f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=[])):
        result = await collected_postmarks(USER_ID)

    assert (result.total, result.postmarks) == (85, [])


async def test_a_stamp_city_no_longer_in_the_catalogue_is_left_out_and_logged() -> None:
    briefs = [
        _brief("brief_1", "2026-09-01", "atlantis"),
        _brief("brief_2", "2026-09-04", "lima"),
    ]
    with patch(f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=briefs)):
        async with captured_wide_event() as event:
            result = await collected_postmarks(USER_ID)

    assert [postmark.city_slug for postmark in result.postmarks] == ["lima"]
    [warning] = event["warnings"]
    assert (warning["msg"], warning["city_slug"], warning["briefing_id"]) == (
        "briefing.postmark_city_unknown",
        "atlantis",
        "brief_1",
    )
