"""Postmarks: a user's collected Air Mail stamps, built from each city's first stamped brief.

The repository is faked; the real stamp catalogue (cities.json) is read.
"""

from unittest.mock import AsyncMock, patch

from tests.factories import make_user_id
from tests.helpers import captured_wide_event

from app.config.settings import settings
from app.constants.briefing import BriefingKind, EditionFamily
from app.models.brief_document_models import (
    BriefCardRecord,
    BriefingModel,
    EditionImage,
    EditionRender,
)
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.models.brief_view_models import BriefCard, Postmark
from app.services.briefing.postmarks import collected_postmarks

MODULE = "app.services.briefing.postmarks"
USER_ID = make_user_id()
_EDITION_URL = f"{settings.HOST}/api/v1/briefings/editions/"
_STAMP_URL = f"{settings.HOST}/api/v1/briefings/stamps/"
_PAPER = [0.1, 0.05, 0.9, 0.95]


def _unsigned(postmark: Postmark) -> Postmark:
    """Cut each edition URL's signature, which changes with the day it is issued."""
    edition = postmark.card.edition
    if edition is None:
        return postmark
    url = edition.image_url.split("?t=")[0] + "?t="
    card = postmark.card.model_copy(
        update={"edition": edition.model_copy(update={"image_url": url})}
    )
    return postmark.model_copy(update={"card": card})


def _brief(brief_id: str, date: str, stamp_city: str) -> BriefCardRecord:
    brief = BriefingModel(
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
            template_family=EditionFamily.POSTAL,
            stamp_city=stamp_city,
        ),
    )
    return BriefCardRecord.model_validate(brief, from_attributes=True)


def _card(brief_id: str, date: str, city: str) -> BriefCard:
    return BriefCard(
        briefing_id=brief_id,
        date=date,
        kind=BriefingKind.DAILY,
        headline="Postcard",
        edition=EditionImage(
            image_url=f"{_EDITION_URL}key-{brief_id}/png?t=", fold=0.31, paper=_PAPER
        ),
        edition_name="Air Mail",
        stamp_city_name=city,
        needs_you_count=0,
    )


async def test_each_city_is_shown_with_the_card_of_the_brief_it_first_came_on() -> None:
    briefs = [_brief("brief_1", "2026-09-01", "tokyo"), _brief("brief_2", "2026-09-04", "lima")]
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
            stamp_url=f"{_STAMP_URL}tokyo.webp",
            card=_card("brief_1", "2026-09-01", "Tokyo"),
        ),
        Postmark(
            city_slug="lima",
            city="Lima",
            country="Peru",
            lat=-12.05,
            lng=-77.04,
            stamp_url=f"{_STAMP_URL}lima.webp",
            card=_card("brief_2", "2026-09-04", "Lima"),
        ),
    ]


async def test_a_postmark_carries_its_briefs_edition_so_the_stamp_opens_without_fetching_it() -> (
    None
):
    briefs = [_brief("brief_1", "2026-09-01", "tokyo")]
    with patch(f"{MODULE}.briefing_repository.list_stamped", AsyncMock(return_value=briefs)):
        result = await collected_postmarks(USER_ID)

    [tokyo] = result.postmarks
    edition = tokyo.card.edition
    assert edition is not None
    assert edition.image_url.startswith(f"{_EDITION_URL}key-brief_1/png?t=")
    assert (edition.fold, edition.paper) == (0.31, _PAPER)


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
