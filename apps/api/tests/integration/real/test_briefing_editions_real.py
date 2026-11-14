"""Choosing the daily brief's editions through the real router, against REAL MongoDB.

The real router, edition service and repository run; only the analytics capture is
replaced, and the draw reads the user back from Mongo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch

from bson import ObjectId
from httpx import AsyncClient
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.redis import delete_cache
from app.db.repositories.users import user_repository
from app.models.brief_composition_models import SectionBlock
from app.services.briefing.edition_draws import draw_edition
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import SettingsBriefingEditionsUpdated
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.service

EDITIONS_URL = "/api/v1/notifications/preferences/briefing-editions"
USER_OID = ObjectId(FAKE_USER.user_id)


@pytest.fixture(autouse=True)
async def _user(mongo_db) -> AsyncIterator[None]:
    await mongo_db["users"].delete_many({"_id": USER_OID})
    await mongo_db["users"].insert_one(
        {"_id": USER_OID, "email": FAKE_USER.email, "name": FAKE_USER.name, "timezone": "UTC"}
    )
    # The raw insert bypasses the repository, so drop any entity an earlier test cached.
    await delete_cache(
        user_repository.cache_policy.entity_key(REPO_GLOBAL_SCOPE, FAKE_USER.user_id)
    )
    yield
    await mongo_db["users"].delete_many({"_id": USER_OID})


@pytest.fixture
def captured() -> Iterator[MagicMock]:
    with patch("app.services.briefing.edition_choices.capture") as capture:
        yield capture


def _choices(body: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    return {e["family"]: e["choice"] for e in body["editions"]}


class TestBriefingEditions:
    async def test_every_daily_edition_starts_on(self, client: AsyncClient) -> None:
        response = await client.get(EDITIONS_URL)

        assert response.status_code == 200
        assert _choices(response.json()) == dict.fromkeys(DAILY_FAMILY_WEIGHTS, "on")

    async def test_choices_are_stored_read_back_and_drawn_from(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        response = await client.put(
            EDITIONS_URL, json={"choices": {"menu": "off", "swiss": "favourite", "memo": "on"}}
        )

        assert response.status_code == 200
        stored = await mongo_db["users"].find_one({"_id": USER_OID})
        assert stored["briefing_editions"] == {"menu": "off", "swiss": "favourite"}
        read = _choices((await client.get(EDITIONS_URL)).json())
        assert read["menu"] == "off" and read["swiss"] == "favourite" and read["memo"] == "on"
        captured.assert_called_once_with(
            UserId(FAKE_USER.user_id),
            SettingsBriefingEditionsUpdated(
                editions_off=1, editions_favourited=1, editions_total=len(DAILY_FAMILY_WEIGHTS)
            ),
        )
        user = await user_repository.get(FAKE_USER.user_id)
        assert user is not None
        draw = draw_edition(user, [SectionBlock(kind="items", section=0)])
        assert draw.family.next_state.order.count("swiss") == 2
        assert "menu" not in draw.family.next_state.order

    async def test_turning_every_edition_off_is_refused_and_nothing_is_stored(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        response = await client.put(
            EDITIONS_URL, json={"choices": dict.fromkeys(DAILY_FAMILY_WEIGHTS, "off")}
        )

        assert response.status_code == 422
        assert response.json()["message"] == "Keep at least one edition on"
        stored = await mongo_db["users"].find_one({"_id": USER_OID})
        assert "briefing_editions" not in stored
        captured.assert_not_called()

    async def test_an_unknown_or_weekly_family_is_refused(
        self, client: AsyncClient, mongo_db
    ) -> None:
        response = await client.put(EDITIONS_URL, json={"choices": {"weekly": "off"}})

        assert response.status_code == 422
        stored = await mongo_db["users"].find_one({"_id": USER_OID})
        assert "briefing_editions" not in stored
