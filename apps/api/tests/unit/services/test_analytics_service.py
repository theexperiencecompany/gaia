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

        # Implementation uses PostHog `set` and `set_once` methods
        mock_posthog.set.assert_called_once()
        set_call = mock_posthog.set.call_args
        # set called with distinct_id keyword and properties
        assert set_call.kwargs.get("distinct_id") == "user@example.com"
        props = set_call.kwargs.get("properties")
        assert props["email"] == "user@example.com"
        mock_posthog.set_once.assert_called_once()
        set_once_call = mock_posthog.set_once.call_args
        assert set_once_call.kwargs.get("distinct_id") == "user@example.com"
        fo_props = set_once_call.kwargs.get("properties")
        assert "first_seen" in fo_props

    def test_identify_with_none_properties(self, mock_posthog):
        identify_user("user@example.com", None)
        mock_posthog.set.assert_called_once()
        mock_posthog.set_once.assert_called_once()

    def test_identify_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        identify_user("user@example.com", {"email": "user@example.com"})

    def test_identify_handles_exception(self, mock_posthog):
        mock_posthog.set.side_effect = Exception("PostHog error")

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
        # capture called with keyword args: event, distinct_id, properties
        assert call_args.kwargs.get("event") == "test:event"
        assert call_args.kwargs.get("distinct_id") == "user1"
        props = call_args.kwargs.get("properties")
        assert props["key"] == "value"
        assert "timestamp" in props

    def test_capture_with_none_properties(self, mock_posthog):
        capture_event("user1", "test:event", None)
        mock_posthog.capture.assert_called_once()
        call_args = mock_posthog.capture.call_args
        props = call_args.kwargs.get("properties")
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
        # identify_user uses set/set_once
        assert mock_posthog.set.call_count == 1
        assert mock_posthog.set_once.call_count == 1
        assert mock_posthog.capture.call_count == 1

        # Verify set properties contain email/name/signup_method
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["email"] == "user@example.com"
        assert set_props["name"] == "Alice"
        assert set_props["signup_method"] == "workos"

        # Verify capture event name
        assert mock_posthog.capture.call_args.kwargs.get("event") == AnalyticsEvents.USER_SIGNED_UP

    def test_default_signup_method(self, mock_posthog):
        track_signup("user1", "user@example.com")
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["signup_method"] == "workos"

    def test_custom_signup_method(self, mock_posthog):
        track_signup("user1", "user@example.com", signup_method="google")
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["signup_method"] == "google"

    def test_extra_properties_merged(self, mock_posthog):
        track_signup("user1", "user@example.com", properties={"referral": "friend"})
        capture_props = mock_posthog.capture.call_args.kwargs.get("properties")
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
        props = call_args.kwargs.get("properties")
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
        props = call_args.kwargs.get("properties")
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
        # Should call set to update user properties
        assert mock_posthog.set.call_count >= 1
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["plan"] == "pro"
        assert set_props["subscription_status"] == "active"

    def test_non_activated_event_no_identify(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_CANCELLED,
        )

        mock_posthog.set.assert_not_called()

    def test_extra_properties_merged(self, mock_posthog):
        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_RENEWED,
            properties={"renewal_count": 3},
        )

        call_args = mock_posthog.capture.call_args
        props = call_args.kwargs.get("properties")
        assert props["renewal_count"] == 3

    def test_identify_error_handled(self, mock_posthog):
        mock_posthog.set.side_effect = Exception("PostHog error")

        # Should not raise despite set failure
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
        assert call_args.kwargs.get("event") == AnalyticsEvents.PAYMENT_SUCCEEDED
        props = call_args.kwargs.get("properties")
        assert props["payment_id"] == "pay123"
        assert props["amount"] == pytest.approx(29.99)
        assert props["currency"] == "USD"

    def test_removes_none_values(self, mock_posthog):
        track_payment_event(
            "user1",
            AnalyticsEvents.PAYMENT_FAILED,
        )

        call_args = mock_posthog.capture.call_args
        props = call_args.kwargs.get("properties")
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
        props = call_args.kwargs.get("properties")
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
