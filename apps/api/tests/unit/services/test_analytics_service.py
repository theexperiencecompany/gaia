"""Unit tests for analytics service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.analytics_service import (
    AnalyticsEvents,
    capture_event,
    flush_events,
    identify_user,
    track_payment_event,
    track_signup,
    track_subscription_event,
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
# AnalyticsEvents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnalyticsEvents:
    def test_event_constants_exist(self):
        assert AnalyticsEvents.USER_SIGNED_UP == "user:signed_up"
        assert AnalyticsEvents.PAYMENT_SUCCEEDED == "payment:succeeded"
        assert AnalyticsEvents.PAYMENT_FAILED == "payment:failed"
        assert AnalyticsEvents.PAYMENT_REFUNDED == "payment:refunded"
        assert AnalyticsEvents.SUBSCRIPTION_ACTIVATED == "subscription:activated"
        assert AnalyticsEvents.SUBSCRIPTION_RENEWED == "subscription:renewed"
        assert AnalyticsEvents.SUBSCRIPTION_CANCELLED == "subscription:cancelled"
        assert AnalyticsEvents.SUBSCRIPTION_EXPIRED == "subscription:expired"
        assert AnalyticsEvents.SUBSCRIPTION_FAILED == "subscription:failed"


# ---------------------------------------------------------------------------
# identify_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIdentifyUser:
    def test_identify_with_properties(self, mock_posthog):
        identify_user("user@example.com", {"email": "user@example.com"})

        mock_posthog.identify.assert_called_once()
        call_args = mock_posthog.identify.call_args
        assert call_args[0][0] == "user@example.com"
        props = call_args[0][1]
        assert props["email"] == "user@example.com"
        assert "$set_once" in props
        assert "first_seen" in props["$set_once"]

    def test_identify_with_none_properties(self, mock_posthog):
        identify_user("user@example.com", None)

        mock_posthog.identify.assert_called_once()
        call_args = mock_posthog.identify.call_args
        props = call_args[0][1]
        assert "$set_once" in props

    def test_identify_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        identify_user("user@example.com", {"email": "user@example.com"})

    def test_identify_handles_exception(self, mock_posthog):
        mock_posthog.identify.side_effect = Exception("PostHog error")

        # Should not raise
        identify_user("user@example.com", {"email": "user@example.com"})


# ---------------------------------------------------------------------------
# capture_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCaptureEvent:
    def test_capture_basic_event(self, mock_posthog):
        capture_event("user1", "test:event", {"key": "value"})

        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        assert call_args[0][0] == "user1"
        assert call_args[0][1] == "test:event"
        props = call_args[0][2]
        assert props["key"] == "value"
        assert "timestamp" in props

    def test_capture_with_none_properties(self, mock_posthog):
        capture_event("user1", "test:event", None)

        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert "timestamp" in props

    def test_capture_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        capture_event("user1", "test:event")

    def test_capture_handles_exception(self, mock_posthog):
        mock_posthog.capture.side_effect = Exception("PostHog error")

        # Should not raise
        capture_event("user1", "test:event")


# ---------------------------------------------------------------------------
# track_signup
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTrackSignup:
    def test_calls_identify_and_capture(self, mock_posthog):
        track_signup("user1", "user@example.com", name="Alice")

        assert mock_posthog.identify.call_count == 1
        assert mock_posthog.capture.call_count == 1

        # Verify identify properties
        identify_props = mock_posthog.identify.call_args[0][1]
        assert identify_props["email"] == "user@example.com"
        assert identify_props["name"] == "Alice"
        assert identify_props["signup_method"] == "workos"

        # Verify capture event name
        assert mock_posthog.capture.call_args[0][1] == AnalyticsEvents.USER_SIGNED_UP

    def test_default_signup_method(self, mock_posthog):
        track_signup("user1", "user@example.com")

        identify_props = mock_posthog.identify.call_args[0][1]
        assert identify_props["signup_method"] == "workos"

    def test_custom_signup_method(self, mock_posthog):
        track_signup("user1", "user@example.com", signup_method="google")

        identify_props = mock_posthog.identify.call_args[0][1]
        assert identify_props["signup_method"] == "google"

    def test_extra_properties_merged(self, mock_posthog):
        track_signup("user1", "user@example.com", properties={"referral": "friend"})

        capture_props = mock_posthog.capture.call_args[0][2]
        assert capture_props["referral"] == "friend"

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_signup("user1", "user@example.com")


# ---------------------------------------------------------------------------
# track_subscription_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTrackSubscriptionEvent:
    def test_captures_subscription_event(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            subscription_id="sub123",
            plan_name="pro",
            amount=9.99,
            currency="USD",
        )

        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert props["subscription_id"] == "sub123"
        assert props["plan_name"] == "pro"
        assert props["amount"] == pytest.approx(9.99)
        assert props["currency"] == "USD"

    def test_removes_none_values(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_CANCELLED,
            subscription_id="sub123",
        )

        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert "plan_name" not in props
        assert "amount" not in props
        assert "currency" not in props

    def test_activated_event_updates_user_properties(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            plan_name="pro",
        )

        # Should call identify to update user properties
        assert mock_posthog.identify.call_count == 1
        identify_props = mock_posthog.identify.call_args[0][1]
        assert identify_props["plan"] == "pro"
        assert identify_props["subscription_status"] == "active"

    def test_non_activated_event_no_identify(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_CANCELLED,
        )

        mock_posthog.identify.assert_not_called()

    def test_extra_properties_merged(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_RENEWED,
            properties={"renewal_count": 3},
        )

        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert props["renewal_count"] == 3

    def test_identify_error_handled(self, mock_posthog):
        mock_posthog.identify.side_effect = Exception("PostHog error")

        # Should not raise despite identify failure
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            plan_name="pro",
        )

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_subscription_event("user1", AnalyticsEvents.SUBSCRIPTION_ACTIVATED)


# ---------------------------------------------------------------------------
# track_payment_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTrackPaymentEvent:
    def test_captures_payment_event(self, mock_posthog):
        track_payment_event(
            "user1",
            AnalyticsEvents.PAYMENT_SUCCEEDED,
            payment_id="pay123",
            amount=29.99,
            currency="USD",
        )

        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        assert call_args[0][1] == AnalyticsEvents.PAYMENT_SUCCEEDED
        props = call_args[0][2]
        assert props["payment_id"] == "pay123"
        assert props["amount"] == pytest.approx(29.99)
        assert props["currency"] == "USD"

    def test_removes_none_values(self, mock_posthog):
        track_payment_event(
            "user1",
            AnalyticsEvents.PAYMENT_FAILED,
        )

        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert "payment_id" not in props
        assert "amount" not in props
        assert "currency" not in props

    def test_extra_properties_merged(self, mock_posthog):
        track_payment_event(
            "user1",
            AnalyticsEvents.PAYMENT_REFUNDED,
            properties={"reason": "duplicate"},
        )

        call_args = mock_posthog.capture.call_args
        props = call_args[0][2]
        assert props["reason"] == "duplicate"


# ---------------------------------------------------------------------------
# flush_events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFlushEvents:
    def test_flushes_client(self, mock_posthog):
        flush_events()

        mock_posthog.flush.assert_called_once()

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        flush_events()

    def test_handles_flush_exception(self, mock_posthog):
        mock_posthog.flush.side_effect = Exception("Flush failed")

        # Should not raise
        flush_events()
