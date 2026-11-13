"""The tool_data cards a bot receives, with the account-bound links filled in."""

from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.auth import CONNECT_LINK_TTL_MINUTES
from app.models.chat_models import ToolDataEntry
from app.models.payment_models import PlanType
from app.services.bot.cards import BotCardContext, resolve_bot_cards
from app.services.connect_link_service import integrations_page_url
from shared.py.wide_events import log

CHECKOUT_URL = "https://checkout.dodopayments.com/s/cs_1"
CHECKOUT_PATCH = "app.services.bot.upgrade_link.payment_service.create_pro_checkout"
BUILD_CONNECT_LINK_PATCH = "app.services.bot.cards.build_connect_link_url"


@pytest.fixture
def upgrade_link_window_open() -> Iterator[None]:
    """Open the once-per-window mint gate, so card tests are about the card.

    Without it a repeat user id falls through to the pricing-page branch and
    passes for the wrong reason.
    """
    with patch(
        "app.services.bot.upgrade_link._may_mint_bot_upgrade_link",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


def _rate_limit_card(current_plan: str) -> ToolDataEntry:
    return {
        "tool_name": "rate_limit_data",
        "data": {"feature": "chat_messages", "current_plan": current_plan},
    }


def _connect_card(**data: object) -> ToolDataEntry:
    return {
        "tool_name": "integration_connection_required",
        "data": {"integration_id": "gmail", **data},
    }


def _upgrade_url_of(cards: list[ToolDataEntry]) -> object:
    (card,) = cards
    assert isinstance(card["data"], dict)
    return card["data"]["upgrade_url"]


@pytest.mark.usefixtures("upgrade_link_window_open")
class TestRateLimitCards:
    """Bots have no modal, so the card has to carry the one-tap upgrade link itself."""

    async def test_free_user_gets_a_real_checkout_link(
        self, make_checkout: Callable[[str], AsyncMock]
    ) -> None:
        checkout = make_checkout(CHECKOUT_URL)
        with patch(CHECKOUT_PATCH, checkout):
            cards = await resolve_bot_cards(
                _rate_limit_card(PlanType.FREE.value), BotCardContext.for_user("user_1", None)
            )

        assert cards == [
            {
                "tool_name": "rate_limit_data",
                "data": {
                    "feature": "chat_messages",
                    "current_plan": "free",
                    "upgrade_url": CHECKOUT_URL,
                },
            }
        ]
        checkout.assert_awaited_once_with("user_1")

    async def test_dodo_failure_degrades_to_the_pricing_page(self) -> None:
        """A marketing link must never cost the user their reply."""
        log.reset()
        with patch(CHECKOUT_PATCH, AsyncMock(side_effect=RuntimeError("dodo down"))):
            cards = await resolve_bot_cards(
                _rate_limit_card(PlanType.FREE.value), BotCardContext.for_user("user_1", None)
            )

        assert str(_upgrade_url_of(cards)).endswith("/pricing")
        assert [w["failure_reason"] for w in log.get()["warnings"]] == ["checkout_unavailable"]

    async def test_pro_user_gets_a_null_upgrade_url_and_no_session(self) -> None:
        checkout = AsyncMock()
        with patch(CHECKOUT_PATCH, checkout):
            cards = await resolve_bot_cards(
                _rate_limit_card(PlanType.PRO.value), BotCardContext.for_user("user_1", None)
            )

        assert _upgrade_url_of(cards) is None
        checkout.assert_not_awaited()

    async def test_two_cards_in_one_request_share_one_minted_session(
        self, make_checkout: Callable[[str], AsyncMock]
    ) -> None:
        checkout = make_checkout(CHECKOUT_URL)
        ctx = BotCardContext.for_user("user_1", None)
        with patch(CHECKOUT_PATCH, checkout):
            await resolve_bot_cards(_rate_limit_card(PlanType.FREE.value), ctx)
            await resolve_bot_cards(_rate_limit_card(PlanType.FREE.value), ctx)

        assert checkout.await_count == 1


async def test_a_blocked_turn_outside_the_mint_window_still_carries_a_working_link(
    make_checkout: Callable[[str], AsyncMock],
) -> None:
    """A bot has no modal fallback, so the card still goes out, with the pricing page in place of the personalised link when only the mint is gated."""
    checkout = make_checkout(CHECKOUT_URL)
    with (
        patch(
            "app.services.bot.upgrade_link._may_mint_bot_upgrade_link",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(CHECKOUT_PATCH, checkout),
    ):
        cards = await resolve_bot_cards(
            _rate_limit_card(PlanType.FREE.value), BotCardContext.for_user("user_1", None)
        )

    assert str(_upgrade_url_of(cards)).endswith("/pricing")
    checkout.assert_not_awaited()


class TestConnectCards:
    """A connect card is single-use-link bound to the account, minted as the card leaves."""

    @staticmethod
    def _ctx() -> BotCardContext:
        return BotCardContext(user_id="user_1", conversation_id=None, upgrade_url=AsyncMock())

    async def test_a_fresh_link_is_minted_for_the_reconnect_account(self) -> None:
        mint = AsyncMock(return_value="https://app.example/connect/code1")
        card = _connect_card(reconnect_account={"id": "acct_9"})
        with patch(BUILD_CONNECT_LINK_PATCH, mint):
            cards = await resolve_bot_cards(card, self._ctx())

        mint.assert_awaited_once_with("user_1", "gmail", "acct_9")
        assert cards == [
            _connect_card(
                reconnect_account={"id": "acct_9"},
                connect_url="https://app.example/connect/code1",
                connect_url_valid_minutes=CONNECT_LINK_TTL_MINUTES,
            )
        ]

    async def test_a_first_connect_mints_without_an_account_id(self) -> None:
        mint = AsyncMock(return_value="https://app.example/connect/code2")
        with patch(BUILD_CONNECT_LINK_PATCH, mint):
            await resolve_bot_cards(_connect_card(), self._ctx())

        mint.assert_awaited_once_with("user_1", "gmail", None)

    async def test_an_existing_connect_url_is_left_alone(self) -> None:
        mint = AsyncMock()
        card = _connect_card(connect_url="https://app.example/connect/already")
        with patch(BUILD_CONNECT_LINK_PATCH, mint):
            cards = await resolve_bot_cards(card, self._ctx())

        mint.assert_not_awaited()
        assert cards == [card]

    async def test_an_unstorable_link_falls_back_to_the_integrations_page(self) -> None:
        with patch(BUILD_CONNECT_LINK_PATCH, AsyncMock(return_value=None)):
            cards = await resolve_bot_cards(_connect_card(), self._ctx())

        assert cards == [
            _connect_card(connect_url=integrations_page_url(), connect_url_valid_minutes=None)
        ]


class TestFiltering:
    async def test_only_bot_renderable_cards_survive_in_order(self) -> None:
        approval: ToolDataEntry = {"tool_name": "approval_request", "data": {"id": "req-1"}}
        memory: ToolDataEntry = {"tool_name": "memory_data", "data": {}}
        web_only: list[ToolDataEntry] = [
            {"tool_name": "tool_calls_data", "data": {}},
            {"tool_name": "subagent_group", "data": {}},
            {"tool_name": "not_a_real_tool", "data": {}},
        ]
        ctx = BotCardContext(user_id="user_1", conversation_id=None, upgrade_url=AsyncMock())

        cards = await resolve_bot_cards(
            [web_only[0], approval, web_only[1], memory, web_only[2]], ctx
        )

        assert cards == [approval, memory]

    async def test_a_malformed_entry_is_dropped_with_a_warning_and_the_rest_survive(self) -> None:
        log.reset()
        memory: ToolDataEntry = {"tool_name": "memory_data", "data": {}}
        ctx = BotCardContext(user_id="user_1", conversation_id=None, upgrade_url=AsyncMock())

        cards = await resolve_bot_cards([{"no_tool_name": True}, memory], ctx)

        assert cards == [memory]
        assert log.get()["warnings"] == [
            {
                "msg": "[API] Bot cards: dropped a malformed tool_data entry",
                "error_type": "ValidationError",
            }
        ]

    async def test_no_tool_data_yields_no_cards_and_no_warning(self) -> None:
        log.reset()
        ctx = BotCardContext(user_id="user_1", conversation_id=None, upgrade_url=AsyncMock())

        assert await resolve_bot_cards(None, ctx) == []
        assert "warnings" not in log.get()
