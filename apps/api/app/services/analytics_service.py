"""Type-safe server-side PostHog event tracking with consistent naming conventions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from posthog import Posthog

from app.constants.auth import LOGIN_METHOD_WORKOS
from app.core.lazy_loader import providers
from app.models.payment_models import PlanType, SubscriptionStatus
from shared.py.wide_events import log


# Event name constants for consistent tracking
class AnalyticsEvents(StrEnum):
    """Backend-relevant analytics event names (matching frontend conventions)."""

    # Auth
    USER_SIGNED_UP = "user:signed_up"
    USER_LOGGED_IN = "user:logged_in"
    USER_LOGGED_OUT = "user:logged_out"

    # Core product actions
    CHAT_MESSAGE_SUBMITTED = "chat:message_submitted"
    # The other half of submitted: a turn stopped at a gate, carrying why.
    # Without it a refusal is a MISSING event, and missing is
    # indistinguishable from a user who never typed.
    CHAT_MESSAGE_REFUSED = "chat:message_refused"
    WORKFLOW_CREATED = "workflow:created"
    WORKFLOW_EXECUTED = "workflow:executed"
    WORKFLOW_ACTIVATED = "workflow:activated"
    WORKFLOW_PUBLISHED = "workflow:published"
    WORKFLOW_DELETED = "workflow:deleted"
    WORKFLOW_UNPUBLISHED = "workflow:unpublished"
    WORKFLOW_DEACTIVATED = "workflow:deactivated"
    WORKFLOW_UPDATED = "workflow:updated"
    WORKFLOW_STEPS_REGENERATED = "workflow:steps_regenerated"
    PAYMENT_CHECKOUT_STARTED = "payment:checkout_started"
    SUBSCRIPTION_CANCELLATION_REQUESTED = "subscription:cancellation_requested"
    FEEDBACK_MESSAGE_SUBMITTED = "feedback:message_submitted"
    SESSION_ARTIFACT_PINNED = "session:artifact_pinned"
    PROFILE_UPDATED = "profile:updated"
    # Activation checklist hidden by the user — carries how many steps were
    # done at that moment, never which.
    FIRST_STEPS_COLLAPSED = "first_steps:collapsed"

    # Lifecycle email
    NURTURE_EMAIL_SENT = "nurture:email_sent"

    # Day-by-day activation sequence. The three together are the funnel: how
    # many days went out, why the rest did not, and how often anyone answered.

    # Settings. Which platform GAIA texts first — the names of the platforms
    # and how many are ordered, never anything the user wrote.
    SETTINGS_CHAT_CHANNEL_PRIORITY_UPDATED = "settings:chat_channel_priority_updated"

    # Payments (used by payment webhook processing)
    PAYMENT_SUCCEEDED = "payment:succeeded"
    PAYMENT_FAILED = "payment:failed"

    # Subscription lifecycle (used by payment webhook processing)
    SUBSCRIPTION_ACTIVATED = "subscription:activated"
    SUBSCRIPTION_RENEWED = "subscription:renewed"
    SUBSCRIPTION_CANCELLED = "subscription:cancelled"
    SUBSCRIPTION_EXPIRED = "subscription:expired"
    RATE_LIMIT_HIT = "rate_limit_hit"
    # A non-PRO caller was turned away from a paid-only surface with a 402.
    # Carries which surface blocked them, never what they were trying to do.
    PAYWALL_BLOCKED = "paywall:blocked"

    # Conversations
    CONVERSATION_CREATED = "chat:conversation_created"
    CONVERSATION_RENAMED = "chat:conversation_renamed"
    CONVERSATION_STARRED = "chat:conversation_starred"
    CONVERSATION_DELETED = "chat:conversation_deleted"
    # Terminal turn event. Server-side latency props: ttft_ms (first response text,
    # absent when none streamed), e2e_ack_ms, e2e_full_ms, delegated, queued.
    # Executor-leg timings ride on agent:run_completed, HIL waits on the wide event.
    CHAT_MESSAGE_COMPLETED = "chat:message_completed"
    CHAT_MESSAGE_CANCELLED = "chat:message_cancelled"
    CHAT_MESSAGE_PINNED = "chat:message_pinned"
    CHAT_MESSAGE_UNPINNED = "chat:message_unpinned"
    # A comms reply scored dirty against the AI-ism detectors and was
    # rewritten before delivery. Counts only — never the text.
    CHAT_STYLE_GUARD_REGENERATED = "chat:style_guard_regenerated"

    # Files
    FILE_UPLOADED = "chat:file_uploaded"
    FILE_UPDATED = "chat:file_updated"
    FILE_DELETED = "chat:file_deleted"

    # Images
    IMAGE_GENERATED = "image:generated"
    IMAGE_DESCRIBED = "image:described"

    # Todos
    TODO_CREATED = "todos:created"
    TODO_UPDATED = "todos:updated"
    # Toggled, not completed: the same event fires for un-completing, and the
    # value is what the frontend's TODOS_TOGGLED already emits.
    TODO_TOGGLED = "todos:toggled"
    TODO_DELETED = "todos:deleted"
    # Trigger subscriptions. `todos:` (plural) matches the events above — the
    # domain half of the name is the surface, not the individual record.
    TODO_SUBSCRIPTION_REGISTERED = "todos:subscription_registered"
    TODO_SUBSCRIPTION_FAILED = "todos:subscription_failed"
    TODO_TRIGGER_FIRED = "todos:trigger_fired"

    PROJECT_CREATED = "projects:created"
    PROJECT_UPDATED = "projects:updated"
    PROJECT_DELETED = "projects:deleted"

    CALENDAR_EVENT_CREATED = "calendar:event_created"
    CALENDAR_EVENT_UPDATED = "calendar:event_updated"
    CALENDAR_EVENT_DELETED = "calendar:event_deleted"
    CALENDAR_PREFERENCES_UPDATED = "calendar:preferences_updated"

    EMAIL_SENT = "email:sent"
    EMAIL_REPLIED = "email:replied"
    # NOT the same as the web's email:compose_opened, which is the user opening
    # the modal. This fires when the ASSISTANT finishes composing a draft — a
    # different action that happened to be wearing the same name.
    EMAIL_COMPOSED = "email:draft_composed"
    EMAIL_MARKED_READ = "email:marked_read"
    EMAIL_MARKED_UNREAD = "email:marked_unread"
    EMAIL_STARRED = "email:starred"
    EMAIL_UNSTARRED = "email:unstarred"
    EMAIL_TRASHED = "email:trashed"
    EMAIL_UNTRASHED = "email:untrashed"
    EMAIL_ARCHIVED = "email:archived"
    EMAIL_MOVED_TO_INBOX = "email:moved_to_inbox"
    EMAIL_LABEL_CREATED = "email:label_created"
    EMAIL_LABEL_UPDATED = "email:label_updated"
    EMAIL_LABEL_DELETED = "email:label_deleted"
    EMAIL_LABEL_APPLIED = "email:label_applied"
    EMAIL_LABEL_REMOVED = "email:label_removed"
    EMAIL_DRAFT_CREATED = "email:draft_created"
    EMAIL_DRAFT_UPDATED = "email:draft_updated"
    EMAIL_DRAFT_DELETED = "email:draft_deleted"

    # Memory
    MEMORY_CREATED = "memory:created"
    MEMORY_UPDATED = "memory:updated"
    MEMORY_CLEARED = "memory:cleared"
    MEMORY_ITEM_DELETED = "memory:item_deleted"
    MEMORY_DOCUMENT_UPDATED = "memory:document_updated"

    # Notes
    NOTE_CREATED = "notes:created"
    NOTE_UPDATED = "notes:updated"
    NOTE_DELETED = "notes:deleted"

    # Reminders
    REMINDER_CREATED = "reminder:created"
    REMINDER_UPDATED = "reminder:updated"
    REMINDER_PAUSED = "reminder:paused"
    REMINDER_RESUMED = "reminder:resumed"
    REMINDER_COMPLETED = "reminder:completed"
    REMINDER_DELETED = "reminder:deleted"

    # Bot-originated actions with no web equivalent
    BOT_SESSION_RESET = "bot:session_reset"
    BOT_AUDIO_TRANSCRIBED = "bot:audio_transcribed"

    # Search
    SEARCH_PERFORMED = "search:performed"

    # Device bridge
    DEVICE_SELF_PAIRED = "device:self_paired"
    DEVICE_APPROVED = "device:approved"
    DEVICE_REVOKED = "device:revoked"

    NOTIFICATION_PREFERENCE_UPDATED = "settings:notifications_toggled"
    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_BULK_ACTION = "notification:bulk_action"
    NOTIFICATION_ACTION_EXECUTED = "notification:action_executed"
    NOTIFICATION_UNSUBSCRIBED = "notification:unsubscribed"

    # Onboarding
    # Named for its "phase" payload — the web's own onboarding:step_completed
    # carries step_number/step_name, a different shape unqueryable under one name.
    ONBOARDING_PHASE_COMPLETED = "onboarding:phase_completed"
    ONBOARDING_COMPLETED = "onboarding:completed"
    ONBOARDING_INTEGRATIONS_SUBMITTED = "onboarding:integrations_submitted"
    ONBOARDING_RESET = "onboarding:reset"
    ONBOARDING_WRITING_STYLE_SAVED = "onboarding:writing_style_saved"
    ONBOARDING_WRITING_STYLE_EXAMPLE_REGENERATED = "onboarding:writing_style_example_regenerated"
    ONBOARDING_SOCIAL_PROFILES_CONFIRMED = "onboarding:social_profiles_confirmed"

    # Integrations
    INTEGRATION_CONNECTED = "integration:connected"
    INTEGRATION_CONNECT_INITIATED = "integration:connect_initiated"
    INTEGRATION_DISCONNECTED = "integration:disconnected"
    INTEGRATION_INSTRUCTIONS_UPDATED = "integration:instructions_updated"
    INTEGRATION_CUSTOM_UPDATED = "integration:custom_updated"
    INTEGRATION_CUSTOM_DELETED = "integration:custom_deleted"
    INTEGRATION_CUSTOM_PUBLISHED = "integration:custom_published"
    INTEGRATION_CUSTOM_UNPUBLISHED = "integration:custom_unpublished"
    MCP_CONNECTION_TESTED = "mcp:connection_tested"

    # Skills
    SKILL_INSTALLED = "skill:installed"
    SKILL_UPDATED = "skill:updated"
    SKILL_ENABLED = "skill:enabled"
    SKILL_DISABLED = "skill:disabled"
    SKILL_UNINSTALLED = "skill:uninstalled"

    # Support
    SUPPORT_TICKET_SUBMITTED = "support:form_submitted"

    # Settings / profile
    SETTINGS_PREFERENCES_CHANGED = "settings:preferences_changed"

    # Account-center mutations made through the agent's account tools
    ACCOUNT_SETTING_CHANGED = "account:setting_changed"
    ACCOUNT_PLATFORM_DISCONNECTED = "account:platform_disconnected"

    # Human-in-the-loop approvals
    APPROVAL_DECIDED = "approval:decided"

    # Worker / agent lifecycle. AGENT_RUN_COMPLETED/FAILED carry executor
    # timing props when measured: queue_wait_ms, executor_ttft_ms,
    # executor_active_ms, queued. Absent on runs dispatched before the stamp.
    AGENT_RUN_STARTED = "agent:run_started"
    AGENT_RUN_COMPLETED = "agent:run_completed"
    AGENT_RUN_FAILED = "agent:run_failed"
    TOOL_USED = "tool:used"

    USAGE_QUERIED = "usage:queried"


def _get_posthog_client() -> Posthog | None:
    """Get the PostHog client from providers."""
    client: Posthog | None = providers.get("posthog")
    return client


def identify_user(
    user_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Identify a user in PostHog with their properties.

    Args:
        user_id: Stable PostHog distinct_id from the application's user record.
        properties: Person properties to set
    """
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping identify")
        return

    try:
        user_properties = {**(properties or {})}
        client.set(distinct_id=user_id, properties=user_properties)
        client.set_once(
            distinct_id=user_id,
            properties={"first_seen": datetime.now(UTC).isoformat()},
        )
    except Exception as e:
        log.error(
            "Failed to identify user in PostHog",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def capture_context_event(
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Capture an event attributed by the active PostHog request context."""
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping event", event=event)
        return

    try:
        client.capture(
            event=event,
            properties={
                **(properties or {}),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as e:
        log.error(
            "Failed to capture event in PostHog",
            event=event,
            error=str(e),
            error_type=type(e).__name__,
        )


def capture_event(
    user_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Capture an analytics event in PostHog, attributed to user_id.

    dedupe_key makes it idempotent: derive it from what happened (a run id, a
    user+phase) and PostHog collapses repeats. Required for anything emitted
    from a retryable worker task, or an ARQ retry double-counts the milestone.
    """
    client = _get_posthog_client()
    if client is None:
        log.debug("PostHog client not available, skipping event", event=event)
        return

    log.set(analytics={"user_id": user_id, "event": event})
    try:
        event_properties = {
            **(properties or {}),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        # A stable uuid is PostHog's dedupe key — the same one twice is stored
        # once. uuid5 so the same inputs always produce the same id, on any
        # worker, on any retry.
        client.capture(
            event=event,
            distinct_id=user_id,
            properties=event_properties,
            **(
                {"uuid": str(uuid5(NAMESPACE_URL, f"{event}:{user_id}:{dedupe_key}"))}
                if dedupe_key
                else {}
            ),
        )
    except Exception as e:
        log.error(
            "Failed to capture event in PostHog",
            event=event,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def track_signup(
    user_id: str,
    email: str,
    name: str | None = None,
    signup_method: str = LOGIN_METHOD_WORKOS,
    properties: dict[str, Any] | None = None,
) -> None:
    """Track a user signup event.

    signup_method is one of "workos", "google", "email".
    """
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "signup_method": signup_method,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )

    capture_event(
        user_id,
        AnalyticsEvents.USER_SIGNED_UP,
        {
            "signup_method": signup_method,
            **(properties or {}),
        },
    )


def track_login(
    user_id: str,
    email: str,
    name: str | None = None,
    login_method: str = LOGIN_METHOD_WORKOS,
    properties: dict[str, Any] | None = None,
) -> None:
    """Track a user login event.

    login_method is one of "workos", "google", "email".
    """
    identify_user(
        user_id,
        {
            "email": email,
            "name": name,
            "last_login_method": login_method,
            "last_login_at": datetime.now(UTC).isoformat(),
        },
    )

    capture_event(
        user_id,
        AnalyticsEvents.USER_LOGGED_IN,
        {
            "login_method": login_method,
            **(properties or {}),
        },
    )


def track_logout(
    user_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Track a user logout event.

    Args:
        user_id: User's unique identifier
        properties: Additional properties
    """
    capture_event(
        user_id,
        AnalyticsEvents.USER_LOGGED_OUT,
        properties,
    )


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    """The priced plan a subscription event refers to.

    Fields a given webhook doesn't carry stay None and are dropped from the event.
    """

    name: str | None = None
    amount: float | None = None
    currency: str | None = None


def track_subscription_event(
    user_id: str,
    event_type: AnalyticsEvents,
    subscription_id: str | None = None,
    plan: SubscriptionPlan | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """Track subscription-related events."""
    plan = plan or SubscriptionPlan()
    log.set(
        subscription={
            "user_id": user_id,
            "event_type": event_type,
            "plan_name": plan.name,
            "subscription_id": subscription_id,
        }
    )
    event_properties = {
        "subscription_id": subscription_id,
        "plan_name": plan.name,
        "amount": plan.amount,
        "currency": plan.currency,
        **(properties or {}),
    }
    # Remove None values
    event_properties = {k: v for k, v in event_properties.items() if v is not None}

    capture_event(user_id, event_type, event_properties)

    # Update the user's subscription metadata (person properties, not an emitted
    # event) so any chart can segment pro vs free. `is_subscribed` is the
    # canonical flag; a cancellation keeps access until the plan actually expires.
    match event_type:
        case AnalyticsEvents.SUBSCRIPTION_ACTIVATED:
            metadata = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
                "subscription_activated_at": datetime.now(UTC).isoformat(),
            }
        case AnalyticsEvents.SUBSCRIPTION_RENEWED:
            metadata = {
                "plan": PlanType.PRO,
                "is_subscribed": True,
                "subscription_status": SubscriptionStatus.ACTIVE,
            }
        case AnalyticsEvents.SUBSCRIPTION_CANCELLED:
            metadata = {"subscription_status": SubscriptionStatus.CANCELLED}
        case AnalyticsEvents.SUBSCRIPTION_EXPIRED:
            metadata = {
                "plan": PlanType.FREE,
                "is_subscribed": False,
                "subscription_status": SubscriptionStatus.EXPIRED,
            }
        case _:
            # Non-subscription or no-metadata events (e.g. FAILED) are ignored.
            return

    client = _get_posthog_client()
    if client is None:
        return
    try:
        client.set(distinct_id=user_id, properties=metadata)
    except Exception as e:
        log.error(
            "Failed to update user subscription properties",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )


def track_payment_event(
    user_id: str,
    event_type: str,
    payment_id: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """Track payment-related events."""
    event_properties = {
        "payment_id": payment_id,
        "amount": amount,
        "currency": currency,
        **(properties or {}),
    }
    # Remove None values
    event_properties = {k: v for k, v in event_properties.items() if v is not None}

    capture_event(user_id, event_type, event_properties)
