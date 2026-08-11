"""Unit tests for analytics service (server-side PostHog event tracking).

Hermetic: the PostHog client, the provider registry seam and the wide-event
logger are all mocked. Every assertion pins the exact call contract —
distinct_ids, property dicts, event names, error payloads — so a mutated
line (wrong key, dropped arg, wrong constant, naive timestamp) is caught.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.constants.auth import LOGIN_METHOD_WORKOS
from app.models.payment_models import PlanType, SubscriptionStatus
from app.services.analytics_service import (
    AnalyticsEvents,
    _get_posthog_client,
    capture_event,
    identify_user,
    track_login,
    track_logout,
    track_payment_event,
    track_signup,
    track_subscription_event,
)

_MOD = "app.services.analytics_service"

USER_ID = "user-123"
EMAIL = "user@example.com"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_posthog():
    """PostHog client returned by the (mocked) provider seam."""
    mock_client = MagicMock()
    with patch(f"{_MOD}._get_posthog_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_posthog_none():
    """No PostHog client configured."""
    with patch(f"{_MOD}._get_posthog_client", return_value=None):
        yield


@pytest.fixture
def mock_log():
    """Wide-event logger; every analytics call path logs through it."""
    with patch(f"{_MOD}.log") as mock_logger:
        yield mock_logger


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_utc_iso(value: object) -> None:
    """Pin that timestamps are ISO-8601 strings with an explicit UTC offset."""
    assert isinstance(value, str)
    assert value.endswith("+00:00")
    datetime.fromisoformat(value)


def _assert_capture(
    client: MagicMock, *, event: object, distinct_id: str, expected_props: dict
) -> None:
    """capture() was called exactly once with the exact contract."""
    assert client.capture.call_count == 1
    kwargs = client.capture.call_args.kwargs
    assert kwargs["event"] == event
    assert kwargs["distinct_id"] == distinct_id
    props = dict(kwargs["properties"])
    _assert_utc_iso(props.pop("timestamp"))
    assert props == expected_props


def _assert_identify_set(client: MagicMock, *, distinct_id: str, expected_props: dict) -> None:
    """set() (identify) was called exactly once with the exact properties."""
    assert client.set.call_count == 1
    kwargs = client.set.call_args.kwargs
    assert kwargs["distinct_id"] == distinct_id
    assert dict(kwargs["properties"]) == expected_props


def _assert_identify_set_ts(
    client: MagicMock, *, distinct_id: str, ts_key: str, expected_props: dict
) -> None:
    """Like _assert_identify_set, with a dynamic UTC timestamp popped first."""
    assert client.set.call_count == 1
    kwargs = client.set.call_args.kwargs
    assert kwargs["distinct_id"] == distinct_id
    props = dict(kwargs["properties"])
    _assert_utc_iso(props.pop(ts_key))
    assert props == expected_props


def _assert_set_once(client: MagicMock, *, distinct_id: str) -> None:
    """set_once() was called exactly once with a first_seen UTC timestamp."""
    assert client.set_once.call_count == 1
    kwargs = client.set_once.call_args.kwargs
    assert kwargs["distinct_id"] == distinct_id
    props = kwargs["properties"]
    assert set(props) == {"first_seen"}
    _assert_utc_iso(props["first_seen"])


def _assert_metadata_set(
    client: MagicMock, *, distinct_id: str, expected_props: dict, ts_key: str | None = None
) -> None:
    """set() (subscription metadata) was called exactly once with the exact props."""
    assert client.set.call_count == 1
    kwargs = client.set.call_args.kwargs
    assert kwargs["distinct_id"] == distinct_id
    props = dict(kwargs["properties"])
    if ts_key is not None:
        _assert_utc_iso(props.pop(ts_key))
    assert props == expected_props


# ---------------------------------------------------------------------------
# AnalyticsEvents
# ---------------------------------------------------------------------------


class TestAnalyticsEvents:
    def test_event_constants_match_frontend_conventions(self):
        assert AnalyticsEvents.USER_SIGNED_UP == "user:signed_up"
        assert AnalyticsEvents.USER_LOGGED_IN == "user:logged_in"
        assert AnalyticsEvents.USER_LOGGED_OUT == "user:logged_out"
        assert AnalyticsEvents.NURTURE_EMAIL_SENT == "nurture:email_sent"
        assert AnalyticsEvents.PAYMENT_SUCCEEDED == "payment:succeeded"
        assert AnalyticsEvents.PAYMENT_FAILED == "payment:failed"
        assert AnalyticsEvents.PAYMENT_REFUNDED == "payment:refunded"
        assert AnalyticsEvents.SUBSCRIPTION_ACTIVATED == "subscription:activated"
        assert AnalyticsEvents.SUBSCRIPTION_RENEWED == "subscription:renewed"
        assert AnalyticsEvents.SUBSCRIPTION_CANCELLED == "subscription:cancelled"
        assert AnalyticsEvents.SUBSCRIPTION_EXPIRED == "subscription:expired"
        assert AnalyticsEvents.SUBSCRIPTION_FAILED == "subscription:failed"


# ---------------------------------------------------------------------------
# _get_posthog_client
# ---------------------------------------------------------------------------


class TestGetPosthogClient:
    def test_returns_registered_client(self):
        client = object()
        with patch(f"{_MOD}.providers") as mock_providers:
            mock_providers.get.return_value = client
            assert _get_posthog_client() is client
            mock_providers.get.assert_called_once_with("posthog")

    def test_returns_none_when_unregistered(self):
        with patch(f"{_MOD}.providers") as mock_providers:
            mock_providers.get.return_value = None
            assert _get_posthog_client() is None


# ---------------------------------------------------------------------------
# identify_user
# ---------------------------------------------------------------------------


class TestIdentifyUser:
    def test_identify_with_properties(self, mock_posthog):
        identify_user(EMAIL, {"email": EMAIL, "plan": "pro"})

        _assert_identify_set(
            mock_posthog, distinct_id=EMAIL, expected_props={"email": EMAIL, "plan": "pro"}
        )
        _assert_set_once(mock_posthog, distinct_id=EMAIL)

    def test_identify_with_none_properties(self, mock_posthog):
        identify_user(EMAIL, None)

        _assert_identify_set(mock_posthog, distinct_id=EMAIL, expected_props={})
        _assert_set_once(mock_posthog, distinct_id=EMAIL)

    def test_skips_when_no_client(self, mock_posthog_none, mock_log):
        identify_user(EMAIL, {"email": EMAIL})

        mock_log.debug.assert_called_once_with("PostHog client not available, skipping identify")
        mock_log.error.assert_not_called()

    def test_set_failure_logs_and_stops(self, mock_posthog, mock_log):
        mock_posthog.set.side_effect = RuntimeError("posthog down")

        identify_user(EMAIL, {"email": EMAIL})

        mock_posthog.set_once.assert_not_called()
        mock_log.error.assert_called_once_with(
            "Failed to identify user in PostHog",
            error="posthog down",
            error_type="RuntimeError",
            user_id=EMAIL,
        )


# ---------------------------------------------------------------------------
# capture_event
# ---------------------------------------------------------------------------


class TestCaptureEvent:
    def test_capture_basic_event(self, mock_posthog):
        capture_event(USER_ID, "test:event", {"key": "value"})

        _assert_capture(
            mock_posthog, event="test:event", distinct_id=USER_ID, expected_props={"key": "value"}
        )

    def test_capture_with_none_properties(self, mock_posthog):
        capture_event(USER_ID, "test:event", None)

        _assert_capture(mock_posthog, event="test:event", distinct_id=USER_ID, expected_props={})

    def test_sets_analytics_log_context(self, mock_posthog, mock_log):
        capture_event(USER_ID, "test:event", {"key": "value"})

        mock_log.set.assert_called_once_with(analytics={"user_id": USER_ID, "event": "test:event"})

    def test_skips_when_no_client(self, mock_posthog_none, mock_log):
        capture_event(USER_ID, "test:event")

        mock_log.debug.assert_called_once_with(
            "PostHog client not available, skipping event", event="test:event"
        )
        mock_log.error.assert_not_called()

    def test_capture_failure_logs(self, mock_posthog, mock_log):
        mock_posthog.capture.side_effect = RuntimeError("posthog down")

        capture_event(USER_ID, "test:event", {"key": "value"})

        mock_log.error.assert_called_once_with(
            "Failed to capture event in PostHog",
            event="test:event",
            error="posthog down",
            error_type="RuntimeError",
            user_id=USER_ID,
        )


# ---------------------------------------------------------------------------
# track_signup
# ---------------------------------------------------------------------------


class TestTrackSignup:
    def test_identifies_and_captures(self, mock_posthog):
        track_signup(USER_ID, EMAIL, name="Alice")

        _assert_identify_set_ts(
            mock_posthog,
            distinct_id=EMAIL,
            ts_key="created_at",
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": "Alice",
                "signup_method": "workos",
            },
        )
        _assert_set_once(mock_posthog, distinct_id=EMAIL)
        _assert_capture(
            mock_posthog,
            event="user:signed_up",
            distinct_id=EMAIL,
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": "Alice",
                "signup_method": "workos",
            },
        )

    def test_default_signup_method(self, mock_posthog):
        track_signup(USER_ID, EMAIL)

        assert (
            mock_posthog.set.call_args.kwargs["properties"]["signup_method"] == LOGIN_METHOD_WORKOS
        )
        assert (
            mock_posthog.capture.call_args.kwargs["properties"]["signup_method"]
            == LOGIN_METHOD_WORKOS
        )

    def test_custom_signup_method(self, mock_posthog):
        track_signup(USER_ID, EMAIL, signup_method="google")

        assert mock_posthog.set.call_args.kwargs["properties"]["signup_method"] == "google"
        assert mock_posthog.capture.call_args.kwargs["properties"]["signup_method"] == "google"

    def test_extra_properties_merged_into_capture_only(self, mock_posthog):
        track_signup(USER_ID, EMAIL, properties={"referral": "friend"})

        _assert_capture(
            mock_posthog,
            event="user:signed_up",
            distinct_id=EMAIL,
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": None,
                "signup_method": "workos",
                "referral": "friend",
            },
        )
        # extra properties extend only the event, not the identify payload
        set_props = mock_posthog.set.call_args.kwargs["properties"]
        assert "referral" not in set_props

    def test_skips_when_no_client(self, mock_posthog_none, mock_log):
        track_signup(USER_ID, EMAIL)  # must not raise

        mock_log.error.assert_not_called()


# ---------------------------------------------------------------------------
# track_login
# ---------------------------------------------------------------------------


class TestTrackLogin:
    def test_identifies_and_captures(self, mock_posthog):
        track_login(USER_ID, EMAIL, name="Bob", login_method="google")

        _assert_identify_set_ts(
            mock_posthog,
            distinct_id=EMAIL,
            ts_key="last_login_at",
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": "Bob",
                "last_login_method": "google",
            },
        )
        _assert_set_once(mock_posthog, distinct_id=EMAIL)
        _assert_capture(
            mock_posthog,
            event="user:logged_in",
            distinct_id=EMAIL,
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": "Bob",
                "login_method": "google",
            },
        )

    def test_default_login_method(self, mock_posthog):
        track_login(USER_ID, EMAIL)

        assert (
            mock_posthog.set.call_args.kwargs["properties"]["last_login_method"]
            == LOGIN_METHOD_WORKOS
        )
        assert (
            mock_posthog.capture.call_args.kwargs["properties"]["login_method"]
            == LOGIN_METHOD_WORKOS
        )

    def test_extra_properties_merged_into_capture_only(self, mock_posthog):
        track_login(USER_ID, EMAIL, properties={"device": "mac"})

        _assert_capture(
            mock_posthog,
            event="user:logged_in",
            distinct_id=EMAIL,
            expected_props={
                "user_id": USER_ID,
                "email": EMAIL,
                "name": None,
                "login_method": "workos",
                "device": "mac",
            },
        )


# ---------------------------------------------------------------------------
# track_logout
# ---------------------------------------------------------------------------


class TestTrackLogout:
    def test_captures_logout_event(self, mock_posthog):
        track_logout(USER_ID, EMAIL, properties={"session_id": "s1"})

        _assert_capture(
            mock_posthog,
            event="user:logged_out",
            distinct_id=EMAIL,
            expected_props={"user_id": USER_ID, "email": EMAIL, "session_id": "s1"},
        )
        mock_posthog.set.assert_not_called()

    def test_captures_without_extra_properties(self, mock_posthog):
        track_logout(USER_ID, EMAIL)

        _assert_capture(
            mock_posthog,
            event="user:logged_out",
            distinct_id=EMAIL,
            expected_props={"user_id": USER_ID, "email": EMAIL},
        )
        mock_posthog.set.assert_not_called()


# ---------------------------------------------------------------------------
# track_subscription_event
# ---------------------------------------------------------------------------


class TestTrackSubscriptionEvent:
    def test_captures_event_with_all_fields(self, mock_posthog):
        track_subscription_event(
            USER_ID,
            AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            subscription_id="sub123",
            plan_name="pro",
            amount=9.99,
            currency="USD",
        )

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            distinct_id=USER_ID,
            expected_props={
                "subscription_id": "sub123",
                "plan_name": "pro",
                "amount": 9.99,
                "currency": "USD",
            },
        )

    def test_strips_none_values_from_event_properties(self, mock_posthog):
        track_subscription_event(
            USER_ID, AnalyticsEvents.SUBSCRIPTION_CANCELLED, subscription_id="sub123"
        )

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.SUBSCRIPTION_CANCELLED,
            distinct_id=USER_ID,
            expected_props={"subscription_id": "sub123"},
        )

    def test_extra_properties_merged(self, mock_posthog):
        track_subscription_event(
            USER_ID, AnalyticsEvents.SUBSCRIPTION_RENEWED, properties={"renewal_count": 3}
        )

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.SUBSCRIPTION_RENEWED,
            distinct_id=USER_ID,
            expected_props={"renewal_count": 3},
        )

    def test_sets_subscription_log_context(self, mock_posthog, mock_log):
        track_subscription_event(
            USER_ID,
            AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
            plan_name="pro",
            subscription_id="sub123",
        )

        assert mock_log.set.call_args_list[0].kwargs == {
            "subscription": {
                "user_id": USER_ID,
                "event_type": AnalyticsEvents.SUBSCRIPTION_ACTIVATED,
                "plan_name": "pro",
                "subscription_id": "sub123",
            }
        }
        # the nested capture_event also logs its own analytics context
        assert len(mock_log.set.call_args_list) == 2

    def test_activated_sets_user_metadata(self, mock_posthog):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_ACTIVATED, plan_name="pro")

        _assert_metadata_set(
            mock_posthog,
            distinct_id=USER_ID,
            ts_key="subscription_activated_at",
            expected_props={
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
            },
        )

    def test_renewed_sets_user_metadata(self, mock_posthog):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_RENEWED)

        _assert_metadata_set(
            mock_posthog,
            distinct_id=USER_ID,
            expected_props={
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
            },
        )

    def test_cancelled_sets_user_metadata(self, mock_posthog):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_CANCELLED)

        _assert_metadata_set(
            mock_posthog,
            distinct_id=USER_ID,
            expected_props={"subscription_status": SubscriptionStatus.CANCELLED},
        )

    def test_expired_sets_user_metadata(self, mock_posthog):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_EXPIRED)

        _assert_metadata_set(
            mock_posthog,
            distinct_id=USER_ID,
            expected_props={
                "plan": PlanType.FREE,
                "is_subscribed": False,
                "subscription_status": SubscriptionStatus.EXPIRED,
            },
        )

    def test_unmapped_event_skips_metadata_set(self, mock_posthog, mock_log):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_FAILED)

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.SUBSCRIPTION_FAILED,
            distinct_id=USER_ID,
            expected_props={},
        )
        mock_posthog.set.assert_not_called()
        # The default case must swallow unmapped events silently: no metadata
        # update attempt and no error logged (a dropped `case _` falls through
        # to an UnboundLocalError that this must catch).
        mock_log.error.assert_not_called()

    def test_set_failure_logs(self, mock_posthog, mock_log):
        mock_posthog.set.side_effect = RuntimeError("posthog down")

        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_ACTIVATED)

        mock_log.error.assert_called_once_with(
            "Failed to update user subscription properties",
            error="posthog down",
            error_type="RuntimeError",
            user_id=USER_ID,
        )

    def test_skips_metadata_when_no_client(self, mock_posthog_none, mock_log):
        track_subscription_event(USER_ID, AnalyticsEvents.SUBSCRIPTION_ACTIVATED)  # must not raise

        mock_log.error.assert_not_called()


# ---------------------------------------------------------------------------
# track_payment_event
# ---------------------------------------------------------------------------


class TestTrackPaymentEvent:
    def test_captures_payment_event(self, mock_posthog):
        track_payment_event(
            USER_ID,
            AnalyticsEvents.PAYMENT_SUCCEEDED,
            payment_id="pay123",
            amount=29.99,
            currency="USD",
        )

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.PAYMENT_SUCCEEDED,
            distinct_id=USER_ID,
            expected_props={"payment_id": "pay123", "amount": 29.99, "currency": "USD"},
        )

    def test_strips_none_values(self, mock_posthog):
        track_payment_event(USER_ID, AnalyticsEvents.PAYMENT_FAILED)

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.PAYMENT_FAILED,
            distinct_id=USER_ID,
            expected_props={},
        )

    def test_extra_properties_merged(self, mock_posthog):
        track_payment_event(
            USER_ID, AnalyticsEvents.PAYMENT_REFUNDED, properties={"reason": "duplicate"}
        )

        _assert_capture(
            mock_posthog,
            event=AnalyticsEvents.PAYMENT_REFUNDED,
            distinct_id=USER_ID,
            expected_props={"reason": "duplicate"},
        )
