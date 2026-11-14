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
    ReferralRevokeReason,
    ReferralRewardState,
    ReferralUpdate,
    ReferredFriendStatus,
)

# A month that can still be granted or taken back; SELF_REFERRAL and REVOKED are final.
_REVOCABLE_STATES = [
    ReferralRewardState.PENDING.value,
    ReferralRewardState.APPLIED.value,
    ReferralRewardState.BANKED.value,
]


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

    async def list_owed(self, referrer_user_id: str) -> list[ReferralDocument]:
        """Return the referrer's rewards still owing work, oldest paid first.

        A month to grant (pending), one waiting for a subscription (banked), or
        one a refund or dispute asked back.
        """
        return await self._find(
            {
                "referrer_user_id": referrer_user_id,
                "$or": [
                    {
                        "reward_state": {
                            "$in": [
                                ReferralRewardState.PENDING.value,
                                ReferralRewardState.BANKED.value,
                            ]
                        }
                    },
                    {
                        "revoke_reason": {"$ne": None},
                        "reward_state": {"$ne": ReferralRewardState.REVOKED.value},
                    },
                ],
            },
            sort=[("paid_at", 1)],
        )

    async def list_referrers_unsettled(self, paid_before: datetime, limit: int) -> list[str]:
        """Return referrers with a month still pending for a friend who paid before the cutoff."""
        stuck = await self._find(
            {
                "reward_state": ReferralRewardState.PENDING.value,
                "paid_at": {"$lt": paid_before},
            },
            sort=[("paid_at", 1)],
            limit=limit,
        )
        return list(dict.fromkeys(referral.referrer_user_id for referral in stuck))

    async def get_by_payment_id(self, payment_id: str) -> ReferralDocument | None:
        """Return the referral this payment converted, if it was a friend's first."""
        return await self._find_one({"payment_id": payment_id})

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

    async def replace_gift_code(
        self, friend_user_id: str, duration: PlanDuration, *, refused: str, fresh: str
    ) -> ReferralDocument | None:
        """Swap a refused gift code for a fresh one unless a racing checkout already did; returns the row as it stands."""
        field = f"gift_codes.{duration.value}"
        still_refused = {"friend_user_id": friend_user_id, field: refused}
        swap = {"$set": {field: fresh}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        stored = await self._apply_raw_update(still_refused, swap, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end
        return stored if stored is not None else await self.get(friend_user_id)

    async def pin_reward_target(
        self, friend_user_id: str, *, subscription_id: str, target: datetime
    ) -> ReferralDocument | None:
        """Pin the billing date this reward moves the referrer's subscription to, once per subscription.

        A retry reads the pinned date back; a pin made against a subscription
        the referrer no longer has is replaced.
        """
        unpinned = {
            "friend_user_id": friend_user_id,
            "$or": [
                {"reward_target_billing_date": None},
                {"reward_subscription_id": {"$ne": subscription_id}},
            ],
        }
        pin = {
            "$set": {
                "reward_target_billing_date": target,
                "reward_subscription_id": subscription_id,
            }
        }
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        stored = await self._apply_raw_update(unpinned, pin, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end
        return stored if stored is not None else await self.get(friend_user_id)

    async def pin_revoke_target(
        self, friend_user_id: str, target: datetime
    ) -> ReferralDocument | None:
        """Pin the billing date taking this reward back moves the referrer to, once."""
        unpinned = {"friend_user_id": friend_user_id, "revoke_target_billing_date": None}
        pin = {"$set": {"revoke_target_billing_date": target}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        stored = await self._apply_raw_update(unpinned, pin, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end
        return stored if stored is not None else await self.get(friend_user_id)

    async def request_revocation(
        self, payment_id: str, *, reason: ReferralRevokeReason, at: datetime
    ) -> ReferralDocument | None:
        """Ask for the reward this first payment earned back; None when there is none to ask for.

        Only the first refund or dispute records; a repeat, or a payment that
        converted nobody, matches nothing.
        """
        revocable = {
            "payment_id": payment_id,
            "revoke_reason": None,
            "reward_state": {"$in": _REVOCABLE_STATES},
        }
        revoke = {"$set": {"revoke_reason": reason.value, "revoked_at": at}}
        # pragma: no mutate start — cache_policy is None, so scope keys nothing
        return await self._apply_raw_update(revocable, revoke, scope=REPO_GLOBAL_SCOPE)
        # pragma: no mutate end


referral_repository = ReferralsRepository()
