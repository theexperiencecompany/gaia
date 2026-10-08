"""Unit tests for analytics service."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.constants.analytics import POSTHOG_PROVIDER_KEY
from app.models.payment_models import SubscriptionStatus
from app.services.analytics_service import (
    _get_posthog_client,
    capture,
    identify_user,
    track_signup,
    track_subscription_event,
)
from shared.py.analytics import PlatformIdentity, UserId
from shared.py.analytics.catalog.auth import UserLoggedOut, UserSignedUp
from shared.py.analytics.catalog.billing import (
    PaymentSucceeded,
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionRenewed,
)
from shared.py.analytics.catalog.chat import ChatComposerPlusMenuClicked
from shared.py.analytics.catalog.memory import MemoryCleared
from tests.helpers import captured_wide_event

USER_1 = UserId("6812f0b3c9a14e2b7d5a91cc")
USER_2 = UserId("6812f0b3c9a14e2b7d5a91dd")
CANCELLED = SubscriptionCancelled(
    subscription_id="sub123", product_id="prod_1", billing_interval="Month"
)
ACTIVATED = SubscriptionActivated(
    subscription_id="sub123", plan_name="Pro", currency="USD", amount=9.99
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_posthog():
    mock_client = MagicMock()
    with patch(
        "app.services.analytics_service._get_posthog_client",
        return_value=mock_client,
    ):
        yield mock_client


@pytest.fixture
def mock_posthog_none():
    with patch(
        "app.services.analytics_service._get_posthog_client",
        return_value=None,
    ):
        yield


# ---------------------------------------------------------------------------
# _get_posthog_client
# ---------------------------------------------------------------------------


class TestGetPosthogClient:
    """Every other test patches this away, so nothing else notices analytics going dead."""

    def test_it_returns_the_registered_client(self):
        client = MagicMock()
        with patch("app.services.analytics_service.providers.get", return_value=client) as registry:
            assert _get_posthog_client() is client

        # The key must match the one the provider is registered under; a different
        # string resolves to nothing and every capture becomes a no-op.
        registry.assert_called_once_with(POSTHOG_PROVIDER_KEY)

    def test_an_unregistered_provider_is_reported_as_absent(self):
        with patch("app.services.analytics_service.providers.get", return_value=None):
            assert _get_posthog_client() is None

    def test_a_captured_event_reaches_the_real_client_through_the_registry(self):
        """Proves capture is wired to the registry, not merely to a patched helper."""
        client = MagicMock()
        with patch("app.services.analytics_service.providers.get", return_value=client):
            capture(USER_1, UserSignedUp(signup_method="workos"))

        client.capture.assert_called_once()
        assert client.capture.call_args.kwargs["distinct_id"] == USER_1.value


# ---------------------------------------------------------------------------
# identify_user
# ---------------------------------------------------------------------------


class TestIdentifyUser:
    def test_identify_with_properties(self, mock_posthog):
        identify_user(USER_1, {"email": "user@example.com"})

        mock_posthog.set.assert_called_once()
        set_call = mock_posthog.set.call_args
        assert set_call.kwargs.get("distinct_id") == USER_1.value
        props = set_call.kwargs.get("properties")
        assert props["email"] == "user@example.com"
        mock_posthog.set_once.assert_called_once()
        set_once_call = mock_posthog.set_once.call_args
        assert set_once_call.kwargs.get("distinct_id") == USER_1.value
        fo_props = set_once_call.kwargs.get("properties")
        assert "first_seen" in fo_props

    def test_identify_with_none_properties(self, mock_posthog):
        identify_user(USER_1, None)
        mock_posthog.set.assert_called_once()
        mock_posthog.set_once.assert_called_once()

    def test_identify_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        identify_user(USER_1, {"email": "user@example.com"})

    def test_identify_handles_exception(self, mock_posthog):
        mock_posthog.set.side_effect = Exception("PostHog error")

        # Should not raise
        identify_user(USER_1, {"email": "user@example.com"})


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------


class TestCapture:
    def test_capture_sends_the_catalog_name_and_properties(self, mock_posthog):
        capture(USER_1, MemoryCleared(deleted_count=3))
        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        assert call_args.kwargs.get("event") == "memory:cleared"
        assert call_args.kwargs.get("distinct_id") == USER_1.value
        props = call_args.kwargs.get("properties")
        assert props["deleted_count"] == 3
        assert "timestamp" in props

    def test_a_none_field_is_left_out_not_sent_as_null(self, mock_posthog):
        capture(USER_1, PaymentSucceeded(payment_id="pay_1", currency="USD", amount=None))

        props = mock_posthog.capture.call_args.kwargs["properties"]
        assert "amount" not in props
        assert props["payment_id"] == "pay_1"

    def test_a_platform_identity_is_sent_as_platform_colon_id(self, mock_posthog):
        capture(PlatformIdentity("telegram", "42"), UserLoggedOut())

        assert mock_posthog.capture.call_args.kwargs["distinct_id"] == "telegram:42"

    def test_the_timestamp_is_offset_aware_utc(self, mock_posthog):
        """datetime.now() without UTC yields naive local time; PostHog then reads the runner's own timezone."""
        capture(USER_1, UserLoggedOut())

        stamped = mock_posthog.capture.call_args.kwargs["properties"]["timestamp"]
        parsed = datetime.fromisoformat(stamped)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_capture_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        capture(USER_1, UserLoggedOut())

    def test_capture_handles_exception(self, mock_posthog):
        mock_posthog.capture.side_effect = Exception("PostHog error")

        # Should not raise
        capture(USER_1, UserLoggedOut())


