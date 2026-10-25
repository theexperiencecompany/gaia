"""Contract tests for ProviderCredentialsRepository against real Mongo: one ciphertext row per provider."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.provider_credentials import ProviderCredentialsRepository


@pytest.fixture
def repo(raw_collection: AsyncIOMotorCollection) -> ProviderCredentialsRepository:
    return ProviderCredentialsRepository()


async def test_an_unconfigured_provider_has_no_row(repo: ProviderCredentialsRepository) -> None:
    assert await repo.find_by_provider("openai") is None
    assert await repo.exists("openai") is False


async def test_a_save_writes_one_row_and_a_resave_replaces_its_ciphertext(
    repo: ProviderCredentialsRepository, raw_collection: AsyncIOMotorCollection
) -> None:
    await repo.upsert_encrypted("openai", "cipher-1")
    await repo.upsert_encrypted("openai", "cipher-2")
    await repo.upsert_encrypted("gemini", "cipher-g")

    stored = await repo.find_by_provider("openai")
    assert stored is not None
    assert (stored.provider, stored.data_encrypted) == ("openai", "cipher-2")
    assert await repo.exists("openai") is True
    assert await raw_collection.count_documents({"provider": "openai"}) == 1
    assert await raw_collection.count_documents({}) == 2
