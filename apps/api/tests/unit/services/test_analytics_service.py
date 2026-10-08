"""Unit tests for analytics service."""

import contextvars
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

from pydantic import ValidationError
import pytest
import time_machine

from app.constants.analytics import (
    ANALYTICS_DAY_TIMEZONE,
    AT_MOST_ONCE_KEY_PREFIX,
    POSTHOG_PROVIDER_KEY,
)
from app.services.analytics_service import (
    _get_posthog_client,
    analytics_day_start,
    capture,
    identify_user,
    track_signup,
    track_subscription_event,
)
from shared.py.analytics import Dedupe, PlatformIdentity, UserId
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.auth import UserActive, UserLoggedOut, UserSignedUp
from shared.py.analytics.catalog.billing import (
    PaymentSucceeded,
    SubscriptionActivated,
    SubscriptionCancelled,
)
from shared.py.analytics.catalog.chat import ChatComposerPlusMenuClicked
from shared.py.analytics.catalog.memory import MemoryCleared
from shared.py.analytics.context import (
    AnalyticsContext,
    MissingAnalyticsContextError,
    analytics_context,
    worker_context,
)
from tests.helpers import captured_wide_event, drain_at_most_once_sends

USER_1 = UserId("6812f0b3c9a14e2b7d5a91cc")
USER_2 = UserId("6812f0b3c9a14e2b7d5a91dd")
CANCELLED = SubscriptionCancelled(
    subscription_id="sub123", product_id="prod_1", billing_interval="Month"
)
OCCURRED_AT = datetime(2026, 10, 8, 6, 30, tzinfo=UTC)
#: 23:00 IST on Oct 8, which is still Oct 8 17:30 UTC; two hours later is Oct 9 in IST.
LATE_EVENING_IST = datetime(2026, 10, 8, 17, 30, tzinfo=UTC)
IST_DAY_START = datetime(2026, 10, 8, tzinfo=ANALYTICS_DAY_TIMEZONE)
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

    async def test_the_wide_event_names_the_captured_event_and_its_person(self, mock_posthog):
        async with captured_wide_event() as event:
            capture(USER_1, MemoryCleared(deleted_count=3))

        assert event["analytics"] == {"user_id": USER_1.value, "event": "memory:cleared"}

    def test_a_none_field_is_left_out_not_sent_as_null(self, mock_posthog):
        capture(USER_1, PaymentSucceeded(payment_id="pay_1", currency="USD", amount=None))

        props = mock_posthog.capture.call_args.kwargs["properties"]
        assert "amount" not in props
        assert props["payment_id"] == "pay_1"

    def test_a_platform_identity_is_sent_as_platform_colon_id(self, mock_posthog):
        capture(PlatformIdentity("telegram", "42"), UserLoggedOut())

        assert mock_posthog.capture.call_args.kwargs["distinct_id"] == "telegram:42"

    def test_no_timestamp_property_rides_along(self, mock_posthog):
        """The event time is the SDK's timestamp; a "timestamp" property was a second, wrong copy."""
        capture(USER_1, UserLoggedOut())

        assert "timestamp" not in mock_posthog.capture.call_args.kwargs["properties"]

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
    """A Dedupe is the only thing standing between a re-sent fact and a double count.

    PostHog merges two rows only when uuid, event, timestamp and distinct_id all
    match, so the uuid AND the timestamp must come from the fact, never now().
    """

    def test_no_dedupe_sends_no_uuid(self, mock_posthog):
        """A uuid derived from nothing would collapse genuinely repeated user actions into one."""
        capture(USER_1, MemoryCleared(deleted_count=1))

        assert mock_posthog.capture.call_args.kwargs["uuid"] is None
        assert mock_posthog.capture.call_args.kwargs["timestamp"] is None

    def test_a_retry_with_the_same_dedupe_is_the_same_row(self, posthog_events):
        """Through the real SDK: the retry's message matches on uuid, timestamp, event and distinct_id."""
        fact = Dedupe(key="run-1", occurred_at=OCCURRED_AT)

        capture(USER_1, MemoryCleared(deleted_count=1), fact)
        capture(USER_1, MemoryCleared(deleted_count=1), fact)

        first, retry = posthog_events
        for field in ("uuid", "timestamp", "event", "distinct_id"):
            assert first[field] == retry[field], field
        assert UUID(first["uuid"]).version == 5
        assert datetime.fromisoformat(first["timestamp"]) == OCCURRED_AT

    @pytest.mark.regression
    def test_a_deduped_event_is_stored_at_its_own_time_not_shifted_by_sent_at(self, posthog_events):
        """PostHog moves timestamp by its clock minus sent_at (+3.6s on gaia-test) unless told not to."""
        capture(USER_1, MemoryCleared(deleted_count=1), Dedupe("run-1", OCCURRED_AT))

        [sent] = posthog_events
        assert sent["properties"]["$ignore_sent_at"] is True

    def test_a_live_event_keeps_posthogs_clock_skew_correction(self, posthog_events):
        """Without a Dedupe the SDK's own now() is the time, and sent_at corrects a skewed host clock."""
        capture(USER_1, MemoryCleared(deleted_count=1))

        [sent] = posthog_events
        assert "$ignore_sent_at" not in sent["properties"]

    def test_the_uuid_changes_with_event_user_and_key(self, mock_posthog):
        """A uuid that ignores any of its three inputs silently deduplicates events that are not repeats."""
        capture(USER_1, MemoryCleared(deleted_count=1), Dedupe("run-1", OCCURRED_AT))
        capture(USER_1, UserLoggedOut(), Dedupe("run-1", OCCURRED_AT))
        capture(USER_2, MemoryCleared(deleted_count=1), Dedupe("run-1", OCCURRED_AT))
        capture(USER_1, MemoryCleared(deleted_count=1), Dedupe("run-2", OCCURRED_AT))

        uuids = [call.kwargs["uuid"] for call in mock_posthog.capture.call_args_list]
        assert len(set(uuids)) == 4

    def test_a_naive_occurrence_time_is_refused(self):
        """A naive time is read in the runner's own zone, so two workers would stamp different rows."""
        with pytest.raises(ValueError, match="timezone-aware"):
            Dedupe("run-1", datetime(2026, 10, 8, 12, 0))

    def test_an_at_most_once_event_needs_a_dedupe(self, mock_posthog):
        with pytest.raises(ValueError, match="needs a Dedupe"):
            capture(USER_1, UserActive())
        mock_posthog.capture.assert_not_called()

    def test_a_deduped_capture_failure_is_reported_loudly(self, mock_posthog):
        """Analytics never raises into the caller, so this failure is visible only via the wide event."""
        mock_posthog.capture.side_effect = RuntimeError("PostHog error")

        with patch("app.services.analytics_service.log") as mock_log:
            capture(USER_1, UserLoggedOut(), Dedupe("run-1", OCCURRED_AT))

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.args[0] == "Failed to capture event in PostHog"
        kwargs = mock_log.error.call_args.kwargs
        assert kwargs["event"] == "user:logged_out"
        assert kwargs["user_id"] == USER_1.value
        assert kwargs["error"] == "PostHog error"
        assert kwargs["error_type"] == "RuntimeError"


