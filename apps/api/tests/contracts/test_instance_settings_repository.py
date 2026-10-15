"""Contract tests for InstanceSettingsRepository against real Mongo: one value per key."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.instance_settings import InstanceSettingsRepository


@pytest.fixture
def repo(raw_collection: AsyncIOMotorCollection) -> InstanceSettingsRepository:
    return InstanceSettingsRepository()


async def test_an_unset_key_reads_as_none(repo: InstanceSettingsRepository) -> None:
    assert await repo.find_by_key("setup") is None


async def test_set_value_writes_then_replaces_one_row_per_key(
    repo: InstanceSettingsRepository, raw_collection: AsyncIOMotorCollection
) -> None:
    await repo.set_value("setup", {"dismissed": False})
    await repo.set_value("setup", {"dismissed": True})
    await repo.set_value("registration", {"policy": "open"})

    stored = await repo.find_by_key("setup")
    assert stored is not None and stored.value == {"dismissed": True}
    assert await raw_collection.count_documents({"key": "setup"}) == 1


async def test_only_the_first_set_if_absent_wins(repo: InstanceSettingsRepository) -> None:
    assert await repo.set_if_absent("secrets", {"instance_secret": "first"}) is True
    assert await repo.set_if_absent("secrets", {"instance_secret": "second"}) is False

    stored = await repo.find_by_key("secrets")
    assert stored is not None and stored.value == {"instance_secret": "first"}


async def test_put_returns_the_value_it_stored(repo: InstanceSettingsRepository) -> None:
    await repo.put("registration", {"policy": "invite_only"})

    stored = await repo.put("registration", {"policy": "open"})

    assert (stored.key, stored.value) == ("registration", {"policy": "open"})
    reread = await repo.find_by_key("registration")
    assert reread is not None and reread.value == {"policy": "open"}
