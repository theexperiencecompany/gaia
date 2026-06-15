"""
Referral reward service.

Owns the money-touching side of the program: minting Dodo discount codes (the
friend's 50%-off code and the referrer's 100%-off reward codes) and keeping the
``referral_rewards`` ledger in sync with a referrer's points. All Dodo specifics
are isolated here so the one open mechanism (delivering an active-subscription
free month) can evolve in a single place.

Idempotency: rewards are anchored by a unique ``(referrer_user_id,
milestone_threshold)`` index, so re-running ``sync_rewards`` (e.g. on a Dodo
webhook retry) never double-grants.
"""

import asyncio
from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from app.constants.referrals import (
    DISCOUNT_USAGE_LIMIT,
    FRIEND_DISCOUNT_BASIS_POINTS,
    FRIEND_DISCOUNT_CYCLES,
    REFERRER_REWARD_BASIS_POINTS,
)
from app.db.mongodb.collections import (
    plans_collection,
    referral_rewards_collection,
    referrals_collection,
)
from app.models.referral_models import (
    ReferralRewardStatus,
    ReferralStatus,
)
from app.services.payments.payment_service import payment_service
from app.services.referrals import points_service
from shared.py.wide_events import log

# Referral statuses that imply the friend has reached each points-bearing tier.
_ACTIVATED_STATES = [
    ReferralStatus.ACTIVATED.value,
    ReferralStatus.UPGRADED.value,
    ReferralStatus.RENEWED.value,
]
_UPGRADED_STATES = [ReferralStatus.UPGRADED.value, ReferralStatus.RENEWED.value]
_RENEWED_STATES = [ReferralStatus.RENEWED.value]


async def _get_pro_product_id() -> str | None:
    """Resolve the PRO plan's Dodo product id, to scope discounts to PRO only."""
    plan = await plans_collection.find_one({"name": "Pro"})
    if plan:
        return plan.get("dodo_product_id")
    return None


async def _create_discount(
    *,
    amount_basis_points: int,
    subscription_cycles: int,
    name: str,
    restricted_to: list[str] | None,
) -> tuple[str, str] | None:
    """Create a single-use percentage discount in Dodo; return ``(code, id)``.

    Dodo's SDK is synchronous, so the call is offloaded to a thread to avoid
    blocking the event loop. Returns ``None`` if the client is unavailable.
    """
    client = getattr(payment_service, "client", None)
    if client is None:
        log.error("Dodo client unavailable; cannot mint referral discount")
        return None

    kwargs: dict[str, object] = {
        "amount": amount_basis_points,
        "type": "percentage",
        "subscription_cycles": subscription_cycles,
        "usage_limit": DISCOUNT_USAGE_LIMIT,
        "name": name,
    }
    if restricted_to:
        kwargs["restricted_to"] = restricted_to

    discount = await asyncio.to_thread(client.discounts.create, **kwargs)
    return discount.code, discount.discount_id


async def mint_friend_discount(referral: dict) -> str | None:
    """Ensure a unique friend discount exists for a referral; return its code.

    Idempotent — returns the existing code if one was already minted. The friend
    gets 50% off their first ``FRIEND_DISCOUNT_CYCLES`` billing cycles, applied
    automatically at checkout.
    """
    existing_code = referral.get("friend_discount_code")
    if existing_code:
        return existing_code

    pro_product_id = await _get_pro_product_id()
    result = await _create_discount(
        amount_basis_points=FRIEND_DISCOUNT_BASIS_POINTS,
        subscription_cycles=FRIEND_DISCOUNT_CYCLES,
        name=f"Referral gift · {referral.get('referrer_user_id', 'unknown')}",
        restricted_to=[pro_product_id] if pro_product_id else None,
    )
    if result is None:
        return None

    code, _discount_id = result
    await referrals_collection.update_one(
        {"_id": referral["_id"]},
        {"$set": {"friend_discount_code": code, "updated_at": datetime.now(UTC)}},
    )
    log.info(f"Minted friend referral discount {code}")
    return code