class TestAttribution:
    """Every server event says who acted, what started the run and where, from the bound context."""

    def test_the_bound_context_is_stamped_on_the_event(self, posthog_events):
        with analytics_context(worker_context(Trigger.SCHEDULE)):
            capture(USER_1, MemoryCleared(deleted_count=1))

        [event] = posthog_events
        assert {key: event["properties"][key] for key in ("actor", "trigger", "surface")} == {
            "actor": "agent",
            "trigger": "schedule",
            "surface": "worker",
        }

    def test_an_emitter_cannot_pass_attribution_by_hand(self):
        with pytest.raises(ValidationError):
            MemoryCleared(deleted_count=1, actor="user")  # type: ignore[call-arg]  # the extra field is the point: the model must refuse it

    def test_a_capture_with_no_context_bound_fails(self, mock_posthog_none):
        """Fails even with no client configured, so a missing entry point shows up in every local run."""
        with pytest.raises(MissingAnalyticsContextError):
            contextvars.Context().run(capture, USER_1, MemoryCleared(deleted_count=1))


def _user_context(surface: EntrySurface) -> AnalyticsContext:
    return AnalyticsContext(
        attribution=Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=surface)
    )


class TestAnalyticsDayStart:
    def test_the_last_instant_of_an_ist_day_starts_at_its_midnight(self):
        last_instant = datetime(2026, 10, 8, 23, 59, 59, 999999, tzinfo=ANALYTICS_DAY_TIMEZONE)

        assert analytics_day_start(last_instant) == IST_DAY_START

    def test_a_utc_evening_already_in_the_next_ist_day_starts_there(self):
        assert analytics_day_start(LATE_EVENING_IST + timedelta(hours=1)) == datetime(
            2026, 10, 9, tzinfo=ANALYTICS_DAY_TIMEZONE
        )