class TestCaptureRefusesUntypedInput:
    """A raw name or id must fail loud, even with no client configured, so local runs catch it."""

    def test_a_raw_event_name_cannot_be_captured(self, mock_posthog_none):
        with pytest.raises(TypeError, match="catalog event model"):
            capture(USER_1, "user:logged_out")  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime

    def test_a_raw_string_user_id_cannot_be_captured(self, mock_posthog_none):
        with pytest.raises(TypeError, match="UserId or PlatformIdentity"):
            capture("6812f0b3c9a14e2b7d5a91cc", UserLoggedOut())  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime

    def test_a_web_owned_event_cannot_be_captured_by_the_server(self, mock_posthog):
        web_event = ChatComposerPlusMenuClicked(item_id="upload_file", is_mode=False)
        with pytest.raises(TypeError, match="web event; server may not emit it"):
            capture(USER_1, web_event)  # type: ignore[arg-type]  # the wrong type is the point: capture must refuse it at runtime
        mock_posthog.capture.assert_not_called()

    @pytest.mark.parametrize("raw", ["system", "someone@example.com", ""])
    def test_a_non_object_id_user_cannot_be_built(self, raw: str):
        with pytest.raises(ValueError, match="ObjectId"):
            UserId(raw)


class TestCaptureDedupe:
    """dedupe_key is the only thing standing between a retryable worker task and a double count.

    It becomes a stable event uuid, and PostHog stores the same uuid once. Nothing
    exercised it, so every way of getting that uuid wrong was invisible.
    """

    def test_no_dedupe_key_sends_no_uuid(self, mock_posthog):
        """A uuid derived from nothing would collapse genuinely repeated user actions into one."""
        capture(USER_1, MemoryCleared(deleted_count=1))

        assert "uuid" not in mock_posthog.capture.call_args.kwargs

    def test_dedupe_key_attaches_a_uuid_alongside_the_normal_payload(self, mock_posthog):
        capture(USER_1, MemoryCleared(deleted_count=1), dedupe_key="run-1")

        mock_posthog.capture.assert_called_once()
        kwargs = mock_posthog.capture.call_args.kwargs
        assert kwargs["event"] == "memory:cleared"
        assert kwargs["distinct_id"] == USER_1.value
        assert kwargs["properties"]["deleted_count"] == 1
        assert UUID(kwargs["uuid"]).version == 5

    def test_the_same_capture_twice_carries_the_same_uuid(self, mock_posthog):
        """The retry case: an ARQ task re-runs its whole body and must produce a matching uuid."""
        capture(USER_1, MemoryCleared(deleted_count=1), dedupe_key="run-1")
        capture(USER_1, MemoryCleared(deleted_count=2), dedupe_key="run-1")

        first, second = (call.kwargs["uuid"] for call in mock_posthog.capture.call_args_list)
        assert first == second

    def test_the_uuid_changes_with_event_user_and_key(self, mock_posthog):
        """A uuid that ignores any of its three inputs silently deduplicates events that are not repeats."""
        capture(USER_1, MemoryCleared(deleted_count=1), dedupe_key="run-1")
        capture(USER_1, UserLoggedOut(), dedupe_key="run-1")
        capture(USER_2, MemoryCleared(deleted_count=1), dedupe_key="run-1")
        capture(USER_1, MemoryCleared(deleted_count=1), dedupe_key="run-2")

        uuids = [call.kwargs["uuid"] for call in mock_posthog.capture.call_args_list]
        assert len(set(uuids)) == 4

    def test_a_deduped_capture_failure_is_reported_loudly(self, mock_posthog):
        """Analytics never raises into the caller, so this failure is visible only via the wide event."""
        mock_posthog.capture.side_effect = RuntimeError("PostHog error")

        with patch("app.services.analytics_service.log") as mock_log:
            capture(USER_1, UserLoggedOut(), dedupe_key="run-1")

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == "Failed to capture event in PostHog"
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs["event"] == "user:logged_out"
        assert kwargs["user_id"] == USER_1.value
        assert kwargs["error"] == "PostHog error"
        assert kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# track_signup
