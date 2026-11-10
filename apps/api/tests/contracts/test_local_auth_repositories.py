"""Contract tests for the self-host account stores against real Mongo.

Covers what only a real Mongo can prove: the partial unique slot index admits
one bootstrap admin but any number of slotless members, the boot migration
replaces the single-admin era's index and backfills the admin role, and invite
redemption is single-use under a race.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import uuid

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.auth import InstanceRole
from app.db.mongodb.indexes import create_local_credential_indexes, create_local_invite_indexes
from app.db.repositories.local_credentials import LocalCredentialsRepository
from app.db.repositories.local_invites import LocalInvitesRepository
from app.models.auth_models import (
    ADMIN_CREDENTIAL_SLOT,
    LocalCredentialDocument,
    LocalInviteDocument,
)
from tests.helpers import worker_mongo_db_name

LEGACY_SLOT_INDEX = "slot_1"


@pytest.fixture
async def collections(
    mongodb_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, AsyncIOMotorCollection]]:
    """Give users, auth_credentials and auth_invites their own throwaway collections."""
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        mongodb_url, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=5000
    )
    suffix = uuid.uuid4().hex
    db = client[worker_mongo_db_name()]
    colls = {
        name: db[f"contract_{name}_{suffix}"]
        for name in ("users", "auth_credentials", "auth_invites")
    }

    def accessor(name: str) -> AsyncIOMotorCollection:
        return colls[name]

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", accessor)
    monkeypatch.setattr("app.db.mongodb.indexes.get_async_collection", accessor)
    yield colls
    for coll in colls.values():
        await coll.drop()
    client.close()


def _credential(user_id: str, *, slot: str | None = None) -> LocalCredentialDocument:
    return LocalCredentialDocument(user_id=user_id, password_hash="bcrypt-hash", slot=slot)


class TestCredentialIndexes:
    async def test_one_bootstrap_admin_and_many_members(self, collections):
        await create_local_credential_indexes()
        repo = LocalCredentialsRepository()

        assert await repo.try_create(_credential("a", slot=ADMIN_CREDENTIAL_SLOT)) is not None
        assert await repo.try_create(_credential("b", slot=ADMIN_CREDENTIAL_SLOT)) is None
        await repo.create(_credential("m1"))
        await repo.create(_credential("m2"))

        assert await repo.admin_exists() is True
        assert [c.user_id for c in await repo.list_all()] == ["a", "m1", "m2"]
        stored_member = await collections["auth_credentials"].find_one({"user_id": "m1"})
        assert stored_member is not None and "slot" not in stored_member

    async def test_no_credential_means_no_admin(self, collections):
        assert await LocalCredentialsRepository().admin_exists() is False

    async def test_accounts_list_oldest_first_whatever_the_insert_order(self, collections):
        repo = LocalCredentialsRepository()
        now = datetime.now(UTC)
        for user_id, age in (("newest", 1), ("oldest", 3), ("middle", 2)):
            await repo.create(
                _credential(user_id).model_copy(update={"created_at": now - timedelta(days=age)})
            )

        assert [c.user_id for c in await repo.list_all()] == ["oldest", "middle", "newest"]

    async def test_racing_bootstrap_claims_admit_one(self, collections):
        await create_local_credential_indexes()
        repo = LocalCredentialsRepository()
        outcomes = await asyncio.gather(
            *(repo.try_create(_credential(f"u{i}", slot=ADMIN_CREDENTIAL_SLOT)) for i in range(5))
        )
        assert sum(o is not None for o in outcomes) == 1

    async def test_boot_replaces_the_single_admin_index_and_backfills_the_role(self, collections):
        """An instance from the single-admin era boots into multi-member shape, twice over."""
        creds = collections["auth_credentials"]
        users = collections["users"]
        await creds.create_index("slot", unique=True)
        admin_id = ObjectId()
        await users.insert_one({"_id": admin_id, "email": "admin@gaia.dev"})
        await creds.insert_one(
            {"user_id": str(admin_id), "password_hash": "h", "slot": ADMIN_CREDENTIAL_SLOT}
        )

        await create_local_credential_indexes()
        await create_local_credential_indexes()

        slot_indexes = [i async for i in creds.list_indexes() if dict(i["key"]) == {"slot": 1}]
        assert len(slot_indexes) == 1
        assert slot_indexes[0]["partialFilterExpression"] == {"slot": {"$exists": True}}
        stored = await users.find_one({"_id": admin_id})
        assert stored is not None and stored["role"] == InstanceRole.ADMIN.value
        repo = LocalCredentialsRepository()
        await repo.create(_credential("m1"))
        await repo.create(_credential("m2"))

    async def test_backfill_never_overwrites_a_stored_role(self, collections):
        users = collections["users"]
        admin_id = ObjectId()
        await users.insert_one({"_id": admin_id, "role": InstanceRole.MEMBER.value})
        await collections["auth_credentials"].insert_one(
            {"user_id": str(admin_id), "password_hash": "h", "slot": ADMIN_CREDENTIAL_SLOT}
        )

        await create_local_credential_indexes()

        stored = await users.find_one({"_id": admin_id})
        assert stored is not None and stored["role"] == InstanceRole.MEMBER.value

    async def test_no_admin_means_no_backfill(self, collections):
        await create_local_credential_indexes()
        assert await collections["users"].count_documents({}) == 0


class TestInvites:
    @pytest.fixture
    async def repo(self, collections) -> LocalInvitesRepository:
        await create_local_invite_indexes()
        return LocalInvitesRepository()

    @staticmethod
    def _invite(token_hash: str, *, expires_in: timedelta) -> LocalInviteDocument:
        return LocalInviteDocument(
            token_hash=token_hash,
            created_by="admin",
            expires_at=datetime.now(UTC) + expires_in,
        )

    async def test_an_invite_is_redeemed_once(self, repo):
        await repo.create(self._invite("h1", expires_in=timedelta(days=1)))
        now = datetime.now(UTC)

        first = await repo.redeem("h1", now, "member")
        assert first is not None and first.used_at is not None
        assert first.used_by == "member"
        assert await repo.redeem("h1", now, "member") is None

    async def test_finding_a_live_invite_does_not_spend_it(self, repo):
        await repo.create(self._invite("peek", expires_in=timedelta(days=1)))
        await repo.create(self._invite("stale", expires_in=timedelta(seconds=-1)))
        now = datetime.now(UTC)

        found = await repo.find_redeemable("peek", now)
        assert found is not None and found.used_at is None
        assert await repo.find_redeemable("stale", now) is None
        assert await repo.redeem("peek", now, "member") is not None
        assert await repo.find_redeemable("peek", now) is None

    async def test_racing_redemptions_admit_one(self, repo):
        await repo.create(self._invite("race", expires_in=timedelta(days=1)))
        now = datetime.now(UTC)
        outcomes = await asyncio.gather(*(repo.redeem("race", now, "member") for _ in range(5)))
        assert sum(o is not None for o in outcomes) == 1

    async def test_expired_and_revoked_invites_cannot_be_redeemed(self, repo):
        await repo.create(self._invite("old", expires_in=timedelta(seconds=-1)))
        live = await repo.create(self._invite("live", expires_in=timedelta(days=1)))
        now = datetime.now(UTC)

        assert await repo.revoke(live.id, now) is True
        assert await repo.revoke(live.id, now) is False
        assert await repo.redeem("old", now, "member") is None
        assert await repo.redeem("live", now, "member") is None

    async def test_pending_lists_only_redeemable_invites(self, repo):
        await repo.create(self._invite("expired", expires_in=timedelta(seconds=-1)))
        await repo.create(self._invite("used", expires_in=timedelta(days=1)))
        revoked = await repo.create(self._invite("revoked", expires_in=timedelta(days=1)))
        pending = await repo.create(self._invite("pending", expires_in=timedelta(days=1)))
        now = datetime.now(UTC)
        await repo.redeem("used", now, "member")
        await repo.revoke(revoked.id, now)

        assert [i.id for i in await repo.list_pending(now)] == [pending.id]

    async def test_pending_invites_list_newest_first_whatever_the_insert_order(self, repo):
        now = datetime.now(UTC)
        for token_hash, age in (("middle", 2), ("newest", 1), ("oldest", 3)):
            await repo.create(
                self._invite(token_hash, expires_in=timedelta(days=1)).model_copy(
                    update={"created_at": now - timedelta(days=age)}
                )
            )

        assert [i.token_hash for i in await repo.list_pending(now)] == [
            "newest",
            "middle",
            "oldest",
        ]

    async def test_a_used_invite_cannot_be_revoked(self, repo):
        invite = await repo.create(self._invite("h", expires_in=timedelta(days=1)))
        await repo.redeem("h", datetime.now(UTC), "member")
        assert await repo.revoke(invite.id, datetime.now(UTC)) is False
        assert await repo.revoke("not-an-object-id", datetime.now(UTC)) is False

    async def test_two_invites_never_share_a_digest(self, repo):
        await repo.create(self._invite("same", expires_in=timedelta(days=1)))
        with pytest.raises(DuplicateKeyError):
            await repo.create(self._invite("same", expires_in=timedelta(days=1)))
