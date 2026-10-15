"""Repository for the auth_invites collection: single-use self-host invite links.

Global, not user-scoped: an invite is redeemed by someone who has no account
yet. Redemption is one atomic find-and-update on the token digest, so two
signups presenting the same link cannot both win it.
"""

from datetime import datetime

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.auth_models import LocalInviteDocument, LocalInviteUpdate


def _redeemable(token_hash: str, now: datetime) -> dict[str, object]:
    return {
        "token_hash": token_hash,
        "used_at": None,
        "revoked_at": None,
        "expires_at": {"$gt": now},
    }


class LocalInvitesRepository(MongoRepository[LocalInviteDocument, LocalInviteUpdate]):
    collection_name = "auth_invites"
    document_model = LocalInviteDocument
    update_model = LocalInviteUpdate
    uses_object_id = True
    cache_policy = None

    async def list_pending(self, now: datetime) -> list[LocalInviteDocument]:
        """Invites that can still be redeemed, newest first."""
        return await self._find(
            {"used_at": None, "revoked_at": None, "expires_at": {"$gt": now}},
            sort=[("created_at", -1)],
        )

    async def find_redeemable(self, token_hash: str, now: datetime) -> LocalInviteDocument | None:
        """Look up a live invite without spending it; None when unknown, used, revoked or expired."""
        return await self._find_one(_redeemable(token_hash, now))

    async def redeem(
        self, token_hash: str, now: datetime, used_by: str
    ) -> LocalInviteDocument | None:
        """Atomically mark a live invite used by an account; None when unknown, used, revoked or expired."""
        return await self._apply_raw_update(
            _redeemable(token_hash, now),
            {"$set": {"used_at": now, "used_by": used_by}},
            scope=REPO_GLOBAL_SCOPE,  # pragma: no mutate — a cacheless global repo never reads its scope
        )

    async def revoke(self, invite_id: str, now: datetime) -> bool:
        """Revoke an unused invite; False when it does not exist or was already used or revoked."""
        if not self.is_valid_id(invite_id):
            return False
        revoked = await self._apply_raw_update(
            {**self._identity_filter(invite_id), "used_at": None, "revoked_at": None},
            {"$set": {"revoked_at": now}},
            scope=REPO_GLOBAL_SCOPE,  # pragma: no mutate — a cacheless global repo never reads its scope
        )
        return revoked is not None


local_invites_repository = LocalInvitesRepository()
