"""Server-side PostHog capture: catalog events only, attributed to an AnalyticsId."""

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeAlias
from uuid import NAMESPACE_URL, uuid5

from posthog import Posthog

from app.constants.analytics import ANALYTICS_ONCE_KEY_PREFIX, POSTHOG_PROVIDER_KEY
from app.core.lazy_loader import providers
from app.db.redis import redis_cache
from shared.py.analytics import AnalyticsId, UserId, check_capture, posthog_properties
from shared.py.analytics.catalog.auth import UserLoggedIn, UserSignedUp
from shared.py.analytics.catalog.base import ServerEvent, Surface
from shared.py.analytics.catalog.billing import (
    SubscriptionActivated,
    SubscriptionCancelled,
    SubscriptionExpired,
    SubscriptionLapsed,
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
    MODERATION = "moderation", ("profanity",)
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


async def capture_once(
    distinct_id: AnalyticsId, event: ServerEvent, *, scope: str, window_seconds: int
) -> None:
    """Capture event at most once per window for this person and scope; a repeat inside it is dropped."""
    key = f"{ANALYTICS_ONCE_KEY_PREFIX}{event.event}:{distinct_id.distinct_id}:{scope}"
    if await redis_cache.set_if_absent(key, "1", ttl=window_seconds):
        capture(distinct_id, event, dedupe_key=scope)


def track_signup(
    user_id: UserId,
    email: str,
    name: str | None = None,
    *,
    signup_method: str | None,
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
    *,
    login_method: str | None,
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
    SubscriptionActivated
    | SubscriptionRenewed
    | SubscriptionCancelled
    | SubscriptionExpired
    | SubscriptionLapsed
)


def track_subscription_event(user_id: UserId, event: SubscriptionLifecycleEvent) -> None:
    """Capture a subscription transition and name it on the wide event for billing support."""
    log.set(
        subscription={
            "user_id": user_id.distinct_id,
            "event_type": event.event,
            "plan_name": event.plan_name if isinstance(event, SubscriptionActivated) else None,
            "subscription_id": event.subscription_id,
        }
    )
    capture(user_id, event)
