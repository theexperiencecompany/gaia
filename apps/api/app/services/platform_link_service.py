"""Platform Link Service

Centralized service for managing platform account linking (Discord, Slack, Telegram, WhatsApp).

Storage contract: platform_links.{platform} is always a dict with at minimum an "id" key
containing the platform user ID as a non-empty plain string. Optional keys: "username",
"display_name". Any document storing a non-dict value (legacy string/int) is treated as
unlinked.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.platform_links import IMESSAGE_PENDING_REGISTRATION_TTL
from app.db.repositories.pending_platform_registrations import (
    pending_platform_registration_repository,
)
from app.db.repositories.users import user_repository
from app.models.payment_models import PlanType
from app.models.platform_models import (
    DisconnectPlatformResponse,
    PlatformLinkEntry,
    PlatformLinkResult,
)
from app.models.user_models import PlatformLinkRecord, user_to_legacy_dict
from app.services.payments.payment_service import payment_service
from app.services.photon.photon_client import unregister_shared_user
from app.utils.errors import AppError, create_error
from shared.py.wide_events import log


class Platform(str, Enum):
    """Supported platforms for account linking."""

    DISCORD = "discord"
    SLACK = "slack"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    IMESSAGE = "imessage"

    @classmethod
    def is_valid(cls, platform: str) -> bool:
        """Check if platform is supported."""
        try:
            cls(platform)
            return True
        except ValueError:
            return False

    @classmethod
    def values(cls) -> list[str]:
        """Get list of all platform values."""
        return [p.value for p in cls]


PREMIUM_PLATFORMS: frozenset[str] = frozenset({Platform.IMESSAGE.value})

IMESSAGE_REGISTRATION_FEATURE_KEY = "imessage_registration"


async def _release_imessage_number(user_id: str, phone_number: str) -> bool:
    """Release the number to Photon's pool; False when Photon could not be reached.

    A Photon failure only warns: every caller has already committed the GAIA-side
    change, and the number is retried by the abandoned-registration sweep.
    """
    try:
        released = await unregister_shared_user(phone_number)
    except AppError as e:
        log.warning(
            "imessage photon unregister failed",
            user={"id": user_id},
            provider=Platform.IMESSAGE.value,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False

    if released:
        log.audit(
            "imessage number unregistered",
            actor=user_id,
            provider=Platform.IMESSAGE.value,
        )
    return True


async def register_pending_imessage_number(user_id: str, phone_number: str) -> None:
    """Record a Photon registration that is waiting for the user to text /auth.

    Swapping numbers releases the previous one: the user who mistyped their
    number and retried must not leave the first registration holding a pool seat.
    """
    pending = await pending_platform_registration_repository.get_for_user(
        user_id, Platform.IMESSAGE.value
    )
    if pending is not None and pending.platform_user_id != phone_number:
        await _release_imessage_number(user_id, pending.platform_user_id)

    recorded = await pending_platform_registration_repository.record(
        user_id=user_id,
        platform=Platform.IMESSAGE.value,
        platform_user_id=phone_number,
        created_at=datetime.now(UTC),
    )
    if recorded is None:
        raise create_error(
            message="That number is already being connected on another account",
            why=f"a pending {Platform.IMESSAGE.value} registration for this number belongs to a different GAIA user",
            fix="finish or disconnect the other account's iMessage setup, or use a different number",
            status_code=409,
        )


async def _clear_pending_imessage_registration(user_id: str, linked_phone_number: str) -> None:
    """Retire the pending record once the link lands, releasing a stale number.

    The registered and linked numbers differ when a user registers one handle and
    texts /auth from another — the registered one is then abandoned by definition.
    """
    pending = await pending_platform_registration_repository.get_for_user(
        user_id, Platform.IMESSAGE.value
    )
    if pending is None:
        return

    await pending_platform_registration_repository.delete_for_user(user_id, Platform.IMESSAGE.value)
    if pending.platform_user_id != linked_phone_number:
        await _release_imessage_number(user_id, pending.platform_user_id)


async def _is_linked_number(user_id: str, phone_number: str) -> bool:
    """Whether ``phone_number`` is the user's live iMessage link right now."""
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    entry = linked.get(Platform.IMESSAGE.value)
    return entry is not None and entry["platformUserId"] == phone_number


async def reap_abandoned_imessage_registrations(now: datetime) -> int:
    """Release every Photon number registered before the TTL and never linked.

    A record whose release fails is kept so the next sweep retries it — deleting
    it would strand that pool seat with nothing left pointing at it.
    """
    cutoff = now - IMESSAGE_PENDING_REGISTRATION_TTL
    abandoned = await pending_platform_registration_repository.find_older_than(
        Platform.IMESSAGE.value, cutoff
    )

    reaped = 0
    for record in abandoned:
        if await _is_linked_number(record.user_id, record.platform_user_id):
            # The link landed after the record was written (a /auth that raced the
            # sweep, or a connect re-run by an already-linked user): the number is
            # in use, so the record is stale bookkeeping — never a seat to release.
            await pending_platform_registration_repository.delete_by_platform_user_id(
                Platform.IMESSAGE.value, record.platform_user_id
            )
            continue

        if not await _release_imessage_number(record.user_id, record.platform_user_id):
            continue
        await pending_platform_registration_repository.delete_by_platform_user_id(
            Platform.IMESSAGE.value, record.platform_user_id
        )
        log.audit(
            "imessage abandoned registration reaped",
            actor=record.user_id,
            provider=Platform.IMESSAGE.value,
        )
        reaped += 1
    return reaped


