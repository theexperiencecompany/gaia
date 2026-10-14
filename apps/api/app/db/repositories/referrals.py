"""Repository for the referrals collection: one row per referred friend.

Keyed by friend_user_id (unique), because a person is referred at most once:
the first link they signed up through wins. The atomic transitions below are
what make conversion and reward delivery idempotent under webhook retries.
"""

from datetime import datetime

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.payment_models import PlanDuration
from app.models.referral_models import (
    ReferralDocument,
    ReferralRewardState,
    ReferralUpdate,
    ReferredFriendStatus,
)


class ReferralsRepository(MongoRepository[ReferralDocument, ReferralUpdate]):
    collection_name = "referrals"
    document_model = ReferralDocument
    update_model = ReferralUpdate
    uses_object_id = True
    identity_field = "friend_user_id"
    cache_policy = None

    async def attribute(self, referral: ReferralDocument) -> ReferralDocument | None:
        """Record the friend's referrer; None when the friend already has one."""
        try:
            return await self.create(referral)
        except DuplicateKeyError:
            return None

    async def list_for_referrer(self, referrer_user_id: str) -> list[ReferralDocument]:
        """Return everyone this referrer brought in, newest first."""
        return await self._find({"referrer_user_id": referrer_user_id}, sort=[("joined_at", -1)])

    async def list_banked(self, referrer_user_id: str) -> list[ReferralDocument]:
        """Return the referrer's months still waiting for an active subscription, oldest first."""
        return await self._find(
            {
                "referrer_user_id": referrer_user_id,
                "reward_state": ReferralRewardState.BANKED.value,
            },
            sort=[("paid_at", 1)],
        )

    async def mark_paid(
        self, friend_user_id: str, *, payment_id: str, paid_at: datetime
    ) -> ReferralDocument | None:
        """Move a joined friend to paid with a pending reward; None when they were not joined."""
        joined = {"friend_user_id": friend_user_id, "status": ReferredFriendStatus.JOINED.value}
        paid = {
            "$set": {
                "status": ReferredFriendStatus.PAID.value,
                "paid_at": paid_at,
                "payment_id": payment_id,
                "reward_state": ReferralRewardState.PENDING.value,
            }
        }
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        return await self._apply_raw_update(joined, paid, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end

    async def set_gift_code(
        self, friend_user_id: str, duration: PlanDuration, code: str
    ) -> ReferralDocument | None:
        """Store the friend's gift code for this cycle unless one is there; returns the row as it stands.

        A caller that lost a mint race reads the winner's code back; None only
        when the friend has no referral at all.
        """
        field = f"gift_codes.{duration.value}"
        unset = {"friend_user_id": friend_user_id, field: {"$exists": False}}
        store = {"$set": {field: code}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        stored = await self._apply_raw_update(unset, store, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end
        return stored if stored is not None else await self.get(friend_user_id)

    async def set_reward_target_if_unset(
        self, friend_user_id: str, target: datetime
    ) -> ReferralDocument | None:
        """Pin the billing date this reward moves the referrer to, once; a retry reads the pinned one."""
        unpinned = {"friend_user_id": friend_user_id, "reward_target_billing_date": None}
        pin = {"$set": {"reward_target_billing_date": target}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        stored = await self._apply_raw_update(unpinned, pin, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end
        return stored if stored is not None else await self.get(friend_user_id)


referral_repository = ReferralsRepository()
