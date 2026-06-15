"""
Referral lifecycle service.

The referral domain's business logic: generating and customising referral codes,
attributing signups, sending email invites, building the hub overview, and the
status transitions (signed-up → activated → upgraded → renewed → reverted) that
drive the reward ledger via ``reward_service``.

All functions are async module-level functions; there are no service classes.
Reward/Dodo specifics live in ``reward_service``; pure economics live in
``points_service``.
"""

from datetime import UTC, datetime, timedelta
import re
import secrets

from bson import ObjectId
from pymongo import ReturnDocument

from app.config.settings import settings
from app.constants.referrals import (
    FRIEND_DISCOUNT_CYCLES,
    MAX_INVITES_PER_DAY,
    MAX_INVITES_PER_REQUEST,
    REFERRAL_CODE_ALPHABET,
    REFERRAL_CODE_MAX_LENGTH,
    REFERRAL_CODE_MIN_LENGTH,
    REFERRAL_CODE_PATTERN,
    REFERRAL_CODE_RANDOM_SUFFIX_LENGTH,
    REFUND_CLAWBACK_WINDOW_DAYS,
    RESERVED_REFERRAL_CODES,
)
from app.db.mongodb.collections import (
    plans_collection,
    referral_rewards_collection,
    referrals_collection,
    users_collection,
)
from app.models.referral_models import (
    ReferralChannel,
    ReferralRewardStatus,
    ReferralStatus,
)
from app.schemas.referral_schemas import (
    EarnedReward,
    FriendReferral,
    InviteResponse,
    MilestoneState,
    ReferralMeResponse,
    ReferralStats,
    ResolveCodeResponse,
    UpdateCodeResponse,
)
from app.services.referrals import points_service, reward_service
from app.utils.email_utils import normalize_email, send_referral_invite_email
from app.utils.errors import create_error
from shared.py.wide_events import log

_CODE_REGEX = re.compile(REFERRAL_CODE_PATTERN)
_DEFAULT_OFFER_LABEL = "50% off your first 2 months of GAIA PRO"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def share_link(code: str) -> str:
    """Build the public invite link for a referral code."""
    return f"{settings.FRONTEND_URL}/invite/{code}"


def _slugify_name(name: str) -> str:
    """Turn a display name into a short, link-safe slug base."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    base = base[:20].strip("-")
    return base or "friend"


def _random_suffix() -> str:
    return "".join(
        secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_RANDOM_SUFFIX_LENGTH)
    )


def _mask_email(email: str) -> str:
    """Privacy-mask an email for display: ``j***@gmail.com``."""
    local, _, domain = email.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}" if domain else email


async def _friend_offer_label() -> str:
    """Human, honest friend-offer label including the $ gift value when known."""
    plan = await plans_collection.find_one({"name": "Pro", "duration": "monthly"})
    if plan and plan.get("amount"):
        # 50% off two months saves exactly one month's price — the gift value.
        gift_value = plan["amount"] / 100
        return f"50% off your first {FRIEND_DISCOUNT_CYCLES} months — a ${gift_value:.0f} gift"
    return _DEFAULT_OFFER_LABEL


# ---------------------------------------------------------------------------
# Referral codes
# ---------------------------------------------------------------------------


async def ensure_referral_code(user_id: str) -> str:
    """Return the user's referral code, generating a unique one on first access."""
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise create_error(message="User not found", status_code=404)
    if user.get("referral_code"):
        return user["referral_code"]

    base = _slugify_name(user.get("name", ""))
    for _ in range(10):
        code = f"{base}-{_random_suffix()}"
        if await users_collection.find_one({"referral_code": code}):
            continue
        updated = await users_collection.find_one_and_update(
            {
                "_id": ObjectId(user_id),
                "$or": [{"referral_code": {"$exists": False}}, {"referral_code": None}],
            },
            {"$set": {"referral_code": code, "updated_at": _now()}},
            return_document=ReturnDocument.AFTER,
        )
        if updated:
            return code
        # Another request set the code first — return whatever stuck.
        refreshed = await users_collection.find_one({"_id": ObjectId(user_id)})
        if refreshed and refreshed.get("referral_code"):
            return refreshed["referral_code"]

    raise create_error(message="Could not generate a referral code", status_code=500)