async def count_referral_events(referrer_user_id: str) -> tuple[int, int, int]:
    """Return ``(activation_count, upgrade_count, renewal_count)`` for a referrer.

    Reverted referrals contribute nothing. Because the status enum is monotonic,
    a friend at a higher tier also counts toward every lower tier.
    """
    activation_count, upgrade_count, renewal_count = await asyncio.gather(
        referrals_collection.count_documents(
            {"referrer_user_id": referrer_user_id, "status": {"$in": _ACTIVATED_STATES}}
        ),
        referrals_collection.count_documents(
            {"referrer_user_id": referrer_user_id, "status": {"$in": _UPGRADED_STATES}}
        ),
        referrals_collection.count_documents(
            {"referrer_user_id": referrer_user_id, "status": {"$in": _RENEWED_STATES}}
        ),
    )
    return activation_count, upgrade_count, renewal_count


async def compute_points(referrer_user_id: str) -> int:
    """Current total points for a referrer, derived from live referral state."""
    activation_count, upgrade_count, renewal_count = await count_referral_events(referrer_user_id)
    return points_service.total_points(activation_count, upgrade_count, renewal_count)


async def _grant_milestone(referrer_user_id: str, threshold: int, reward_months: int) -> None:
    """Grant one milestone reward: mint a 100%-off code and ledger it once.

    The unique ledger index makes this safe under concurrent/retried calls — a
    duplicate insert is swallowed and the (already minted) state stands.
    """
    pro_product_id = await _get_pro_product_id()
    result = await _create_discount(
        amount_basis_points=REFERRER_REWARD_BASIS_POINTS,
        subscription_cycles=reward_months,
        name=f"Referral reward · {referrer_user_id} · {threshold}pts",
        restricted_to=[pro_product_id] if pro_product_id else None,
    )
    code, discount_id = result if result else (None, None)

    try:
        await referral_rewards_collection.insert_one(
            {
                "referrer_user_id": referrer_user_id,
                "milestone_threshold": threshold,
                "months_granted": reward_months,
                "dodo_discount_code": code,
                "dodo_discount_id": discount_id,
                "status": ReferralRewardStatus.GRANTED.value,
                "granted_at": datetime.now(UTC),
                "reverted_at": None,
            }
        )
        log.info(
            f"Granted referral milestone {threshold} ({reward_months}mo) to {referrer_user_id}"
        )
    except DuplicateKeyError:
        # Another concurrent sync already granted this milestone. If we minted a
        # now-orphaned code, delete it so we don't leak a redeemable discount.
        if discount_id:
            await _safe_delete_discount(discount_id)


async def _safe_delete_discount(discount_id: str) -> None:
    """Best-effort delete of a Dodo discount; never raises."""
    client = getattr(payment_service, "client", None)
    if client is None:
        return
    try:
        await asyncio.to_thread(client.discounts.delete, discount_id)
    except Exception as e:  # noqa: BLE001 - best-effort cleanup
        log.warning(f"Failed to delete orphaned discount {discount_id}: {e}")


async def sync_rewards(referrer_user_id: str) -> None:
    """Reconcile a referrer's ledger with their current points.

    Grants any milestone now reached but not yet ledgered, and reverts any
    previously-granted milestone that is no longer reached (clawback). Safe to
    call after every referral status change.
    """
    points = await compute_points(referrer_user_id)

    existing = await referral_rewards_collection.find(
        {"referrer_user_id": referrer_user_id}
    ).to_list(None)
    granted_thresholds = {
        r["milestone_threshold"]
        for r in existing
        if r.get("status") == ReferralRewardStatus.GRANTED.value
    }

    # Grant newly-reached milestones (idempotent via the unique index).
    for milestone in points_service.build_ladder(points):
        if milestone["status"] == "done" and milestone["threshold"] not in granted_thresholds:
            await _grant_milestone(
                referrer_user_id,
                int(milestone["threshold"]),
                int(milestone["reward_months"]),
            )

    # Revert milestones that are no longer reached (refund/chargeback pulled
    # the referrer back below the threshold).
    for reward in existing:
        if (
            reward.get("status") == ReferralRewardStatus.GRANTED.value
            and reward["milestone_threshold"] > points
        ):
            await referral_rewards_collection.update_one(
                {"_id": reward["_id"]},
                {
                    "$set": {
                        "status": ReferralRewardStatus.REVERTED.value,
                        "reverted_at": datetime.now(UTC),
                    }
                },
            )
            if reward.get("dodo_discount_id"):
                await _safe_delete_discount(reward["dodo_discount_id"])
            log.info(
                f"Reverted referral milestone {reward['milestone_threshold']} "
                f"for {referrer_user_id} (points now {points})"
            )
