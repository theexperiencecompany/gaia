"""Turning briefs off while workflows still deliver to the brief, against REAL MongoDB.

The real router, schedule service and repositories run; only the analytics
capture is replaced, and every assertion reads the documents back from Mongo.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from unittest.mock import MagicMock, patch

from bson import ObjectId
from httpx import AsyncClient
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.constants.error_codes import BRIEF_DELIVERY_WORKFLOWS_EXIST
from app.constants.workflows import WorkflowDelivery
from app.db.redis import delete_cache
from app.db.repositories.users import user_repository
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowDocument
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import (
    SettingsBriefsOffBlocked,
    SettingsBriefsOffResolved,
)
from tests.conftest import FAKE_USER

pytestmark = pytest.mark.service

SCHEDULE_URL = "/api/v1/notifications/preferences/briefing-schedule"
USER_OID = ObjectId(FAKE_USER.user_id)
OTHER_USER_ID = "507f1f77bcf86cd799439099"
DAILY = {"frequency": "daily", "hour": 9}


@pytest.fixture(autouse=True)
async def _user(mongo_db) -> AsyncIterator[None]:
    await mongo_db["users"].delete_many({"_id": USER_OID})
    await mongo_db["workflows"].delete_many(
        {"user_id": {"$in": [FAKE_USER.user_id, OTHER_USER_ID]}}
    )
    await mongo_db["users"].insert_one(
        {
            "_id": USER_OID,
            "email": FAKE_USER.email,
            "name": FAKE_USER.name,
            "timezone": "UTC",
            "briefing_schedule": DAILY,
        }
    )
    # The raw insert bypasses the repository, so drop any entity an earlier test cached.
    await delete_cache(
        user_repository.cache_policy.entity_key(REPO_GLOBAL_SCOPE, FAKE_USER.user_id)
    )
    yield
    await mongo_db["users"].delete_many({"_id": USER_OID})
    await mongo_db["workflows"].delete_many(
        {"user_id": {"$in": [FAKE_USER.user_id, OTHER_USER_ID]}}
    )


@pytest.fixture
def captured() -> Iterator[MagicMock]:
    with patch("app.services.briefing.schedule.capture") as capture:
        yield capture


async def _seed(
    mongo_db, title: str, delivery: WorkflowDelivery, user_id: str = FAKE_USER.user_id
) -> str:
    workflow = WorkflowDocument(
        user_id=user_id,
        title=title,
        prompt="Summarise the day",
        steps=[],
        delivery=delivery,
        trigger_config=TriggerConfig(type=TriggerType.MANUAL),
    )
    await mongo_db["workflows"].insert_one(
        workflow.model_dump(by_alias=True, exclude={"id"}) | {"_id": workflow.id}
    )
    return workflow.id


async def _stored_schedule(mongo_db) -> dict[str, object]:
    user = await mongo_db["users"].find_one({"_id": USER_OID})
    return user["briefing_schedule"]


async def _delivery(mongo_db, workflow_id: str) -> str:
    workflow = await mongo_db["workflows"].find_one({"_id": workflow_id})
    return workflow["delivery"]


class TestBriefsOffGuard:
    async def test_off_is_a_409_naming_every_workflow_still_on_the_brief(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        news = await _seed(mongo_db, "Morning news", WorkflowDelivery.BRIEF)
        prs = await _seed(mongo_db, "Open PRs", WorkflowDelivery.BRIEF)
        await _seed(mongo_db, "Pinged now", WorkflowDelivery.NOW)

        response = await client.put(SCHEDULE_URL, json={"frequency": "off", "hour": 9})

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == BRIEF_DELIVERY_WORKFLOWS_EXIST
        assert body["message"] == "2 workflows send their results to your brief"
        assert sorted(body["workflows"], key=lambda w: w["title"]) == [
            {"id": news, "title": "Morning news"},
            {"id": prs, "title": "Open PRs"},
        ]
        assert await _stored_schedule(mongo_db) == DAILY
        captured.assert_called_once_with(
            UserId(FAKE_USER.user_id), SettingsBriefsOffBlocked(workflow_count=2, via="settings")
        )

    async def test_off_is_refused_while_one_brief_workflow_has_no_new_delivery(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        chosen = await _seed(mongo_db, "Morning news", WorkflowDelivery.BRIEF)
        left = await _seed(mongo_db, "Open PRs", WorkflowDelivery.BRIEF)

        response = await client.put(
            SCHEDULE_URL,
            json={"frequency": "off", "hour": 9, "workflow_deliveries": {chosen: "now"}},
        )

        assert response.status_code == 409
        assert response.json()["workflows"] == [{"id": left, "title": "Open PRs"}]
        assert await _delivery(mongo_db, chosen) == "brief"
        assert await _stored_schedule(mongo_db) == DAILY

    async def test_off_is_stored_when_no_workflow_delivers_to_the_brief(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        await _seed(mongo_db, "Pinged now", WorkflowDelivery.NOW)
        await _seed(mongo_db, "Someone else's", WorkflowDelivery.BRIEF, user_id=OTHER_USER_ID)

        response = await client.put(SCHEDULE_URL, json={"frequency": "off", "hour": 9})

        assert response.status_code == 200
        assert response.json() == {"frequency": "off", "hour": 9}
        assert await _stored_schedule(mongo_db) == {"frequency": "off", "hour": 9}
        assert not any(
            isinstance(call.args[1], SettingsBriefsOffBlocked | SettingsBriefsOffResolved)
            for call in captured.call_args_list
        )

    async def test_off_moves_each_brief_workflow_to_its_chosen_delivery(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        news = await _seed(mongo_db, "Morning news", WorkflowDelivery.BRIEF)
        prs = await _seed(mongo_db, "Open PRs", WorkflowDelivery.BRIEF)
        digest = await _seed(mongo_db, "Digest", WorkflowDelivery.BRIEF)

        response = await client.put(
            SCHEDULE_URL,
            json={
                "frequency": "off",
                "hour": 9,
                "workflow_deliveries": {news: "now", prs: "now", digest: "silent"},
            },
        )

        assert response.status_code == 200
        assert [await _delivery(mongo_db, w) for w in (news, prs, digest)] == [
            "now",
            "now",
            "silent",
        ]
        assert await _stored_schedule(mongo_db) == {"frequency": "off", "hour": 9}
        captured.assert_any_call(
            UserId(FAKE_USER.user_id),
            SettingsBriefsOffResolved(moved_to_now=2, moved_to_silent=1, via="settings"),
        )

    async def test_weekly_only_stays_allowed_with_brief_workflows(
        self, client: AsyncClient, mongo_db, captured: MagicMock
    ) -> None:
        await _seed(mongo_db, "Morning news", WorkflowDelivery.BRIEF)

        response = await client.put(SCHEDULE_URL, json={"frequency": "weekly_only", "hour": 9})

        assert response.status_code == 200
        assert await _stored_schedule(mongo_db) == {"frequency": "weekly_only", "hour": 9}

    @pytest.mark.parametrize("delivery", ["brief", "silent"])
    async def test_new_deliveries_only_come_with_turning_briefs_off(
        self, client: AsyncClient, mongo_db, captured: MagicMock, delivery: str
    ) -> None:
        news = await _seed(mongo_db, "Morning news", WorkflowDelivery.BRIEF)
        frequency = "off" if delivery == "brief" else "daily"

        response = await client.put(
            SCHEDULE_URL,
            json={"frequency": frequency, "hour": 9, "workflow_deliveries": {news: delivery}},
        )

        assert response.status_code == 422
        assert await _delivery(mongo_db, news) == "brief"
        assert await _stored_schedule(mongo_db) == DAILY
