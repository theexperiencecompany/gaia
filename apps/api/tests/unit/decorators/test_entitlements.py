"""The paywall gate: require_active_subscription / require_subscription.

Distinct from tiered rate limiting — this blocks access outright for a plan
with none at all, rather than capping usage. The 402 wire shape is fixed (the
frontend is built against it), so the contract tests assert the exact body.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.decorators.entitlements import (
    PAYWALL_MESSAGE,
    SubscriptionRequiredException,
    get_checkout_url,
    is_subscription_active,
    require_active_subscription,
    require_subscription,
)
from app.models.payment_models import PlanType
from app.services.analytics_service import AnalyticsEvents

pytestmark = pytest.mark.unit

ENT = "app.decorators.entitlements"
# require_subscription resolves the caller via app.core.request_context.resolve_caller,
# which reads get_authenticated_user from its own module — not re-imported into
# entitlements.py — so tests patch it at the source.
RCX = "app.core.request_context"


def _checkout(payment_link: str | None) -> MagicMock:
    checkout = MagicMock()
    checkout.checkout.payment_link = payment_link
    return checkout


class TestIsSubscriptionActive:
    async def test_pro_plan_is_active(self) -> None:
        plan_lookup = AsyncMock(return_value=PlanType.PRO)
        with patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup):
            assert await is_subscription_active("u1") is True
        plan_lookup.assert_awaited_once_with("u1")

    async def test_free_plan_is_not_active(self) -> None:
        plan_lookup = AsyncMock(return_value=PlanType.FREE)
        with patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup):
            assert await is_subscription_active("u1") is False
        plan_lookup.assert_awaited_once_with("u1")


class TestGetCheckoutUrl:
    async def test_returns_the_minted_payment_link(self) -> None:
        checkout_mock = AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc"))
        with patch(f"{ENT}.payment_service.create_pro_checkout", new=checkout_mock):
            assert await get_checkout_url("u1") == "https://checkout.dodo.test/abc"
        checkout_mock.assert_awaited_once_with("u1")

    async def test_dodo_failure_degrades_to_none_instead_of_raising(self) -> None:
        """A paywall response must never itself fail because Dodo is down."""
        exc = RuntimeError("dodo unreachable")
        with (
            patch(f"{ENT}.payment_service.create_pro_checkout", new=AsyncMock(side_effect=exc)),
            patch(f"{ENT}.log") as mock_log,
        ):
            assert await get_checkout_url("u1") is None

        mock_log.warning.assert_called_once_with(
            "Could not mint checkout link for paywall response",
            user={"id": "u1"},
            payment={"operation": "paywall_checkout_link"},
            error_type="RuntimeError",
        )


class TestRequireActiveSubscription:
    async def test_pro_user_passes_without_minting_a_checkout_link(self) -> None:
        checkout_mock = AsyncMock()
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.PRO),
            ),
            patch(f"{ENT}.payment_service.create_pro_checkout", new=checkout_mock),
        ):
            await require_active_subscription("u1", feature="chat")  # must not raise
        checkout_mock.assert_not_called()

    async def test_free_user_gets_the_exact_402_wire_contract(self) -> None:
        checkout_mock = AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc"))
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(f"{ENT}.payment_service.create_pro_checkout", new=checkout_mock),
            patch(f"{ENT}.settings.PAYWALL_DISCOUNT_CODE", None),
            patch(f"{ENT}.log") as mock_log,
        ):
            with pytest.raises(SubscriptionRequiredException) as exc_info:
                await require_active_subscription("u1", feature="chat_stream_endpoint")

        # The blocked user's own id must reach the checkout minter — not a
        # stale/None value. A caller mixup here would mint a checkout link
        # for the wrong account (or no account at all).
        checkout_mock.assert_awaited_once_with("u1")

        exc = exc_info.value
        assert exc.status_code == 402
        assert exc.detail == {
            "code": "subscription_required",
            "message": PAYWALL_MESSAGE,
            "checkout_url": "https://checkout.dodo.test/abc",
            "discount_code": None,
        }
        mock_log.warning.assert_called_once_with(
            "Subscription required, blocking request",
            user={"id": "u1"},
            payment={"operation": "paywall_gate", "feature": "chat_stream_endpoint"},
        )

    async def test_discount_code_travels_when_configured(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(
                f"{ENT}.payment_service.create_pro_checkout",
                new=AsyncMock(return_value=_checkout(None)),
            ),
            patch(f"{ENT}.settings.PAYWALL_DISCOUNT_CODE", "SAVE20"),
        ):
            with pytest.raises(SubscriptionRequiredException) as exc_info:
                await require_active_subscription("u1", feature="chat")

        assert exc_info.value.detail["discount_code"] == "SAVE20"
        assert exc_info.value.detail["checkout_url"] is None

    async def test_block_is_captured_against_the_blocked_users_own_profile(self) -> None:
        """The paywall event must carry the blocked user's id, not an anonymous
        one — bot and worker paths reach this with no request context, so an
        implicit distinct_id would strand the block on a ghost profile."""
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(
                f"{ENT}.payment_service.create_pro_checkout",
                new=AsyncMock(return_value=_checkout("https://checkout.dodo.test/abc")),
            ),
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            with pytest.raises(SubscriptionRequiredException):
                await require_active_subscription("u1", feature="get_token")

        mock_capture.assert_called_once_with(
            "u1",
            AnalyticsEvents.PAYWALL_BLOCKED,
            {"feature": "get_token", "has_checkout_url": True},
        )

    async def test_pro_user_is_never_captured_as_blocked(self) -> None:
        with (
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.PRO),
            ),
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            await require_active_subscription("u1", feature="get_token")

        mock_capture.assert_not_called()


class TestRequireSubscriptionDecorator:
    async def test_free_user_never_reaches_the_handler(self) -> None:
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)
        plan_lookup = AsyncMock(return_value=PlanType.FREE)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value={"user_id": "u1"}),
            patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup),
            patch(
                f"{ENT}.payment_service.create_pro_checkout",
                new=AsyncMock(return_value=_checkout(None)),
            ),
        ):
            with pytest.raises(SubscriptionRequiredException):
                await wrapped()

        plan_lookup.assert_awaited_once_with("u1")
        handler.assert_not_called()

    async def test_block_is_attributed_to_the_handler_it_blocked(self) -> None:
        """`feature` is the decorated handler's name, so a funnel can tell a
        voice-token block from a chat one without a per-route argument."""

        async def get_token() -> str:
            return "ok"

        wrapped = require_subscription()(get_token)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value={"user_id": "u1"}),
            patch(
                f"{ENT}.payment_service.get_cached_plan_type",
                new=AsyncMock(return_value=PlanType.FREE),
            ),
            patch(
                f"{ENT}.payment_service.create_pro_checkout",
                new=AsyncMock(return_value=_checkout(None)),
            ),
            patch(f"{ENT}.capture_event") as mock_capture,
        ):
            with pytest.raises(SubscriptionRequiredException):
                await wrapped()

        assert mock_capture.call_args.args[0] == "u1"
        assert mock_capture.call_args.args[2]["feature"] == "get_token"

    async def test_pro_user_reaches_the_handler_with_its_result_unchanged(self) -> None:
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)
        plan_lookup = AsyncMock(return_value=PlanType.PRO)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value={"user_id": "u1"}),
            patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup),
        ):
            result = await wrapped(1, 2, keyword="value")

        assert result == "ok"
        plan_lookup.assert_awaited_once_with("u1")
        handler.assert_called_once_with(1, 2, keyword="value")

    async def test_unauthenticated_request_is_left_to_the_routes_own_auth(self) -> None:
        """No user to gate — same rule tiered_rate_limit follows for public routes."""
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value=None),
            patch(f"{ENT}.log") as mock_log,
        ):
            result = await wrapped()

        assert result == "ok"
        handler.assert_called_once()
        mock_log.warning.assert_called_once_with(
            "require_subscription could not resolve a caller — paywall bypassed",
            payment={"operation": "paywall_gate_unresolved_user"},
        )

    async def test_unauthenticated_request_forwards_positional_args_and_kwargs_unchanged(
        self,
    ) -> None:
        """The fail-open path must call through with the caller's exact args —
        dropping either positionals or kwargs here would silently corrupt the
        wrapped handler's invocation for every unauthenticated caller."""
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)

        with patch(f"{RCX}.get_authenticated_user", return_value=None):
            result = await wrapped("pos1", "pos2", keyword="value")

        assert result == "ok"
        handler.assert_called_once_with("pos1", "pos2", keyword="value")

    async def test_authenticated_user_with_no_user_id_is_a_401(self) -> None:
        """A truthy but user_id-less auth dict — distinct from no user at all
        (falsy, handled by the fallthrough test above)."""
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)

        with patch(f"{RCX}.get_authenticated_user", return_value={"email": "x@example.com"}):
            with pytest.raises(Exception) as exc_info:
                await wrapped()

        assert getattr(exc_info.value, "status_code", None) == 401
        assert getattr(exc_info.value, "detail", None) == "User ID not found"
        handler.assert_not_called()

    async def test_falls_back_to_an_explicit_user_kwarg_with_no_request_context(self) -> None:
        """A bot resolving its own user via an explicit ``user=`` kwarg — no
        request-scoped auth context at all (direct, non-HTTP invocation)."""
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)
        plan_lookup = AsyncMock(return_value=PlanType.PRO)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value=None),
            patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup),
        ):
            result = await wrapped(user={"user_id": "kwarg-user"})

        assert result == "ok"
        plan_lookup.assert_awaited_once_with("kwarg-user")
        handler.assert_called_once_with(user={"user_id": "kwarg-user"})

    async def test_falls_back_to_a_positional_dict_with_no_request_context(self) -> None:
        """A bot passing its resolved user as a positional dict arg."""
        handler = AsyncMock(return_value="ok")
        wrapped = require_subscription()(handler)
        plan_lookup = AsyncMock(return_value=PlanType.PRO)

        with (
            patch(f"{RCX}.get_authenticated_user", return_value=None),
            patch(f"{ENT}.payment_service.get_cached_plan_type", new=plan_lookup),
        ):
            result = await wrapped("unrelated-positional", {"user_id": "positional-user"})

        assert result == "ok"
        plan_lookup.assert_awaited_once_with("positional-user")
        handler.assert_called_once_with("unrelated-positional", {"user_id": "positional-user"})
