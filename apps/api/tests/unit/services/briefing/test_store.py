"""A brief is given its id and link, rendered around that link, then stored with its edition.

Faked seams: the briefing repository, the short-link mint and the edition image host.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import BriefingPayload, EditionRender
from app.models.short_link_models import ShortLinkTargetType
from app.services.briefing import store
from app.services.briefing.edition_email import HostedEditionImage

_USER = "64f1c0ffee0000000000abcd"
_DATE = "2026-10-14"
_BRIEF_ID = "brief-1"


def _payload() -> BriefingPayload:
    return BriefingPayload(
        kicker="K",
        date=_DATE,
        headline="h",
        lede="l",
        mood="clear",
        caption="c",
        template_family="memo",
    )


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = {
        "briefing_id_for": AsyncMock(return_value=_BRIEF_ID),
        "upsert_briefing": AsyncMock(return_value=MagicMock(id=_BRIEF_ID)),
        "optional_short_link": AsyncMock(return_value="https://heygaia.link/abc"),
        "host_edition_image": AsyncMock(
            return_value=HostedEditionImage(
                display_url="https://cdn.example/f_auto/brief",
                chat_url="https://cdn.example/f_jpg/brief",
                fold=0.4,
                paper=(0.1, 0.2, 0.9, 0.8),
            )
        ),
    }
    monkeypatch.setattr(briefing_repository, "briefing_id_for", fakes["briefing_id_for"])
    monkeypatch.setattr(briefing_repository, "upsert_briefing", fakes["upsert_briefing"])
    monkeypatch.setattr(store, "optional_short_link", fakes["optional_short_link"])
    monkeypatch.setattr(store, "host_edition_image", fakes["host_edition_image"])
    return fakes


class TestStoreBrief:
    async def test_the_brief_is_looked_up_minted_rendered_and_stored_under_one_id(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        payload = _payload()

        stored = await store.store_brief(_USER, _DATE, "daily", payload)

        seams["briefing_id_for"].assert_awaited_once_with(_USER, _DATE, "daily")
        seams["optional_short_link"].assert_awaited_once_with(
            _USER, ShortLinkTargetType.BRIEFING, _BRIEF_ID
        )
        assert payload.link == "https://heygaia.link/abc"
        assert seams["host_edition_image"].await_args.args == (payload,)
        assert seams["host_edition_image"].await_args.kwargs["owner_id"] == _USER
        seams["upsert_briefing"].assert_awaited_once_with(
            _USER,
            _DATE,
            "daily",
            payload,
            briefing_id=_BRIEF_ID,
            edition=EditionRender(
                image_url="https://cdn.example/f_auto/brief",
                fold=0.4,
                paper=[0.1, 0.2, 0.9, 0.8],
            ),
        )
        assert (stored.briefing.id, stored.link) == (_BRIEF_ID, "https://heygaia.link/abc")

    async def test_without_a_short_link_the_link_is_the_briefs_own_page(
        self, seams: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seams["optional_short_link"].return_value = None
        monkeypatch.setattr(
            "app.services.briefing.message.settings.FRONTEND_URL", "https://app.test"
        )

        stored = await store.store_brief(_USER, _DATE, "daily", _payload())

        assert stored.link == "https://app.test/brief/brief-1"

    async def test_an_edition_without_a_fold_or_paper_box_stores_neither(
        self, seams: dict[str, AsyncMock]
    ) -> None:
        seams["host_edition_image"].return_value = HostedEditionImage(
            display_url="https://cdn.example/f_auto/brief",
            chat_url="https://cdn.example/f_jpg/brief",
        )

        await store.store_brief(_USER, _DATE, "weekly", _payload())

        assert seams["upsert_briefing"].await_args.kwargs["edition"] == EditionRender(
            image_url="https://cdn.example/f_auto/brief", fold=None, paper=None
        )