@pytest.mark.usefixtures("fake_redis")
class TestUserActive:
    """user:active is the one definition of an active user: once per user per IST day, any surface."""

    @staticmethod
    def _active_marks(events: list[dict[str, object]]) -> list[dict[str, object]]:
        return [event for event in events if event["event"] == "user:active"]

    async def test_many_user_events_on_many_surfaces_mark_the_user_active_once(
        self, posthog_events
    ):
        with time_machine.travel(LATE_EVENING_IST, tick=False):
            with analytics_context(_user_context(EntrySurface.WEB)):
                capture(USER_1, MemoryCleared(deleted_count=1))
                capture(USER_1, UserLoggedOut())
            with analytics_context(_user_context(EntrySurface.BOT)):
                capture(USER_1, MemoryCleared(deleted_count=2))
            with analytics_context(_user_context(EntrySurface.VOICE)):
                capture(USER_1, MemoryCleared(deleted_count=3))
            await drain_at_most_once_sends()

        [mark] = self._active_marks(posthog_events)
        assert mark["distinct_id"] == USER_1.value
        # The first action's surface; the timestamp is the IST day's start, fixed.
        assert mark["properties"]["surface"] == "web"
        assert datetime.fromisoformat(mark["timestamp"]) == IST_DAY_START

    async def test_the_next_ist_day_marks_the_user_active_again(self, posthog_events):
        with analytics_context(_user_context(EntrySurface.WEB)):
            with time_machine.travel(LATE_EVENING_IST, tick=False):
                capture(USER_1, MemoryCleared(deleted_count=1))
                await drain_at_most_once_sends()
            with time_machine.travel(LATE_EVENING_IST + timedelta(hours=2), tick=False):
                capture(USER_1, MemoryCleared(deleted_count=1))
                await drain_at_most_once_sends()

        assert len(self._active_marks(posthog_events)) == 2

    async def test_each_user_is_marked_on_their_own(self, posthog_events):
        with analytics_context(_user_context(EntrySurface.WEB)):
            capture(USER_1, MemoryCleared(deleted_count=1))
            capture(USER_2, MemoryCleared(deleted_count=1))
            await drain_at_most_once_sends()

        assert {mark["distinct_id"] for mark in self._active_marks(posthog_events)} == {
            USER_1.value,
            USER_2.value,
        }

    async def test_agent_work_never_marks_the_user_active(self, posthog_events):
        """A scheduled workflow running for an idle user is not that user being active."""
        with analytics_context(worker_context(Trigger.SCHEDULE)):
            capture(USER_1, MemoryCleared(deleted_count=1))
        with analytics_context(_user_context(EntrySurface.WEB).acting_as(Actor.AGENT)):
            capture(USER_1, MemoryCleared(deleted_count=1))
        await drain_at_most_once_sends()

        assert self._active_marks(posthog_events) == []

    async def test_the_gate_outlives_the_day_it_keys(self, posthog_events, fake_redis):
        with analytics_context(_user_context(EntrySurface.WEB)):
            capture(USER_1, MemoryCleared(deleted_count=1))
            await drain_at_most_once_sends()

        [key] = await fake_redis.keys(f"{AT_MOST_ONCE_KEY_PREFIX}*")
        ttl = UserActive.at_most_once_ttl
        assert ttl is not None
        assert await fake_redis.ttl(key) == int(ttl.total_seconds())

    async def test_an_unlinked_bot_user_is_not_marked(self, posthog_events):
        """Only a GAIA user has a day to be active on; the platform id merges in on linking."""
        with analytics_context(_user_context(EntrySurface.BOT)):
            capture(PlatformIdentity("telegram", "42"), UserLoggedOut())
            await drain_at_most_once_sends()

        assert self._active_marks(posthog_events) == []


# ---------------------------------------------------------------------------
# track_signup
# ---------------------------------------------------------------------------


class TestTrackSignup:
    def test_calls_identify_and_capture(self, mock_posthog):
        track_signup(USER_1, "user@example.com", name="Alice", signup_method="GoogleOAuth")
        assert mock_posthog.set.call_count == 1
        assert mock_posthog.set_once.call_count == 1
        assert mock_posthog.capture.call_count == 1

        set_props = mock_posthog.set.call_args.kwargs.get("properties")
        assert set_props["email"] == "user@example.com"
        assert set_props["name"] == "Alice"
        assert set_props["signup_method"] == "GoogleOAuth"

        capture_kwargs = mock_posthog.capture.call_args.kwargs
        assert capture_kwargs.get("event") == "user:signed_up"
        assert capture_kwargs["properties"]["signup_method"] == "GoogleOAuth"

    def test_a_method_workos_did_not_report_is_left_out(self, mock_posthog):
        track_signup(USER_1, "user@example.com", signup_method=None)

        assert "signup_method" not in mock_posthog.capture.call_args.kwargs["properties"]

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_signup(USER_1, "user@example.com", signup_method="GoogleOAuth")


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

    def test_skips_when_no_client(self, mock_posthog_none):
        # Should not raise
        track_subscription_event(USER_1, ACTIVATED)