async def update_referral_code(user_id: str, new_code: str) -> UpdateCodeResponse:
    """Set a custom vanity code after validating format, reservations, uniqueness."""
    code = new_code.strip().lower()

    if not (REFERRAL_CODE_MIN_LENGTH <= len(code) <= REFERRAL_CODE_MAX_LENGTH):
        raise create_error(
            message="Invalid referral code length",
            why=f"Codes must be {REFERRAL_CODE_MIN_LENGTH}-{REFERRAL_CODE_MAX_LENGTH} characters.",
            status_code=400,
        )
    if not _CODE_REGEX.match(code):
        raise create_error(
            message="Invalid referral code",
            why="Use lowercase letters, numbers and single hyphens.",
            status_code=400,
        )
    if code in RESERVED_REFERRAL_CODES:
        raise create_error(
            message="That referral code is reserved",
            fix="Pick a different code.",
            status_code=400,
        )

    clash = await users_collection.find_one(
        {"referral_code": code, "_id": {"$ne": ObjectId(user_id)}}
    )
    if clash:
        raise create_error(
            message="That referral code is taken",
            fix="Pick a different code.",
            status_code=409,
        )

    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"referral_code": code, "updated_at": _now()}},
    )
    log.set(referral={"operation": "update_code", "code": code})
    return UpdateCodeResponse(code=code, share_link=share_link(code))


# ---------------------------------------------------------------------------
# Public resolution (landing page)
# ---------------------------------------------------------------------------


async def resolve_code(code: str) -> ResolveCodeResponse:
    """Resolve a referral code to its referrer for the invite landing page."""
    offer_label = await _friend_offer_label()
    referrer = await users_collection.find_one({"referral_code": code.strip().lower()})
    if not referrer:
        return ResolveCodeResponse(valid=False, offer_label=offer_label)
    return ResolveCodeResponse(
        valid=True,
        referrer_name=referrer.get("name"),
        referrer_picture=referrer.get("picture") or None,
        offer_label=offer_label,
    )


# ---------------------------------------------------------------------------
# Attribution + lifecycle transitions
# ---------------------------------------------------------------------------