# ---------------------------------------------------------------------------


class TestTrackSignup:
    def test_calls_identify_and_capture(self, mock_posthog):
        track_signup(USER_1, "user@example.com", name="Alice")
        assert mock_posthog.set.call_count == 1
        assert mock_posthog.set_once.call_count == 1
        assert mock_posthog.capture.call_count == 1

        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["email"] == "user@example.com"
        assert set_props["name"] == "Alice"
        assert set_props["signup_method"] == "workos"

        capture_kwargs = mock_posthog.capture.call_args.kwargs
        assert capture_kwargs.get("event") == "user:signed_up"
        assert capture_kwargs["properties"]["signup_method"] == "workos"

    def test_default_signup_method(self, mock_posthog):
        track_signup(USER_1, "user@example.com")
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["signup_method"] == "workos"

    def test_custom_signup_method(self, mock_posthog):
        track_signup(USER_1, "user@example.com", signup_method="google")
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["signup_method"] == "google"
        assert mock_posthog.capture.call_args.kwargs["properties"]["signup_method"] == "google"

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_signup(USER_1, "user@example.com")


# ---------------------------------------------------------------------------
# track_subscription_event
# ---------------------------------------------------------------------------


class TestTrackSubscriptionEvent:
    def test_captures_subscription_event(self, mock_posthog):
        track_subscription_event(USER_1, ACTIVATED)

        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        assert call_args.kwargs["event"] == "subscription:activated"
        props = call_args.kwargs.get("properties")
        assert props["subscription_id"] == "sub123"
        assert props["plan_name"] == "Pro"
        assert props["amount"] == pytest.approx(9.99)
        assert props["currency"] == "USD"

    async def test_the_wide_event_names_the_plan_that_was_billed(self, mock_posthog):
        """Billing support reads the wide event, not PostHog; a field under the wrong key is invisible."""
        async with captured_wide_event() as event:
            track_subscription_event(USER_1, ACTIVATED)

        assert event["subscription"] == {
            "user_id": USER_1.value,
            "event_type": "subscription:activated",
            "plan_name": "Pro",
            "subscription_id": "sub123",
        }

    def test_a_cancellation_carries_no_plan_fields(self, mock_posthog):
        track_subscription_event(USER_1, CANCELLED)

        props = mock_posthog.capture.call_args.kwargs.get("properties")
        assert "plan_name" not in props
        assert "amount" not in props
        assert "currency" not in props
        assert props["product_id"] == "prod_1"

    def test_activated_event_updates_user_properties(self, mock_posthog):
        track_subscription_event(USER_1, ACTIVATED)

        assert mock_posthog.set.call_count >= 1
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["plan"] == "pro"
        assert set_props["is_subscribed"] is True
        assert set_props["subscription_status"] == "active"

    def test_cancelled_event_updates_subscription_status(self, mock_posthog):
        track_subscription_event(USER_1, CANCELLED)

        mock_posthog.set.assert_called_once()
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props == {"subscription_status": SubscriptionStatus.CANCELLED}

    def test_renewed_event_keeps_the_user_subscribed(self, mock_posthog):
        track_subscription_event(
            USER_1, SubscriptionRenewed(subscription_id="sub123", currency="USD")
        )

        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["is_subscribed"] is True
        assert set_props["subscription_status"] == SubscriptionStatus.ACTIVE

    def test_identify_error_handled(self, mock_posthog):
        mock_posthog.set.side_effect = Exception("PostHog error")

        # Should not raise despite set failure
        track_subscription_event(USER_1, ACTIVATED)

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_subscription_event(USER_1, ACTIVATED)
