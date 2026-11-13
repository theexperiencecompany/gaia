"""A bot turn mints at most one Dodo session per user per window.

Both bot walls — the paid-only gate and the rate-limit card — repeat for
every message until the user acts on them, and each mint is a get_plans
call, a Dodo round-trip and a checkout_sessions insert. Unbounded, a
lapsed user who keeps typing leaves a trail of throwaway sessions, and the
newest of them is what checkout_session_repository.get_latest_for_user
finds when the webhook-race recovery goes looking for the session they
actually paid on.

What is gated is the MINT, never the message: a bot has no modal and no
banner, so going quiet on a blocked turn would read as a broken bot.
"""

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, call, patch

from app.constants.cache import BOT_UPGRADE_LINK_TTL
from app.services.bot.upgrade_link import bot_upgrade_url, bot_upgrade_url_once
from shared.py.wide_events import log

CHECKOUT_URL = "https://checkout.dodopayments.com/s/cs_1"
REDIS_PATCH = "app.services.bot.upgrade_link.redis_cache"
CHECKOUT_PATCH = "app.services.bot.upgrade_link.payment_service.create_pro_checkout"


def _redis(*set_results: object) -> MagicMock:
    cache = MagicMock()
    cache.client.set = AsyncMock(side_effect=list(set_results))
    return cache


class TestBotUpgradeUrl:
    async def test_a_burst_of_blocked_turns_mints_exactly_one_session(
        self, make_checkout: Callable[[str], AsyncMock]
    ) -> None:
        """SET NX returns None once the key is there — that is the whole gate."""
        checkout = make_checkout(CHECKOUT_URL)
        # First turn claims the window; the next two find it held.
        with (
            patch(REDIS_PATCH, _redis(True, None, None)),
            patch(CHECKOUT_PATCH, checkout),
        ):
            urls = [await bot_upgrade_url("user_1") for _ in range(3)]

        assert checkout.await_count == 1, (
            f"three blocked turns minted {checkout.await_count} Dodo session(s); one is the cap"
        )
        assert urls[0] == CHECKOUT_URL

    async def test_a_turn_outside_the_window_still_gets_a_working_url(
        self, make_checkout: Callable[[str], AsyncMock]
    ) -> None:
        """The user is never left without a way to pay — only without one tap."""
        checkout = make_checkout(CHECKOUT_URL)
        with patch(REDIS_PATCH, _redis(None)), patch(CHECKOUT_PATCH, checkout):
            url = await bot_upgrade_url("user_1")

        assert url.endswith("/pricing")
        checkout.assert_not_awaited()

    async def test_the_window_is_per_user(self, make_checkout: Callable[[str], AsyncMock]) -> None:
        """A shared key would let one lapsed user mute everyone else's link."""
        checkout = make_checkout(CHECKOUT_URL)
        cache = _redis(True, True)
        with patch(REDIS_PATCH, cache), patch(CHECKOUT_PATCH, checkout):
            await bot_upgrade_url("user_1")
            await bot_upgrade_url("user_2")

        # SET key value NX EX ttl: without NX every turn re-mints, without EX
        # the first turn locks the user out forever. Both survived as mutants
        # under a key-only assertion.
        assert cache.client.set.await_args_list == [
            call("bot:upgrade-link:user_1", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL),
            call("bot:upgrade-link:user_2", "1", nx=True, ex=BOT_UPGRADE_LINK_TTL),
        ]

    async def test_an_unavailable_window_skips_the_mint_and_says_so(
        self, make_checkout: Callable[[str], AsyncMock]
    ) -> None:
        """Fails CLOSED, unlike the workflow limit-notice gate it copies — a degraded link costs orphan sessions, cheaper than silently burying a real payment."""
        log.reset()
        cache = MagicMock()
        cache.client.set = AsyncMock(side_effect=ConnectionError("redis down"))
        checkout = make_checkout(CHECKOUT_URL)
        with patch(REDIS_PATCH, cache), patch(CHECKOUT_PATCH, checkout):
            url = await bot_upgrade_url("user_1")

        assert url.endswith("/pricing")
        checkout.assert_not_awaited()
        assert log.get()["warnings"] == [
            {
                "msg": (
                    "[PAYMENT] Bot upgrade-link window unavailable, falling back to pricing page"
                ),
                "user": {"id": "user_1"},
                "payment": {"operation": "bot_upgrade_link_window"},
                "failure_reason": "window_unavailable",
                "error_type": "ConnectionError",
            }
        ]

    async def test_a_dodo_failure_degrades_to_the_pricing_page_loudly(self) -> None:
        """A marketing link must never cost the user their reply."""
        log.reset()
        with (
            patch(REDIS_PATCH, _redis(True)),
            patch(CHECKOUT_PATCH, AsyncMock(side_effect=RuntimeError("dodo down"))),
        ):
            url = await bot_upgrade_url("user_1")

        assert url.endswith("/pricing")
        assert log.get()["warnings"] == [
            {
                "msg": "[PAYMENT] Could not mint bot upgrade link, falling back to pricing page",
                "user": {"id": "user_1"},
                "payment": {"operation": "bot_upgrade_link"},
                "failure_reason": "checkout_unavailable",
                "error_type": "RuntimeError",
            }
        ]


class TestBotUpgradeUrlOnce:
    async def test_the_resolver_mints_lazily_and_only_once_per_request(self) -> None:
        mint = AsyncMock(return_value=CHECKOUT_URL)
        with patch("app.services.bot.upgrade_link.bot_upgrade_url", mint):
            resolve = bot_upgrade_url_once("user_1")
            mint.assert_not_awaited()
            urls = [await resolve(), await resolve()]

        assert urls == [CHECKOUT_URL, CHECKOUT_URL]
        mint.assert_awaited_once_with("user_1")