async def record_attribution(referred_user_id: str, ref_code: str) -> str | None:
    """Attribute a newly-signed-up user to a referrer.

    Guards self-referral and already-attributed users. Converts a matching
    pending email invite when present, otherwise creates a fresh link referral.
    Returns the referrer's user id, or ``None`` when attribution is rejected.
    """
    referrer = await users_collection.find_one({"referral_code": ref_code.strip().lower()})
    if not referrer:
        return None
    referrer_id = str(referrer["_id"])
    if referrer_id == referred_user_id:
        return None  # self-referral

    if await referrals_collection.find_one({"referred_user_id": referred_user_id}):
        return None  # already attributed

    friend = await users_collection.find_one({"_id": ObjectId(referred_user_id)})
    friend_email = (friend.get("email") or "").lower() if friend else None
    now = _now()

    pending_invite = None
    if friend_email:
        pending_invite = await referrals_collection.find_one(
            {
                "referrer_user_id": referrer_id,
                "referred_email": friend_email,
                "status": ReferralStatus.INVITED.value,
            }
        )

    if pending_invite:
        await referrals_collection.update_one(
            {"_id": pending_invite["_id"]},
            {
                "$set": {
                    "referred_user_id": referred_user_id,
                    "status": ReferralStatus.SIGNED_UP.value,
                    "signed_up_at": now,
                    "updated_at": now,
                }
            },
        )
    else:
        await referrals_collection.insert_one(
            {
                "referrer_user_id": referrer_id,
                "referred_user_id": referred_user_id,
                "referred_email": friend_email,
                "status": ReferralStatus.SIGNED_UP.value,
                "channel": ReferralChannel.LINK.value,
                "points_awarded": 0,
                "friend_discount_code": None,
                "invited_at": None,
                "clicked_at": None,
                "signed_up_at": now,
                "activated_at": None,
                "upgraded_at": None,
                "renewed_at": None,
                "reverted_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )

    await users_collection.update_one(
        {"_id": ObjectId(referred_user_id)},
        {"$set": {"referred_by_user_id": referrer_id, "updated_at": now}},
    )
    log.set(referral={"operation": "attribute", "referrer_id": referrer_id})
    return referrer_id


async def _transition(
    referred_user_id: str,
    from_states: list[str],
    to_state: ReferralStatus,
    timestamp_field: str,
) -> None:
    """Move a friend's referral to ``to_state`` and re-sync the referrer's rewards.

    Idempotent: only matches when the referral is in one of ``from_states``, so
    repeated webhooks are no-ops.
    """
    now = _now()
    updated = await referrals_collection.find_one_and_update(
        {"referred_user_id": referred_user_id, "status": {"$in": from_states}},
        {"$set": {"status": to_state.value, timestamp_field: now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        await reward_service.sync_rewards(updated["referrer_user_id"])


async def record_activation(referred_user_id: str) -> None:
    """Mark a referred friend as activated (reached real-usage threshold)."""
    await _transition(
        referred_user_id,
        [ReferralStatus.SIGNED_UP.value],
        ReferralStatus.ACTIVATED,
        "activated_at",
    )


async def record_upgrade(referred_user_id: str) -> None:
    """Mark a referred friend as upgraded to PRO (the revenue conversion)."""
    await _transition(
        referred_user_id,
        [ReferralStatus.SIGNED_UP.value, ReferralStatus.ACTIVATED.value],
        ReferralStatus.UPGRADED,
        "upgraded_at",
    )


async def record_renewal(referred_user_id: str) -> None:
    """Mark a referred friend's first PRO renewal (retention bonus)."""
    await _transition(
        referred_user_id,
        [ReferralStatus.UPGRADED.value],
        ReferralStatus.RENEWED,
        "renewed_at",
    )


async def revert_referral(referred_user_id: str) -> None:
    """Clawback: a refund/chargeback inside the window reverts the conversion.

    Once a conversion survives ``REFUND_CLAWBACK_WINDOW_DAYS`` the reward is
    locked in, so a late refund does not strip the referrer's earned months.
    """
    referral = await referrals_collection.find_one(
        {
            "referred_user_id": referred_user_id,
            "status": {"$in": [ReferralStatus.UPGRADED.value, ReferralStatus.RENEWED.value]},
        }
    )
    if not referral:
        return

    upgraded_at = referral.get("upgraded_at")
    if upgraded_at and not is_within_clawback_window(upgraded_at, REFUND_CLAWBACK_WINDOW_DAYS):
        log.info(f"Refund for {referred_user_id} is outside the clawback window; reward stays")
        return

    await _transition(
        referred_user_id,
        [ReferralStatus.UPGRADED.value, ReferralStatus.RENEWED.value],
        ReferralStatus.REVERTED,
        "reverted_at",
    )


async def get_pending_friend_discount(user_id: str) -> str | None:
    """Return a friend's pre-applied discount code if they were referred.

    Called at checkout so the friend's 50%-off code is applied automatically with
    nothing to type. Mints the code lazily on first checkout.
    """
    referral = await referrals_collection.find_one(
        {
            "referred_user_id": user_id,
            "status": {"$in": [ReferralStatus.SIGNED_UP.value, ReferralStatus.ACTIVATED.value]},
        }
    )
    if not referral:
        return None
    return await reward_service.mint_friend_discount(referral)


# ---------------------------------------------------------------------------
# Email invites
# ---------------------------------------------------------------------------


async def send_invites(user_id: str, emails: list[str]) -> InviteResponse:
    """Send referral invite emails, deduping and rate-limiting; report outcomes."""
    code = await ensure_referral_code(user_id)
    referrer = await users_collection.find_one({"_id": ObjectId(user_id)})
    referrer_name = (referrer.get("name") if referrer else None) or "A friend"
    referrer_picture = (referrer.get("picture") if referrer else None) or None
    link = share_link(code)
    offer_label = await _friend_offer_label()

    # Daily cap: how many invites already sent today by this referrer.
    day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = await referrals_collection.count_documents(
        {
            "referrer_user_id": user_id,
            "channel": ReferralChannel.EMAIL.value,
            "invited_at": {"$gte": day_start},
        }
    )
    remaining_today = max(0, MAX_INVITES_PER_DAY - sent_today)

    sent: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    for raw in emails[:MAX_INVITES_PER_REQUEST]:
        addr = normalize_email(raw)
        if not addr or addr in seen:
            skipped.append(raw)
            continue
        seen.add(addr)

        # Don't invite existing users or anyone this referrer already invited.
        if await users_collection.find_one({"email": addr}):
            skipped.append(addr)
            continue
        if await referrals_collection.find_one(
            {"referrer_user_id": user_id, "referred_email": addr}
        ):
            skipped.append(addr)
            continue
        if len(sent) >= remaining_today:
            skipped.append(addr)
            continue

        now = _now()
        await referrals_collection.insert_one(
            {
                "referrer_user_id": user_id,
                "referred_user_id": None,
                "referred_email": addr,
                "status": ReferralStatus.INVITED.value,
                "channel": ReferralChannel.EMAIL.value,
                "points_awarded": 0,
                "friend_discount_code": None,
                "invited_at": now,
                "clicked_at": None,
                "signed_up_at": None,
                "activated_at": None,
                "upgraded_at": None,
                "renewed_at": None,
                "reverted_at": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        try:
            await send_referral_invite_email(
                to_email=addr,
                referrer_name=referrer_name,
                referrer_picture=referrer_picture,
                invite_link=link,
                offer_label=offer_label,
            )
            sent.append(addr)
        except Exception as e:  # noqa: BLE001 - report, don't fail the batch
            log.error(f"Failed to send referral invite to {addr}: {e!s}")
            skipped.append(addr)

    log.set(referral={"operation": "invite", "sent": len(sent), "skipped": len(skipped)})
    return InviteResponse(sent=sent, skipped=skipped)


# ---------------------------------------------------------------------------
# Hub overview
# ---------------------------------------------------------------------------


async def get_my_referral_overview(user_id: str) -> ReferralMeResponse:
    """Assemble everything the hub and corner bar render for the current user."""
    code = await ensure_referral_code(user_id)
    points = await reward_service.compute_points(user_id)
    goal = points_service.next_goal(points)
    ladder = [
        MilestoneState(
            threshold=int(m["threshold"]),
            reward_months=int(m["reward_months"]),
            cumulative_months=int(m["cumulative_months"]),
            status=str(m["status"]),
        )
        for m in points_service.build_ladder(points)
    ]

    invited, joined, upgraded = await _referral_counts(user_id)
    stats = ReferralStats(
        invited=invited,
        joined=joined,
        upgraded=upgraded,
        months_earned=points_service.total_earned_months(points),
    )

    friends = await _friend_list(user_id)
    rewards = await _earned_rewards(user_id)

    return ReferralMeResponse(
        code=code,
        share_link=share_link(code),
        points=points,
        points_into_current_goal=int(goal["points_into_current"]),
        next_goal_threshold=int(goal["threshold"]),
        next_goal_reward_months=int(goal["reward_months"]),
        progress_pct=float(goal["progress_pct"]),
        ladder=ladder,
        stats=stats,
        friends=friends,
        rewards=rewards,
    )


async def _referral_counts(user_id: str) -> tuple[int, int, int]:
    """``(invited_total, joined, upgraded)`` headline counts for the hub."""
    joined_states = [
        ReferralStatus.SIGNED_UP.value,
        ReferralStatus.ACTIVATED.value,
        ReferralStatus.UPGRADED.value,
        ReferralStatus.RENEWED.value,
    ]
    upgraded_states = [ReferralStatus.UPGRADED.value, ReferralStatus.RENEWED.value]
    return (
        await _count(user_id, None),
        await _count(user_id, joined_states),
        await _count(user_id, upgraded_states),
    )


async def _count(user_id: str, states: list[str] | None) -> int:
    query: dict[str, object] = {"referrer_user_id": user_id}
    if states is not None:
        query["status"] = {"$in": states}
    return await referrals_collection.count_documents(query)


async def _friend_list(user_id: str, limit: int = 100) -> list[FriendReferral]:
    """Recent referred friends with privacy-aware display names."""
    docs = (
        await referrals_collection.find({"referrer_user_id": user_id})
        .sort("created_at", -1)
        .to_list(limit)
    )

    user_ids = [ObjectId(d["referred_user_id"]) for d in docs if d.get("referred_user_id")]
    name_by_id: dict[str, str] = {}
    if user_ids:
        async for u in users_collection.find({"_id": {"$in": user_ids}}, {"name": 1, "email": 1}):
            name_by_id[str(u["_id"])] = u.get("name") or _mask_email(u.get("email", ""))

    friends: list[FriendReferral] = []
    for d in docs:
        referred_id = d.get("referred_user_id")
        if referred_id and referred_id in name_by_id:
            display = name_by_id[referred_id]
        elif d.get("referred_email"):
            display = _mask_email(d["referred_email"])
        else:
            display = "Friend"
        friends.append(
            FriendReferral(
                display=display,
                status=ReferralStatus(d["status"]),
                channel=ReferralChannel(d.get("channel", ReferralChannel.LINK.value)),
                created_at=d["created_at"],
                upgraded_at=d.get("upgraded_at"),
            )
        )
    return friends


async def _earned_rewards(user_id: str) -> list[EarnedReward]:
    """Granted milestone rewards (free months) and their redemption codes."""
    docs = (
        await referral_rewards_collection.find(
            {
                "referrer_user_id": user_id,
                "status": ReferralRewardStatus.GRANTED.value,
            }
        )
        .sort("granted_at", -1)
        .to_list(None)
    )
    return [
        EarnedReward(
            months_granted=d["months_granted"],
            milestone_threshold=d["milestone_threshold"],
            discount_code=d.get("dodo_discount_code"),
            status=d["status"],
            granted_at=d["granted_at"],
        )
        for d in docs
    ]


# Kept for symmetry with the clawback window constant; used by callers that need
# to know whether a conversion is still inside the refund window.
def is_within_clawback_window(upgraded_at: datetime, window_days: int) -> bool:
    """True if ``upgraded_at`` is still inside the clawback window."""
    return _now() - upgraded_at <= timedelta(days=window_days)
