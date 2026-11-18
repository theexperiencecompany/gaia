"""A brief is given its id and link, rendered around that link, then stored with its edition.

Faked seams: the briefing repository, the short-link mint, the render and the edition store.
"""

from unittest.mock import AsyncMock

import pytest

from app.config.settings import settings
from app.constants.briefing import BriefingKind, EditionFamily
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefDelivery, BriefingModel, EditionRender
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.models.short_link_models import RecordTarget, ShortLink, ShortLinkTargetType
from app.services.briefing import store
from app.services.briefing.render import RenderedImage

_USER = "64f1c0ffee0000000000abcd"
_DATE = "2026-10-14"
_BRIEF_ID = "brief-1"
_PLAN = BriefDelivery(push=True, notification_kind="briefing_daily")


def _payload() -> BriefingPayload:
    return BriefingPayload(
        kicker="K",
        date=_DATE,
        headline="h",
        lede="l",
        mood=BriefingMood.CLEAR,
        caption="c",
        template_family=EditionFamily.MEMO,
    )


async def _upserted(brief: BriefingModel) -> BriefingModel:
    return brief


_LINK = ShortLink(
    slug="abcdefghijk",
    user_id=_USER,
    target=RecordTarget(type=ShortLinkTargetType.BRIEFING, id=_BRIEF_ID),
)
_LINK_URL = f"{settings.SHORTLINK_BASE_URL}/abcdefghijk"


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = {
        "briefing_id_for": AsyncMock(return_value=_BRIEF_ID),
        "upsert_briefing": AsyncMock(side_effect=_upserted),
        "attach_link": AsyncMock(return_value=_LINK),
        "render_edition_png": AsyncMock(
            return_value=RenderedImage(image=b"png", fold=0.4, paper=(0.1, 0.2, 0.9, 0.8))
        ),
        "store_edition": AsyncMock(return_value="edition-key"),
    }
    monkeypatch.setattr(briefing_repository, "briefing_id_for", fakes["briefing_id_for"])
    monkeypatch.setattr(briefing_repository, "upsert_briefing", fakes["upsert_briefing"])
    monkeypatch.setattr(store, "attach_link", fakes["attach_link"])
    monkeypatch.setattr(store, "render_edition_png", fakes["render_edition_png"])
    monkeypatch.setattr(store, "store_edition", fakes["store_edition"])
    return fakes


class TestStoreBrief:
    async def test_the_brief_is_looked_up_minted_rendered_and_stored_under_one_id(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        payload = _payload()

        stored = await store.store_brief(_USER, _DATE, BriefingKind.DAILY, payload, _PLAN)

        seams["briefing_id_for"].assert_awaited_once_with(_USER, _DATE, "daily")
        seams["attach_link"].assert_awaited_once_with(
            _USER, RecordTarget(type=ShortLinkTargetType.BRIEFING, id=_BRIEF_ID)
        )
        linked = payload.model_copy(update={"link": _LINK_URL})
        assert payload.link is None
        assert seams["render_edition_png"].await_args.args == (linked,)
        seams["store_edition"].assert_awaited_once_with(_USER, _BRIEF_ID, b"png")
        [brief] = seams["upsert_briefing"].await_args.args
        assert (brief.id, brief.user_id, brief.date, brief.kind) == (
            _BRIEF_ID,
            _USER,
            _DATE,
            "daily",
        )
        assert (brief.payload, brief.delivery) == (linked, _PLAN)
        assert brief.edition == EditionRender(
            key="edition-key", fold=0.4, paper=[0.1, 0.2, 0.9, 0.8]
        )
        assert (stored.id, stored.payload.link) == (_BRIEF_ID, _LINK_URL)

    async def test_the_brief_exists_before_its_link_is_minted(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        """Simulator: the link was minted to a brief not yet stored ("Target not found"), so it fell back."""
        order: list[str] = []

        async def stored(brief: BriefingModel) -> BriefingModel:
            order.append("stored" if brief.edition is None else "stored with its edition")
            return brief

        async def minted(*_a: object) -> ShortLink:
            order.append("minted")
            return _LINK

        seams["upsert_briefing"].side_effect = stored
        seams["attach_link"].side_effect = minted

        await store.store_brief(_USER, _DATE, BriefingKind.DAILY, _payload(), _PLAN)

        assert order == ["stored", "minted", "stored with its edition"]

    async def test_without_a_short_link_the_link_is_the_briefs_own_page(
        self, seams: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seams["attach_link"].return_value = None
        monkeypatch.setattr(
            "app.services.briefing.message.settings.FRONTEND_URL", "https://app.test"
        )

        stored = await store.store_brief(_USER, _DATE, BriefingKind.DAILY, _payload(), _PLAN)

        assert stored.payload.link == "https://app.test/brief/brief-1"

    async def test_an_edition_without_a_fold_or_paper_box_stores_neither(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        seams["render_edition_png"].return_value = RenderedImage(image=b"png")

        await store.store_brief(_USER, _DATE, BriefingKind.WEEKLY, _payload(), _PLAN)

        assert seams["upsert_briefing"].await_args.args[0].edition == EditionRender(
            key="edition-key"
        )


class TestStoreNote:
    async def test_a_quiet_note_is_stored_under_its_briefs_id_with_no_edition_or_link(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        seams["briefing_id_for"].side_effect = lambda user_id, date, kind: (
            _BRIEF_ID if (user_id, date, kind) == (_USER, _DATE, "weekly") else "brief-fresh"
        )
        payload = _payload()

        stored = await store.store_note(_USER, _DATE, BriefingKind.WEEKLY, payload, _PLAN)

        [brief] = seams["upsert_briefing"].await_args.args
        assert (brief.id, brief.kind, brief.payload) == (_BRIEF_ID, "weekly", payload)
        assert (brief.edition, brief.delivery) == (None, _PLAN)
        seams["attach_link"].assert_not_awaited()
        seams["render_edition_png"].assert_not_awaited()
        seams["store_edition"].assert_not_awaited()
        assert (stored.id, stored.payload.link) == (_BRIEF_ID, None)
