"""Unit tests for analytics service."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.services.analytics_service import (
    AnalyticsEvents,
    capture_context_event,
    capture_event,
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


class TestAnalyticsEvents:
    def test_event_constants_exist(self):
        assert AnalyticsEvents.USER_SIGNED_UP == "user:signed_up"
        assert AnalyticsEvents.PAYMENT_SUCCEEDED == "payment:succeeded"
        assert AnalyticsEvents.PAYMENT_FAILED == "payment:failed"
        assert AnalyticsEvents.SUBSCRIPTION_ACTIVATED == "subscription:activated"
        assert AnalyticsEvents.SUBSCRIPTION_RENEWED == "subscription:renewed"
        assert AnalyticsEvents.SUBSCRIPTION_CANCELLED == "subscription:cancelled"
        assert AnalyticsEvents.SUBSCRIPTION_EXPIRED == "subscription:expired"


# ---------------------------------------------------------------------------
# identify_user
# ---------------------------------------------------------------------------


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


class TestCaptureEventDedupe:
    """``dedupe_key`` is the only thing standing between a retryable worker
    task and a double-counted milestone: it becomes a stable event uuid, and
    PostHog stores the same uuid once. Nothing exercised it, so every way of
    getting that uuid wrong was invisible.
    """

    def test_no_dedupe_key_sends_no_uuid(self, mock_posthog):
        """An ordinary capture must stay un-deduped — a uuid derived from
        nothing would collapse genuinely repeated user actions into one."""
        capture_event("user1", "test:event", {"key": "value"})

        assert "uuid" not in mock_posthog.capture.call_args.kwargs

    def test_dedupe_key_attaches_a_uuid_alongside_the_normal_payload(self, mock_posthog):
        capture_event("user1", "test:event", {"key": "value"}, dedupe_key="run-1")

        mock_posthog.capture.assert_called_once()
        kwargs = mock_posthog.capture.call_args.kwargs
        assert kwargs["event"] == "test:event"
        assert kwargs["distinct_id"] == "user1"
        assert kwargs["properties"]["key"] == "value"
        assert UUID(kwargs["uuid"]).version == 5

    def test_the_same_capture_twice_carries_the_same_uuid(self, mock_posthog):
        """The retry case: an ARQ task re-runs its whole body, so the second
        pass must produce a uuid PostHog recognises as already stored."""
        capture_event("user1", "test:event", {"key": "value"}, dedupe_key="run-1")
        capture_event("user1", "test:event", {"key": "other"}, dedupe_key="run-1")

        first, second = (call.kwargs["uuid"] for call in mock_posthog.capture.call_args_list)
        assert first == second

    def test_the_uuid_changes_with_event_user_and_key(self, mock_posthog):
        """A uuid that ignores any of its three inputs deduplicates events
        that are not repeats — silently deleting real data."""
        capture_event("user1", "test:event", dedupe_key="run-1")
        capture_event("user1", "other:event", dedupe_key="run-1")
        capture_event("user2", "test:event", dedupe_key="run-1")
        capture_event("user1", "test:event", dedupe_key="run-2")

        uuids = [call.kwargs["uuid"] for call in mock_posthog.capture.call_args_list]
        assert len(set(uuids)) == 4

    def test_a_deduped_capture_failure_is_reported_loudly(self, mock_posthog):
        """Analytics never raises into the caller, so a broken deduped capture
        can only be seen through the wide event's errors[]."""
        mock_posthog.capture.side_effect = RuntimeError("PostHog error")

        with patch("app.services.analytics_service.log") as mock_log:
            capture_event("user1", "test:event", dedupe_key="run-1")

        mock_log.error.assert_called_once()
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs["event"] == "test:event"
        assert kwargs["user_id"] == "user1"
        assert kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# capture_context_event
# ---------------------------------------------------------------------------


class TestCaptureContextEvent:
    """The helper every authenticated route uses.

    It sends NO distinct_id on purpose — PostHogRequestContextMiddleware has
    already identified the request — so the only things a test can hold it to
    are the event name, the payload, and the fact that it stays silent when
    no client is configured. None of that was asserted anywhere.
    """

    def test_sends_the_event_and_merges_the_timestamp(self, mock_posthog):
        capture_context_event("test:event", {"key": "value"})

        mock_posthog.capture.assert_called_once()
        kwargs = mock_posthog.capture.call_args.kwargs
        assert kwargs.get("event") == "test:event"
        props = kwargs.get("properties")
        assert props["key"] == "value"
        assert "timestamp" in props

    def test_sends_no_distinct_id_so_the_request_context_supplies_it(self, mock_posthog):
        """Passing one here would override the identified context and is the
        difference between this helper and capture_event."""
        capture_context_event("test:event", {"key": "value"})

        call = mock_posthog.capture.call_args
        assert "distinct_id" not in call.kwargs
        assert call.args == ()

    def test_none_properties_still_carries_a_timestamp(self, mock_posthog):
        capture_context_event("test:event", None)

        props = mock_posthog.capture.call_args.kwargs.get("properties")
        assert "timestamp" in props

    def test_the_timestamp_is_offset_aware_utc(self, mock_posthog):
        """`datetime.now()` without UTC yields naive local time, which
        isoformats without an offset — PostHog then reads it as whatever the
        runner's timezone happens to be."""
        capture_context_event("test:event")

        stamped = mock_posthog.capture.call_args.kwargs["properties"]["timestamp"]
        parsed = datetime.fromisoformat(stamped)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_captures_nothing_when_no_client_is_configured(self, mock_posthog_none):
        """A token-less environment must no-op, not raise — the SILENT
        provider strategy is what lets local dev run without analytics."""
        capture_context_event("test:event", {"key": "value"})

    def test_a_failing_client_does_not_propagate(self, mock_posthog):
        """Analytics must never take down the request it is measuring."""
        mock_posthog.capture.side_effect = Exception("PostHog error")

        capture_context_event("test:event")

    def test_a_failing_client_is_reported_loudly(self, mock_posthog):
        """Swallowed silently, a broken PostHog client looks exactly like a
        quiet product. log.error lands in the wide event's errors[], so the
        payload is queryable — and therefore assertable."""
        mock_posthog.capture.side_effect = RuntimeError("PostHog error")

        with patch("app.services.analytics_service.log") as mock_log:
            capture_context_event("test:event")

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == "Failed to capture event in PostHog"
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs["event"] == "test:event"
        assert kwargs["error"] == "PostHog error"
        assert kwargs["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# track_signup
# ---------------------------------------------------------------------------


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

    def test_cancelled_event_updates_subscription_status(self, mock_posthog):
        """SUBSCRIPTION_CANCELLED now updates user properties with cancellation status."""
        from app.models.payment_models import SubscriptionStatus

        track_subscription_event(
            "user1",
            AnalyticsEvents.SUBSCRIPTION_CANCELLED,
        )

        mock_posthog.set.assert_called_once()
        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["subscription_status"] == SubscriptionStatus.CANCELLED

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
            AnalyticsEvents.PAYMENT_FAILED,
            properties={"reason": "duplicate"},
        )

        call_args = mock_posthog.capture.call_args
        props = call_args.kwargs.get("properties")
        assert props["reason"] == "duplicate"


# ---------------------------------------------------------------------------
# flush_events
# ---------------------------------------------------------------------------
