"""The upgrade link a bot shows a user who hit a paywall or a plan limit.

Bots are where the pricing page is worst, so the link is a personalised Dodo
checkout when one may be minted, and the pricing page otherwise. Shared by the
live bot stream and proactive deliveries, which both carry rate-limit cards.
"""

from collections.abc import Awaitable, Callable

from app.config.settings import settings
from app.constants.cache import BOT_UPGRADE_LINK_PREFIX, BOT_UPGRADE_LINK_TTL
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

#: Resolves the user's upgrade URL on first use; see bot_upgrade_url_once.
UpgradeUrlResolver = Callable[[], Awaitable[str]]


async def _may_mint_bot_upgrade_link(user_id: str) -> bool:
    """Claim this user's one Dodo session mint per BOT_UPGRADE_LINK_TTL window.

    Fails closed: orphan sessions bury the one the user paid on when
    get_latest_for_user looks for it, while a missed mint only degrades the
    link to the pricing page.
    """
    try:
        claimed = await redis_cache.client.set(
            f"{BOT_UPGRADE_LINK_PREFIX}{user_id}", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL
        )
    except Exception as e:
        log.warning(
            f"{LogTag.PAYMENT} Bot upgrade-link window unavailable, falling back to pricing page",
            user={"id": user_id},
            payment={"operation": "bot_upgrade_link_window"},
            failure_reason="window_unavailable",
            error_type=type(e).__name__,
        )
        return False
    return bool(claimed)


async def bot_upgrade_url(user_id: str) -> str:
    """Return a one-tap Dodo checkout URL for this user, or the pricing page.

    The only place a bot turn reaches Dodo; the mint window bounds it to one
    session per user however many blocked messages arrive. A session is never
    reused: Dodo sessions are single-use, and a spent one shows "link expired".
    """
    if not await _may_mint_bot_upgrade_link(user_id):
        return f"{settings.FRONTEND_URL}/pricing"
    try:
        pro = await payment_service.create_pro_checkout(user_id)
    except Exception as e:
        # A marketing link must never cost the user their reply — degrade to
        # the pricing page, loudly. Bounded fields, not provider error text,
        # so the event stays queryable without leaking upstream payloads.
        log.warning(
            f"{LogTag.PAYMENT} Could not mint bot upgrade link, falling back to pricing page",
            user={"id": user_id},
            payment={"operation": "bot_upgrade_link"},
            failure_reason="checkout_unavailable",
            error_type=type(e).__name__,
        )
        return f"{settings.FRONTEND_URL}/pricing"
    return pro.checkout.payment_link or f"{settings.FRONTEND_URL}/pricing"


def bot_upgrade_url_once(user_id: str) -> UpgradeUrlResolver:
    """Build a per-request resolver for this user's upgrade URL, minted at most once.

    Lazy so a turn that never shows a paywall never mints a session. This is
    only the within-turn bound; bot_upgrade_url caps minting across turns.
    """
    cached: list[str] = []

    async def resolve() -> str:
        if not cached:
            cached.append(await bot_upgrade_url(user_id))
        return cached[0]

    return resolve
