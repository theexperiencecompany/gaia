"""Server-side PostHog capture: catalog events only, attributed to an AnalyticsId."""

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import NAMESPACE_URL, uuid5

from posthog import Posthog

from app.constants.analytics import AGENT_RUN_CANCELLED_REASON, POSTHOG_PROVIDER_KEY
from app.constants.auth import LOGIN_METHOD_WORKOS
from app.core.lazy_loader import providers
from app.models.payment_models import PlanType, SubscriptionStatus
from shared.py.analytics import AnalyticsId, UserId, check_capture, posthog_properties
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunFailed, AgentRunStarted
from shared.py.analytics.catalog.auth import UserLoggedIn, UserSignedUp
from shared.py.analytics.catalog.base import ServerEvent, Surface
from shared.py.analytics.catalog.billing import (
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionExpired,
    SubscriptionRenewed,
)
from shared.py.wide_events import log


class AIFeature(StrEnum):
    """The product capability a metered model call was made on behalf of.

    Each member owns the auxiliary label values that roll up to it, so there is
    no second table to keep in sync; test_every_feature_is_reachable fails on a
    member declared with none. Coarser than the labels on purpose: the
    onboarding one-shots roll up to ONBOARDING while keeping their own labels.
    Which integration ran is agent_name, an open string not ours to close.
    """

    _labels: tuple[str, ...]

    def __new__(cls, value: str, labels: tuple[str, ...] = ()) -> "AIFeature":
        member = str.__new__(cls, value)
        member._value_ = value
        member._labels = labels
        return member

    @property
    def labels(self) -> tuple[str, ...]:
        """The auxiliary call labels booked to this feature."""
        return self._labels

    @classmethod
    def for_label(cls, label: str) -> "AIFeature":
        """Return the feature a one-shot's label belongs to, or UNATTRIBUTED."""
        return _FEATURE_BY_LABEL.get(label, cls.UNATTRIBUTED)

    # Graph-tier spend; attributed from the agent, not from a label.
    CHAT = "chat"
    INTEGRATION = "integration"

    WORKFLOW = "workflow", ("playbook_ask_fill", "playbook_narration")
    MEMORY = "memory", ("profile_extraction",)
    VISION = "vision", ("image_to_text", "tool_media_vision", "vision_fallback")
    MAIL = "mail", ("mail_compose",)
    HIL = (
        "hil",
        (
            "hil_conversational_resolve",
            "hil_conversational_resolve_batch",
            "hil_intent_judge",
            "hil_tool_classification",
        ),
    )
    ONBOARDING = (
        "onboarding",
        (
            "onboarding_first_question",
            "onboarding_inbox_triage",
            "onboarding_social_profile",
            "onboarding_writing_style",
            "onboarding_writing_style_example",
        ),
    )
    PROFILE = "profile", ("holo_card",)
    INTEGRATION_INFERENCE = (
        "integration_inference",
        (
            "integration_category",
            "integration_content",
        ),
    )
    WORKFLOW_GENERATION = "workflow_generation", ("workflow_generation", "workflow_prompt")
    FILE_EXTRACTION = "file_extraction", ("file_image_summary", "file_text_summary")
    FOLLOW_UPS = "follow_ups", ("follow_up_actions",)
    RESEARCH = "research", ("research_queries",)
    TODO_MAINTENANCE = "todo_maintenance", ("todo_health_check",)
    MODERATION = "moderation", ("profanity",)
    BROWSER = "browser", ("browser_task",)
    TITLE_GENERATION = "title_generation", ("chatbot",)
    # A caller whose label no member claims.
    UNATTRIBUTED = "unattributed"


_FEATURE_BY_LABEL: dict[str, AIFeature] = {
    label: feature for feature in AIFeature for label in feature.labels
}


#: Event and person properties: counts, enums, durations, booleans and ids.
#: JSON-able values, never PII — see the analytics section of the root CLAUDE.md.
AnalyticsProperties: TypeAlias = Mapping[str, object]


def _get_posthog_client() -> Posthog | None:
    """Get the PostHog client from providers."""
    client: Posthog | None = providers.get(POSTHOG_PROVIDER_KEY)
    return client


def identify_user(user_id: UserId, properties: AnalyticsProperties | None = None) -> None:
    """Set person properties on user_id, stamping first_seen once."""
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping identify")
        return

    try:
        client.set(distinct_id=user_id.distinct_id, properties={**(properties or {})})
        client.set_once(
            distinct_id=user_id.distinct_id,
            properties={"first_seen": datetime.now(UTC).isoformat()},
        )
    except Exception as e:
        log.error(
            "Failed to identify user in PostHog",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id.distinct_id,
        )


