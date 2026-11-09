"""GET/PUT /api/v1/instructions/{scope}, run through the real service against an in-memory store."""

from unittest.mock import MagicMock, call, patch

from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER
from tests.user_instructions_fakes import (
    FakeCollection,
    always_connected,
    install_fake_collection,
    never_connected,
)

from app.models.user_instructions_models import GLOBAL_INSTRUCTIONS_SCOPE
from app.services import user_instructions_service as svc

URL = "/api/v1/instructions"
USER_ID = FAKE_USER.user_id

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    monkeypatch.setattr(svc, "schedule_account_sync", lambda _user_id: None)
    monkeypatch.setattr(svc, "schedule_user_integrations_sync", lambda _user_id: None)
    return install_fake_collection(monkeypatch)


@pytest.fixture
def route_log() -> MagicMock:
    with patch("app.api.v1.endpoints.instructions.log") as log:
        yield log


class TestGetInstructions:
    async def test_an_unset_scope_reads_as_revision_zero(
        self, client: AsyncClient, fake_collection: FakeCollection, route_log: MagicMock
    ) -> None:
        resp = await client.get(f"{URL}/{GLOBAL_INSTRUCTIONS_SCOPE}")

        assert resp.status_code == 200
        assert resp.json() == {
            "scope": "global",
            "content": "",
            "revision": 0,
            "updated_by": None,
            "updated_at": None,
        }
        assert route_log.mock_calls == [
            call.set(user={"id": USER_ID}, instructions={"operation": "get"}),
            call.set_ns("instructions", revision=0),
        ]

    async def test_a_saved_scope_returns_its_text_and_revision(
        self, client: AsyncClient, fake_collection: FakeCollection
    ) -> None:
        await client.put(f"{URL}/global", json={"content": "be brief", "base_revision": 0})

        body = (await client.get(f"{URL}/global")).json()

        assert (body["content"], body["revision"], body["updated_by"]) == ("be brief", 1, "user")

    async def test_an_unconnected_integration_is_a_404_for_this_user(
        self, client: AsyncClient, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        asked: list[tuple[str, str]] = []

        async def check(user_id: str, scope: str) -> bool:  # NOSONAR python:S7503
            asked.append((user_id, scope))
            return False

        monkeypatch.setattr(svc, "check_user_has_integration", check)

        resp = await client.get(f"{URL}/slack")

        assert resp.status_code == 404
        assert resp.json()["message"] == "'slack' is not one of this user's connected integrations"
        assert asked == [(USER_ID, "slack")]

    async def test_an_unsafe_scope_is_a_400(
        self, client: AsyncClient, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(svc, "check_user_has_integration", always_connected)

        resp = await client.get(f"{URL}/caf%C3%A9")

        assert resp.status_code == 400
        assert resp.json()["message"] == "Invalid instructions scope 'café'"


class TestUpdateInstructions:
    async def test_a_save_is_a_user_write_on_the_sent_revision(
        self, client: AsyncClient, fake_collection: FakeCollection, route_log: MagicMock
    ) -> None:
        resp = await client.put(
            f"{URL}/{GLOBAL_INSTRUCTIONS_SCOPE}", json={"content": "be brief", "base_revision": 0}
        )

        body = resp.json()
        assert resp.status_code == 200
        assert (body["scope"], body["content"], body["revision"], body["updated_by"]) == (
            "global",
            "be brief",
            1,
            "user",
        )
        assert fake_collection.docs[0]["updated_by"] == "user"
        assert route_log.mock_calls == [
            call.set(user={"id": USER_ID}, instructions={"operation": "update"}),
            call.set_ns("instructions", revision=1),
        ]

    async def test_a_stale_revision_is_a_409_carrying_the_current_one(
        self, client: AsyncClient, fake_collection: FakeCollection
    ) -> None:
        await client.put(f"{URL}/global", json={"content": "v1", "base_revision": 0})
        await client.put(f"{URL}/global", json={"content": "v2", "base_revision": 1})

        resp = await client.put(f"{URL}/global", json={"content": "editor", "base_revision": 1})

        assert resp.status_code == 409
        assert resp.json()["current_revision"] == 2
        assert fake_collection.docs[0]["content"] == "v2"

    async def test_an_unconnected_integration_is_refused_before_anything_is_written(
        self, client: AsyncClient, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(svc, "check_user_has_integration", never_connected)

        resp = await client.put(f"{URL}/slack", json={"content": "hi", "base_revision": 0})

        assert resp.status_code == 404
        assert fake_collection.docs == []