async def platform_requires_upgrade(user_id: str, platform: str) -> bool:
    """True when ``platform`` is Pro-only and ``user_id`` is on the free plan."""
    if platform not in PREMIUM_PLATFORMS:
        return False
    return await payment_service.get_cached_plan_type(user_id) == PlanType.FREE


async def require_platform_plan(user_id: str, platform: str) -> None:
    """Raise the standard 429 upsell when a free user tries to link a paid-only platform."""
    if await platform_requires_upgrade(user_id, platform):
        raise RateLimitExceededException(
            feature=f"{platform}_linking",
            plan_required=PlanType.PRO.value,
            current_plan=PlanType.FREE.value,
        )


class PlatformLinkService:
    """Service for platform account linking operations."""

    @staticmethod
    async def get_user_by_platform_id(
        platform: str, platform_user_id: str
    ) -> dict[str, Any] | None:
        """Find a GAIA user by their platform account ID (queries the nested .id field)."""
        user = await user_repository.get_by_platform_id(platform, platform_user_id)
        return user_to_legacy_dict(user) if user else None

    @staticmethod
    async def list_platform_user_ids(platform: str, limit: int = 500) -> list[str]:
        """List the platform_user_ids of every account linked to the given platform.

        Used by bots (e.g. Discord) to pre-warm DM-channel caches on startup so
        inbound DMs resolve even on a cold restart. Bounded by ``limit`` to keep
        startup cost predictable.
        """
        return await user_repository.list_platform_user_ids(platform, limit=limit)

    @staticmethod
    async def link_account(
        user_id: str,
        platform: str,
        platform_user_id: str,
        # A Mapping, not a dict: the OAuth callback path builds one whose values
        # may be None (a provider that omits a username), and dict's invariance
        # would then reject the dict[str, str] the token path builds.
        profile: Mapping[str, str | None] | None = None,
    ) -> PlatformLinkResult:
        """Link a platform account to a GAIA user.

        Stores the link as a dict {"id", "username"?, "display_name"?}. Raises
        ValueError if the id is empty, the user is not found, or either side is
        already linked to a different account.
        """
        platform_user_id = str(platform_user_id).strip()
        if not platform_user_id:
            raise ValueError("platform_user_id must not be empty")

        # Reject if this platform ID is already linked to a different user
        existing = await user_repository.get_by_platform_id(platform, platform_user_id)
        if existing and existing.id != user_id:
            raise ValueError(f"This {platform} account is already linked to another GAIA user")

        # Reject if the user already has a different platform ID stored
        user = await user_repository.get(user_id)
        if user:
            current_link = (user.platform_links or {}).get(platform)
            if isinstance(current_link, dict):
                current_id = current_link.get("id", "")
                if current_id and current_id != platform_user_id:
                    raise ValueError(
                        f"Your account already has a different {platform} account linked"
                    )

        now = datetime.now(UTC).isoformat()

        # Build the stored dict value
        link_value: PlatformLinkRecord = {"id": platform_user_id}
        if profile:
            if profile.get("username"):
                link_value["username"] = str(profile["username"])
            if profile.get("display_name"):
                link_value["display_name"] = str(profile["display_name"])

        result = await user_repository.link_platform(user_id, platform, link_value, now)
        if result is None:
            raise ValueError("User not found")

        if platform == Platform.IMESSAGE.value:
            await _clear_pending_imessage_registration(user_id, platform_user_id)

        prior_link = (user.platform_links or {}).get(platform) if user else None
        previously_linked_same = (
            isinstance(prior_link, dict) and prior_link.get("id") == platform_user_id
        )

        return PlatformLinkResult(
            status="linked",
            platform=platform,
            platform_user_id=platform_user_id,
            connected_at=now,
            # True only when this call created a brand-new link (not a re-link of
            # the same id) — lets the caller fire a one-off "connected" greeting.
            is_new_link=not previously_linked_same,
        )

    @staticmethod
    async def unlink_account(user_id: str, platform: str) -> DisconnectPlatformResponse:
        """Unlink a platform account from a GAIA user. Raises ValueError if the user is not found.

        Owns the Photon cleanup for iMessage so every unlink path gets it — the
        settings page and the bot's own /unlink both land here.
        """
        # Read before the $unset, or the number to release is already gone.
        linked = await PlatformLinkService.get_linked_platforms(user_id)
        entry = linked.get(platform)

        result = await user_repository.unlink_platform(user_id, platform)
        if result is None:
            raise ValueError("User not found")

        await pending_platform_registration_repository.delete_for_user(user_id, platform)

        if platform == Platform.IMESSAGE.value and entry:
            await _release_imessage_number(user_id, entry["platformUserId"])

        return DisconnectPlatformResponse(status="disconnected", platform=platform)

    @staticmethod
    async def get_linked_platforms(user_id: str) -> dict[str, PlatformLinkEntry]:
        """Get all linked platforms for a user, mapping platform name to connection details.

        Only platforms stored as a dict with a non-empty "id" are returned;
        legacy string/int values are skipped.
        """
        user = await user_repository.get(user_id)
        if user is None:
            return {}

        platform_links = user.platform_links or {}
        connected_at = user.platform_links_connected_at or {}

        result: dict[str, PlatformLinkEntry] = {}
        for platform in Platform.values():
            stored = platform_links.get(platform)
            if isinstance(stored, dict) and stored.get("id"):
                result[platform] = {
                    "platform": platform,
                    "platformUserId": stored["id"],
                    "username": stored.get("username"),
                    "displayName": stored.get("display_name"),
                    "connectedAt": connected_at.get(platform),
                }

        return result
