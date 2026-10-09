"""Unit tests for analytics service."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from app.constants.analytics import POSTHOG_PROVIDER_KEY
from app.models.payment_models import PlanType, SubscriptionStatus
from app.services.analytics_service import (
    _get_posthog_client,
    agent_run_lifecycle,
    capture,
    identify_user,
    track_signup,
    track_subscription_event,
)
from shared.py.analytics import PlatformIdentity, UserId
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunFailed, AgentRunStarted
from shared.py.analytics.catalog.auth import UserLoggedOut, UserSignedUp
from shared.py.analytics.catalog.billing import (
    PaymentSucceeded,
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionExpired,
    SubscriptionRenewed,
)
from shared.py.analytics.catalog.chat import ChatComposerPlusMenuClicked
from shared.py.analytics.catalog.memory import MemoryCleared
from tests.helpers import captured_wide_event

USER_1 = UserId("6812f0b3c9a14e2b7d5a91cc")
USER_2 = UserId("6812f0b3c9a14e2b7d5a91dd")
COMMS_RUN = AgentRunStarted(agent="comms", mode="interactive", conversation_id="conv-1")
EXECUTOR_RUN = AgentRunStarted(
    agent="executor", mode="background", conversation_id="conv-1", task_id="task-1"
)
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


class TestAgentRunLifecycle:
    """Every run_failed and run_completed follows the run_started of the same run."""

    def _events(self, capture: MagicMock) -> list[tuple[object, str | None]]:
        return [(c.args[1], c.kwargs.get("dedupe_key")) for c in capture.call_args_list]

    def test_a_clean_run_is_started_then_completed_with_its_terminal_props(self) -> None:
        with patch("app.services.analytics_service.capture") as capture:
            with agent_run_lifecycle(USER_1.value, EXECUTOR_RUN, dedupe_key="task-1") as run:
                run.queued = True

        assert self._events(capture) == [
            (EXECUTOR_RUN, None),
            (AgentRunCompleted(**EXECUTOR_RUN.model_dump(), queued=True), "task-1"),
        ]

    def test_a_raised_failure_is_started_then_failed_and_still_raises(self) -> None:
        with (
            patch("app.services.analytics_service.capture") as capture,
            pytest.raises(KeyError),
            agent_run_lifecycle(USER_1.value, COMMS_RUN, dedupe_key="task-1"),
        ):
            raise KeyError("boom")

        assert self._events(capture) == [
            (COMMS_RUN, None),
            (AgentRunFailed(**COMMS_RUN.model_dump(), reason="KeyError"), "task-1"),
        ]

    async def test_a_cancelled_run_is_started_then_failed_and_still_cancels(self) -> None:
        async def run_until_cancelled() -> None:
            with agent_run_lifecycle(USER_1.value, COMMS_RUN, dedupe_key="task-1"):
                await asyncio.Event().wait()

        with patch("app.services.analytics_service.capture") as capture:
            task = asyncio.create_task(run_until_cancelled())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert [c.args[0] for c in capture.call_args_list] == [USER_1, USER_1]
        assert self._events(capture) == [
            (COMMS_RUN, None),
            (AgentRunFailed(**COMMS_RUN.model_dump(), reason="cancelled"), "task-1"),
        ]

    def test_a_failure_the_body_handled_is_failed_with_its_reason(self) -> None:
        with patch("app.services.analytics_service.capture") as capture:
            with agent_run_lifecycle(USER_1.value, EXECUTOR_RUN, dedupe_key="task-1") as run:
                run.failure_reason = "approval_lost"

        assert self._events(capture)[1] == (
            AgentRunFailed(**EXECUTOR_RUN.model_dump(), reason="approval_lost"),
            "task-1",
        )

    def test_a_paused_run_has_no_terminal_event(self) -> None:
        with patch("app.services.analytics_service.capture") as capture:
            with agent_run_lifecycle(USER_1.value, EXECUTOR_RUN) as run:
                run.paused = True

        assert self._events(capture) == [(EXECUTOR_RUN, None)]

    def test_no_user_id_captures_nothing(self) -> None:
        with (
            patch("app.services.analytics_service.capture") as capture,
            pytest.raises(ValueError),
            agent_run_lifecycle("", COMMS_RUN),
        ):
            raise ValueError

        capture.assert_not_called()


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

        mock_posthog.set.assert_called_once_with(
            distinct_id=USER_1.value,
            properties={"subscription_status": SubscriptionStatus.CANCELLED},
        )

    def test_an_expiry_drops_the_user_back_to_free(self, mock_posthog):
        track_subscription_event(USER_1, SubscriptionExpired(subscription_id="sub123"))

        mock_posthog.set.assert_called_once_with(
            distinct_id=USER_1.value,
            properties={
                "plan": PlanType.FREE,
                "is_subscribed": False,
                "subscription_status": SubscriptionStatus.EXPIRED,
            },
        )

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
