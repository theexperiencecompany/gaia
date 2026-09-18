"""Unit tests for the browser-profiles repository's raw upsert/delete/read paths."""

from datetime import UTC, timedelta
from unittest.mock import AsyncMock, patch

from app.db.repositories.browser_profiles import BrowserProfilesRepository
from app.models.browser_models import BrowserLoginProvenance


class TestUpsertStorageStateBlob:
    async def test_sets_only_the_blob_when_no_provenance_given(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(
            repo, "_apply_raw_update_unfetched", new=AsyncMock(return_value=1)
        ) as apply_update:
            await repo.upsert_storage_state_blob("user-1", "example.com", "encrypted-blob")

        apply_update.assert_awaited_once()
        args, kwargs = apply_update.await_args
        filter_, update = args
        assert filter_ == {"user_id": "user-1", "domain": "example.com"}
        assert update["$set"] == {"storage_state_blob": "encrypted-blob"}
        assert kwargs["scope"] == "user-1"
        assert kwargs["upsert"] is True

    async def test_sets_provenance_fields_when_given(self) -> None:
        repo = BrowserProfilesRepository()
        provenance = BrowserLoginProvenance(
            source="import", source_browser="chrome", source_ip="1.2.3.4"
        )
        with patch.object(
            repo, "_apply_raw_update_unfetched", new=AsyncMock(return_value=1)
        ) as apply_update:
            await repo.upsert_storage_state_blob(
                "user-1", "example.com", "encrypted-blob", provenance=provenance
            )

        args, _ = apply_update.await_args
        _, update = args
        assert update["$set"] == {
            "storage_state_blob": "encrypted-blob",
            "source": "import",
            "source_browser": "chrome",
            "source_ip": "1.2.3.4",
        }

    async def test_set_on_insert_carries_user_domain_and_a_utc_created_at(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(
            repo, "_apply_raw_update_unfetched", new=AsyncMock(return_value=1)
        ) as apply_update:
            await repo.upsert_storage_state_blob("user-1", "example.com", "encrypted-blob")

        args, _ = apply_update.await_args
        _, update = args
        set_on_insert = update["$setOnInsert"]
        created_at = set_on_insert["created_at"]
        assert set_on_insert == {
            "user_id": "user-1",
            "domain": "example.com",
            "created_at": created_at,
        }
        assert created_at.tzinfo is not None
        assert created_at.utcoffset() == timedelta(0)
        assert created_at.tzinfo is UTC

    async def test_upserts_scoped_to_the_user(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(
            repo, "_apply_raw_update_unfetched", new=AsyncMock(return_value=1)
        ) as apply_update:
            await repo.upsert_storage_state_blob("user-1", "example.com", "encrypted-blob")

        _, kwargs = apply_update.await_args
        assert kwargs["scope"] == "user-1"
        assert kwargs["upsert"] is True


class TestDeleteForUser:
    async def test_deletes_only_the_given_domain_when_domain_is_set(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(repo, "_delete_many", new=AsyncMock(return_value=1)) as delete_many:
            count = await repo.delete_for_user("user-1", domain="example.com")

        delete_many.assert_awaited_once_with(
            {"user_id": "user-1", "domain": "example.com"}, scope="user-1"
        )
        assert count == 1

    async def test_deletes_every_profile_for_the_user_when_domain_is_none(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(repo, "_delete_many", new=AsyncMock(return_value=3)) as delete_many:
            count = await repo.delete_for_user("user-1")

        delete_many.assert_awaited_once_with({"user_id": "user-1"}, scope="user-1")
        assert count == 3


class TestGetForDomain:
    async def test_reads_the_profile_scoped_to_user_and_domain(self) -> None:
        repo = BrowserProfilesRepository()
        with patch.object(repo, "_find_one", new=AsyncMock(return_value="the-profile")) as find_one:
            result = await repo.get_for_domain("user-1", "example.com")

        find_one.assert_awaited_once_with({"user_id": "user-1", "domain": "example.com"})
        assert result == "the-profile"
