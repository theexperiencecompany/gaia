"""A shared brief shows anyone but its owner the front page alone, through every route that serves it.

The link service and the brief's link target run for real; only the stores they read are faked.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.constants.briefing import BriefOutcome, EditionFamily
from app.models.brief_document_models import BriefingModel, EditionRender
from app.models.brief_payload_models import (
    BriefingEvent,
    BriefingItem,
    BriefingMood,
    BriefingPayload,
    BriefingSection,
)
from app.models.short_link_models import (
    LinkAccess,
    RecordTarget,
    ShortLink,
    ShortLinkTargetType,
)

SLUG = "abcdefghijk"
OWNER = "65f1c0ffee0000000000b01e"
HEADLINE = "A clear Tuesday"
ITEM_TEXT = "Reply to Priya about the lease"
SECTION_TITLE = "Waiting on you"
EVENT_TITLE = "Therapy with Dr. Rao"
EDITION_ROUTE = "/briefings/editions/"

_BRIEF = BriefingModel(
    id="brief_abc",
    user_id=OWNER,
    date="2026-10-14",
    edition=EditionRender(key="edition-key"),
    payload=BriefingPayload(
        kicker="THE MORNING BRIEF",
        template_family=EditionFamily.SWISS,
        date="Oct 14",
        headline=HEADLINE,
        lede="One thing waits.",
        sections=[
            BriefingSection(
                numeral="I",
                title=SECTION_TITLE,
                items=[BriefingItem(text=ITEM_TEXT, outcome=BriefOutcome.SENT)],
            )
        ],
        mood=BriefingMood.CLEAR,
        caption="Onward.",
        calendar=[BriefingEvent(date="2026-10-14", start="11:00", title=EVENT_TITLE)],
    ),
)
_LINK = ShortLink(
    slug=SLUG,
    user_id=OWNER,
    target=RecordTarget(type=ShortLinkTargetType.BRIEFING, id=_BRIEF.id),
    access=LinkAccess.PUBLIC,
)


async def _owned_brief(briefing_id: str, user_id: str) -> BriefingModel | None:
    return _BRIEF if (briefing_id, user_id) == (_BRIEF.id, OWNER) else None


@pytest.fixture(autouse=True)
def shared_brief() -> Iterator[None]:
    with (
        patch(
            "app.api.v1.endpoints.short_links.get_link",
            AsyncMock(side_effect=lambda slug: _LINK if slug == SLUG else None),
        ),
        patch("app.api.v1.endpoints.short_links.abuse.refuse_when_locked_out", AsyncMock()),
        patch(
            "app.services.links.targets.briefing.briefing_repository.get",
            AsyncMock(side_effect=_owned_brief),
        ),
        patch(
            "app.api.v1.endpoints.briefings.briefing_repository.get",
            AsyncMock(side_effect=_owned_brief),
        ),
    ):
        yield


def _assert_front_page_only(body: str) -> None:
    for private in (ITEM_TEXT, SECTION_TITLE, EVENT_TITLE, EDITION_ROUTE, _BRIEF.id, OWNER):
        assert private not in body


async def _assert_link_serves_the_front_page_alone(api: AsyncClient) -> None:
    resolved = await api.get(f"/api/v1/l/{SLUG}")
    opened = await api.post(f"/api/v1/l/{SLUG}/opened")

    for response in (resolved, opened):
        assert response.status_code == 200, response.text
        _assert_front_page_only(response.text)
        view = response.json()["view"]
        assert (view["headline"], view["date"]) == (HEADLINE, "Oct 14")


async def test_a_signed_out_viewer_sees_the_front_page_alone(unauthed_client: AsyncClient) -> None:
    await _assert_link_serves_the_front_page_alone(unauthed_client)


async def test_a_signed_in_stranger_sees_the_front_page_alone(client: AsyncClient) -> None:
    await _assert_link_serves_the_front_page_alone(client)


async def test_the_links_preview_card_carries_no_item_and_no_edition(
    unauthed_client: AsyncClient,
) -> None:
    response = await unauthed_client.get(f"/api/v1/l/{SLUG}/meta")

    assert response.status_code == 200
    assert response.json()["title"] == HEADLINE
    assert response.json()["image_url"] is None
    _assert_front_page_only(response.text)


async def test_a_non_owner_cannot_open_the_brief_itself(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/briefings/{_BRIEF.id}")

    assert response.status_code == 404
    _assert_front_page_only(response.text.replace(_BRIEF.id, ""))