def capture(distinct_id: AnalyticsId, event: ServerEvent, dedupe_key: str | None = None) -> None:
    """Capture a server-owned catalog event; the only way the API emits one.

    dedupe_key makes it idempotent: derive it from what happened (a run id, a
    user+phase) and PostHog collapses repeats. Required for anything emitted
    from a retryable worker task, or an ARQ retry double-counts the milestone.
    """
    check_capture(distinct_id, event, Surface.SERVER)
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping event", event=event.event)
        return

    log.set(analytics={"user_id": distinct_id.distinct_id, "event": event.event})
    try:
        # A stable uuid is PostHog's dedupe key; uuid5 so the same inputs give
        # the same id on any worker and any retry.
        client.capture(
            event=event.event,
            distinct_id=distinct_id.distinct_id,
            properties=posthog_properties(event),
            **(
                {
                    "uuid": str(
                        uuid5(
                            NAMESPACE_URL, f"{event.event}:{distinct_id.distinct_id}:{dedupe_key}"
                        )
                    )
                }
                if dedupe_key
                else {}
            ),
        )
    except Exception as e:
        log.error(
            "Failed to capture event in PostHog",
            event=event.event,
            error=str(e),
            error_type=type(e).__name__,
            user_id=distinct_id.distinct_id,
        )


@dataclass
class AgentRunOutcome:
    """A run's terminal outcome and executor timings, set by a body that reports instead of raising."""

    failure_reason: str | None = None
    paused: bool = False
    queued: bool | None = None
    queue_wait_ms: float | None = None
    executor_ttft_ms: float | None = None
    executor_active_ms: float | None = None


@contextmanager
def agent_run_lifecycle(
    user_id: str | None,
    run: AgentRunStarted,
    dedupe_key: str | None = None,
) -> Iterator[AgentRunOutcome]:
    """Emit run_started on entry, then exactly one of run_completed or run_failed.

    A raised exception fails the run with its type as reason, a cancellation with
    "cancelled"; a body that handles its own failure sets failure_reason, and a
    paused run emits no terminal event.
    dedupe_key keys the terminal event. No user id, no events.
    """
    outcome = AgentRunOutcome()
    if not user_id:
        yield outcome
        return
    distinct_id = UserId(user_id)
    capture(distinct_id, run)
    try:
        yield outcome
    except asyncio.CancelledError:
        outcome.failure_reason = AGENT_RUN_CANCELLED_REASON
        _capture_run_terminal(distinct_id, run, outcome, dedupe_key)
        raise
    except Exception as exc:
        outcome.failure_reason = type(exc).__name__
        _capture_run_terminal(distinct_id, run, outcome, dedupe_key)
        raise
    if not outcome.paused:
        _capture_run_terminal(distinct_id, run, outcome, dedupe_key)


def _capture_run_terminal(
    user_id: UserId,
    run: AgentRunStarted,
    outcome: AgentRunOutcome,
    dedupe_key: str | None,
) -> None:
    """Emit run_failed with its reason when the outcome failed, else run_completed."""
    terminal = {
        **run.model_dump(),
        "queued": outcome.queued,
        "queue_wait_ms": outcome.queue_wait_ms,
        "executor_ttft_ms": outcome.executor_ttft_ms,
        "executor_active_ms": outcome.executor_active_ms,
    }
    event: AgentRunCompleted | AgentRunFailed = (
        AgentRunCompleted.model_validate(terminal)
        if outcome.failure_reason is None
        else AgentRunFailed.model_validate({**terminal, "reason": outcome.failure_reason})
    )
    capture(user_id, event, dedupe_key=dedupe_key)


def track_signup(
    user_id: UserId,
    email: str,
    name: str | None = None,
    signup_method: str = LOGIN_METHOD_WORKOS,
) -> None:
    """Set the new user's person properties and capture user:signed_up."""
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "signup_method": signup_method,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    capture(user_id, UserSignedUp(signup_method=signup_method))


def track_login(
    user_id: UserId,
    email: str,
    name: str | None = None,
    login_method: str = LOGIN_METHOD_WORKOS,
) -> None:
    """Refresh the user's person properties and capture user:logged_in."""
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "last_login_method": login_method,
            "last_login_at": datetime.now(UTC).isoformat(),
        },
    )
    capture(user_id, UserLoggedIn(login_method=login_method))


SubscriptionLifecycleEvent: TypeAlias = (
    SubscriptionActivated | SubscriptionRenewed | SubscriptionCancelled | SubscriptionExpired
)


def track_subscription_event(user_id: UserId, event: SubscriptionLifecycleEvent) -> None:
    """Capture a subscription transition and mirror it onto the user's person properties.

    Person properties (not an event) let any chart segment pro vs free;
    is_subscribed is the canonical flag, and a cancellation keeps access until expiry.
    """
    log.set(
        subscription={
            "user_id": user_id.distinct_id,
            "event_type": event.event,
            "plan_name": event.plan_name if isinstance(event, SubscriptionActivated) else None,
            "subscription_id": event.subscription_id,
        }
    )
    capture(user_id, event)

    match event:
        case SubscriptionActivated():
            metadata: dict[str, object] = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
                "subscription_activated_at": datetime.now(UTC).isoformat(),
            }
        case SubscriptionRenewed():
            metadata = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
            }
        case SubscriptionCancelled():
            metadata = {"subscription_status": SubscriptionStatus.CANCELLED}
        case SubscriptionExpired():
            metadata = {
                "plan": PlanType.FREE,
                "is_subscribed": False,
                "subscription_status": SubscriptionStatus.EXPIRED,
            }

    client = _get_posthog_client()
    if client is None:
        return
    try:
        client.set(distinct_id=user_id.distinct_id, properties=metadata)
    except Exception as e:
        log.error(
            "Failed to update user subscription properties",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id.distinct_id,
        )
