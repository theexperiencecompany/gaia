"""Contract tests for DeviceTokensRepository: one document per Expo push token, on real Mongo.

The fixture builds the production indexes on the throwaway collection, so the
unique token key is what decides who holds a token.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
import pytest

from app.db.mongodb.indexes import create_device_token_indexes
from app.db.repositories.device_tokens import DeviceTokensRepository
from app.models.device_token_models import PlatformType

USER = "6812f0b3c9a14e2b7d5a91cc"
OTHER = "6812f0b3c9a14e2b7d5a91cd"
TOKEN = "ExponentPushToken[aaaaaaaaaaaaaaaaaaaaaa]"
SECOND_TOKEN = "ExponentPushToken[bbbbbbbbbbbbbbbbbbbbbb]"
LONG_AGO = datetime(2026, 1, 11, 10, 0, tzinfo=UTC)


@pytest.fixture
async def repo(raw_collection, monkeypatch: pytest.MonkeyPatch) -> DeviceTokensRepository:
    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", lambda _name: raw_collection)
    await create_device_token_indexes()
    return DeviceTokensRepository()


async def _register(
    repo: DeviceTokensRepository,
    token: str = TOKEN,
    user_id: str = USER,
    platform: PlatformType = PlatformType.IOS,
    device_id: str | None = None,
) -> bool:
    return await repo.register(user_id=user_id, token=token, platform=platform, device_id=device_id)


class TestDeviceTokensRepository:
    async def test_a_new_token_is_stored_with_exactly_the_documented_fields(
        self, repo, raw_collection
    ):
        before = datetime.now(UTC).replace(microsecond=0)

        is_new = await _register(repo)

        assert is_new is True
        raw = await raw_collection.find_one({"token": TOKEN})
        assert raw is not None
        assert isinstance(raw.pop("_id"), ObjectId)
        created_at, updated_at = raw.pop("created_at"), raw.pop("updated_at")
        assert raw == {
            "token": TOKEN,
            "user_id": USER,
            "platform": "ios",
            "device_id": None,
            "is_active": True,
        }
        assert created_at >= before and updated_at >= before

    async def test_registering_a_known_token_updates_it_in_place_and_keeps_created_at(
        self, repo, raw_collection
    ):
        await _register(repo)
        await raw_collection.update_one(
            {"token": TOKEN}, {"$set": {"created_at": LONG_AGO, "updated_at": LONG_AGO}}
        )

        is_new = await _register(repo, platform=PlatformType.ANDROID, device_id="pixel-9")

        assert is_new is False
        assert await raw_collection.count_documents({}) == 1
        device = await repo.get(TOKEN, user_id=USER)
        assert device is not None
        assert (device.platform, device.device_id) == (PlatformType.ANDROID, "pixel-9")
        assert device.created_at == LONG_AGO
        assert device.updated_at > LONG_AGO

    async def test_a_token_registered_by_another_user_moves_to_them(self, repo, raw_collection):
        await _register(repo, user_id=USER)

        is_new = await _register(repo, user_id=OTHER)

        assert is_new is False
        assert await raw_collection.count_documents({"token": TOKEN}) == 1
        assert await repo.get(TOKEN, user_id=USER) is None
        moved = await repo.get(TOKEN, user_id=OTHER)
        assert moved is not None and moved.user_id == OTHER

    async def test_get_reads_a_token_only_for_the_user_holding_it(self, repo):
        await _register(repo, device_id="iphone-15")

        held = await repo.get(TOKEN, user_id=USER)

        assert held is not None
        assert (held.token, held.user_id, held.platform) == (TOKEN, USER, PlatformType.IOS)
        assert (held.device_id, held.is_active) == ("iphone-15", True)
        assert await repo.get(TOKEN, user_id=OTHER) is None
        assert await repo.get(SECOND_TOKEN, user_id=USER) is None

    async def test_delete_removes_a_token_only_for_the_user_holding_it(self, repo):
        await _register(repo)

        assert await repo.delete(TOKEN, user_id=OTHER) is False
        assert await repo.get(TOKEN, user_id=USER) is not None
        assert await repo.delete(TOKEN, user_id=USER) is True
        assert await repo.get(TOKEN, user_id=USER) is None
        assert await repo.delete(TOKEN, user_id=USER) is False

    async def test_count_for_user_counts_inactive_tokens_and_no_one_elses(self, repo):
        await _register(repo, TOKEN)
        await _register(repo, SECOND_TOKEN)
        await _register(repo, "ExponentPushToken[cccccccccccccccccccccc]", user_id=OTHER)
        await repo.deactivate([SECOND_TOKEN])

        assert await repo.count_for_user(USER) == 2
        assert await repo.count_for_user(OTHER) == 1
        assert await repo.count_for_user("6812f0b3c9a14e2b7d5a91ce") == 0

    async def test_list_active_tokens_returns_only_that_users_active_tokens(self, repo):
        await _register(repo, TOKEN)
        await _register(repo, SECOND_TOKEN)
        await _register(repo, "ExponentPushToken[cccccccccccccccccccccc]", user_id=OTHER)
        await repo.deactivate([SECOND_TOKEN])

        assert await repo.list_active_tokens(USER) == [TOKEN]
        assert await repo.list_active_tokens("6812f0b3c9a14e2b7d5a91ce") == []

    async def test_deactivate_marks_the_named_tokens_inactive_across_users(self, repo):
        third = "ExponentPushToken[cccccccccccccccccccccc]"
        await _register(repo, TOKEN)
        await _register(repo, SECOND_TOKEN)
        await _register(repo, third, user_id=OTHER)

        await repo.deactivate([SECOND_TOKEN, third, "ExponentPushToken[never-registered]"])

        assert await repo.list_active_tokens(USER) == [TOKEN]
        assert await repo.list_active_tokens(OTHER) == []
        kept = await repo.get(third, user_id=OTHER)
        assert kept is not None and kept.is_active is False

    async def test_registering_a_deactivated_token_again_reactivates_it(self, repo):
        await _register(repo)
        await repo.deactivate([TOKEN])
        assert await repo.list_active_tokens(USER) == []

        await _register(repo)

        assert await repo.list_active_tokens(USER) == [TOKEN]
