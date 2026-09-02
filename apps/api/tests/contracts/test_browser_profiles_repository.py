"""Contract tests for BrowserProfilesRepository (one saved login per user+domain)."""

from __future__ import annotations

import uuid

from cryptography.fernet import Fernet
import pytest

from app.config.settings import settings
from app.db.repositories.browser_profiles import BrowserProfilesRepository
from app.models.browser_models import BrowserLoginProvenance
from app.services.browser import storage_persistence


@pytest.fixture
def repo(raw_collection) -> BrowserProfilesRepository:
    return BrowserProfilesRepository()


@pytest.fixture
def encryption_key(monkeypatch) -> str:
    """A real Fernet key wired into settings, with the module's cached cipher reset."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "BROWSER_STATE_ENCRYPTION_KEY", key, raising=False)
    monkeypatch.setattr(storage_persistence, "_cipher", None)
    yield key
    monkeypatch.setattr(storage_persistence, "_cipher", None)


class TestBrowserProfilesRepository:
    async def test_get_for_domain_is_none_before_any_write(self, repo):
        assert await repo.get_for_domain(f"u-{uuid.uuid4().hex}", "example.com") is None

    async def test_upsert_creates_then_replaces_blob(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(user, "example.com", "blob-1")
        first = await repo.get_for_domain(user, "example.com")
        assert first is not None
        assert first.storage_state_blob == "blob-1"
        assert first.created_at is not None

        await repo.upsert_storage_state_blob(user, "example.com", "blob-2")
        second = await repo.get_for_domain(user, "example.com")
        assert second is not None
        assert second.id == first.id  # same record, not a duplicate
        assert second.storage_state_blob == "blob-2"
        assert second.created_at == first.created_at  # $setOnInsert did not overwrite it

    async def test_profiles_are_scoped_per_user_and_domain(self, repo):
        user_a = f"u-{uuid.uuid4().hex}"
        user_b = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(user_a, "example.com", "blob-a")
        await repo.upsert_storage_state_blob(user_a, "other.com", "blob-a-other")

        assert (await repo.get_for_domain(user_a, "other.com")).storage_state_blob == "blob-a-other"
        assert await repo.get_for_domain(user_b, "example.com") is None

    async def test_delete_for_user_scoped_to_domain(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(user, "example.com", "blob-1")
        await repo.upsert_storage_state_blob(user, "other.com", "blob-2")

        deleted = await repo.delete_for_user(user, "example.com")
        assert deleted == 1
        assert await repo.get_for_domain(user, "example.com") is None
        assert await repo.get_for_domain(user, "other.com") is not None

    async def test_delete_for_user_without_domain_deletes_all(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(user, "example.com", "blob-1")
        await repo.upsert_storage_state_blob(user, "other.com", "blob-2")

        deleted = await repo.delete_for_user(user)
        assert deleted == 2
        assert await repo.get_for_domain(user, "example.com") is None
        assert await repo.get_for_domain(user, "other.com") is None

    async def test_upsert_records_provenance_when_given(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(
            user,
            "example.com",
            "blob-1",
            BrowserLoginProvenance(source="import", source_browser="Arc", source_ip="203.0.113.7"),
        )
        doc = await repo.get_for_domain(user, "example.com")
        assert doc is not None
        assert doc.source == "import"
        assert doc.source_browser == "Arc"
        assert doc.source_ip == "203.0.113.7"

    async def test_task_end_save_does_not_clobber_import_provenance(self, repo):
        # A later browsing-acquired save (provenance=None) must not wipe the
        # provenance an earlier import stamped on the same host.
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert_storage_state_blob(
            user,
            "example.com",
            "blob-1",
            BrowserLoginProvenance(source="import", source_browser="Arc", source_ip="203.0.113.7"),
        )
        await repo.upsert_storage_state_blob(user, "example.com", "blob-2")

        doc = await repo.get_for_domain(user, "example.com")
        assert doc is not None
        assert doc.storage_state_blob == "blob-2"
        assert doc.source == "import"
        assert doc.source_browser == "Arc"
        assert doc.source_ip == "203.0.113.7"


class TestStoragePersistence:
    """Round-trips through the encryption layer, against the real repository."""

    async def test_save_then_load_round_trips_and_encrypts_at_rest(
        self, repo, raw_collection, encryption_key
    ):
        user = f"u-{uuid.uuid4().hex}"
        domain = "example.com"
        state = {
            "cookies": [{"name": "session", "value": "s3cr3t-token", "domain": domain}],
            "origins": [
                {"origin": f"https://{domain}", "localStorage": [{"name": "k", "value": "v"}]}
            ],
        }

        await storage_persistence.save_storage_state(user, domain, state)

        raw_doc = await raw_collection.find_one({"user_id": user, "domain": domain})
        assert raw_doc is not None
        blob = raw_doc["storage_state_blob"]
        assert isinstance(blob, str)
        assert (
            "s3cr3t-token" not in blob
        )  # encryption actually happened, not stored as plaintext JSON

        loaded = await storage_persistence.load_storage_state(user, domain)
        assert loaded == state

    async def test_load_is_none_when_nothing_saved(self, raw_collection, encryption_key):
        assert (
            await storage_persistence.load_storage_state(f"u-{uuid.uuid4().hex}", "example.com")
            is None
        )

    async def test_load_and_save_no_op_without_domain(self, repo, encryption_key):
        user = f"u-{uuid.uuid4().hex}"
        assert await storage_persistence.load_storage_state(user, None) is None
        await storage_persistence.save_storage_state(user, None, {"cookies": [], "origins": []})
        assert await repo.get_for_domain(user, "example.com") is None

    async def test_save_respects_persist_opt_out(self, repo, encryption_key, monkeypatch):
        monkeypatch.setattr(settings, "BROWSER_PERSIST_LOGINS", False, raising=False)
        user = f"u-{uuid.uuid4().hex}"
        await storage_persistence.save_storage_state(
            user, "example.com", {"cookies": [], "origins": []}
        )
        assert await repo.get_for_domain(user, "example.com") is None

    async def test_forget_browser_logins_deletes_saved_state(self, raw_collection, encryption_key):
        user = f"u-{uuid.uuid4().hex}"
        await storage_persistence.save_storage_state(
            user, "example.com", {"cookies": [], "origins": []}
        )
        assert await storage_persistence.load_storage_state(user, "example.com") is not None

        deleted = await storage_persistence.forget_browser_logins(user, "example.com")
        assert deleted == 1
        assert await storage_persistence.load_storage_state(user, "example.com") is None
