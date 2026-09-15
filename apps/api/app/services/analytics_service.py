"""
Analytics service for server-side PostHog event tracking.
Provides type-safe event tracking with consistent naming conventions.
"""

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

    # Lifecycle email
    NURTURE_EMAIL_SENT = "nurture:email_sent"

    # Payments (used by payment webhook processing)
    PAYMENT_SUCCEEDED = "payment:succeeded"
    PAYMENT_FAILED = "payment:failed"

    # Subscription lifecycle (used by payment webhook processing)
    SUBSCRIPTION_ACTIVATED = "subscription:activated"
    SUBSCRIPTION_RENEWED = "subscription:renewed"
    SUBSCRIPTION_CANCELLED = "subscription:cancelled"
    SUBSCRIPTION_EXPIRED = "subscription:expired"
    RATE_LIMIT_HIT = "rate_limit_hit"

    # Conversations
    CONVERSATION_CREATED = "chat:conversation_created"
    CONVERSATION_RENAMED = "chat:conversation_renamed"
    CONVERSATION_STARRED = "chat:conversation_starred"
    CONVERSATION_DELETED = "chat:conversation_deleted"
    # Terminal turn event. Latency props (all ms, measured server-side):
    # ttft_ms (first response text; absent when no text streamed), e2e_ack_ms
    # (comms ack), e2e_full_ms (stream DONE after executor wait), delegated,
    # queued. Executor-leg timings (queue_wait_ms, executor_ttft_ms,
    # executor_active_ms) ride on agent:run_completed, and HIL waits on the
    # wide event — not here.
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
    ONBOARDING_STEP_COMPLETED = "onboarding:step_completed"
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

    # Background spend only; agent-graph calls are covered by $ai_generation.
    AI_LLM_CALL_COMPLETED = "ai:llm_call_completed"


class AIFeature(StrEnum):
    """The product capability a metered model call was made on behalf of.

    Coarser than the call's ``label`` on purpose: many one-shots roll up to one
    member while keeping their own labels. Which integration ran is ``agent_name``.
    """

    CHAT = "chat"
    WORKFLOW = "workflow"
    INTEGRATION = "integration"
    MEMORY = "memory"
    VISION = "vision"
    MAIL = "mail"
    HIL = "hil"
    ONBOARDING = "onboarding"
    PROFILE = "profile"
    INTEGRATION_INFERENCE = "integration_inference"
    WORKFLOW_GENERATION = "workflow_generation"
    FILE_EXTRACTION = "file_extraction"
    FOLLOW_UPS = "follow_ups"
    RESEARCH = "research"
    MODERATION = "moderation"
    TITLE_GENERATION = "title_generation"
    # A caller whose label has no LABEL_FEATURES entry.
    UNATTRIBUTED = "unattributed"


#: Which capability each auxiliary ``label`` belongs to, keyed on the ``label``
#: every one-shot already passes for its log line. Kept beside ``AIFeature`` so
#: the two cannot drift; ``test_every_feature_is_reachable`` enforces it.
LABEL_FEATURES: dict[str, AIFeature] = {
    "chatbot": AIFeature.TITLE_GENERATION,
    "file_image_summary": AIFeature.FILE_EXTRACTION,
    "file_text_summary": AIFeature.FILE_EXTRACTION,
    "follow_up_actions": AIFeature.FOLLOW_UPS,
    "hil_conversational_resolve": AIFeature.HIL,
    "hil_conversational_resolve_batch": AIFeature.HIL,
    "hil_intent_judge": AIFeature.HIL,
    "hil_tool_classification": AIFeature.HIL,
    "holo_card": AIFeature.PROFILE,
    "image_to_text": AIFeature.VISION,
    "integration_category": AIFeature.INTEGRATION_INFERENCE,
    "integration_content": AIFeature.INTEGRATION_INFERENCE,
    "mail_compose": AIFeature.MAIL,
    "onboarding_clarify": AIFeature.ONBOARDING,
    "onboarding_first_message": AIFeature.ONBOARDING,
    "onboarding_focus_todos": AIFeature.ONBOARDING,
    "onboarding_inbox_triage": AIFeature.ONBOARDING,
    "onboarding_social_profile": AIFeature.ONBOARDING,
    "onboarding_todos_from_emails": AIFeature.ONBOARDING,
    "onboarding_workflow_suggestions": AIFeature.ONBOARDING,
    "onboarding_writing_style": AIFeature.ONBOARDING,
    "onboarding_writing_style_example": AIFeature.ONBOARDING,
    "playbook_ask_fill": AIFeature.WORKFLOW,
    "playbook_narration": AIFeature.WORKFLOW,
    "profanity": AIFeature.MODERATION,
    "profile_extraction": AIFeature.MEMORY,
    "research_queries": AIFeature.RESEARCH,
    "tool_media_vision": AIFeature.VISION,
    "vision_fallback": AIFeature.VISION,
    "workflow_generation": AIFeature.WORKFLOW_GENERATION,
    "workflow_prompt": AIFeature.WORKFLOW_GENERATION,
}


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
    """Capture an analytics event in PostHog, attributed to ``user_id``.

    ``dedupe_key`` makes the capture idempotent: pass a value derived from the
    thing that happened (a run id, a user plus a phase) and PostHog collapses
    repeats of it into one event. Anything emitted from a retryable worker task
    needs one — an ARQ retry re-runs the whole body, and without a key the
    second pass simply counts the milestone twice.
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
    """
    Track a user signup event.

    Args:
        user_id: User's unique identifier
        email: User's email address
        name: User's display name
        signup_method: How the user signed up (workos, google, email)
        properties: Additional properties
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
    """
    Track a user login event.

    Args:
        user_id: User's unique identifier
        email: User's email address
        name: User's display name
        login_method: How the user logged in (workos, google, email)
        properties: Additional properties
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


def track_subscription_event(
    user_id: str,
    event_type: AnalyticsEvents,
    subscription_id: str | None = None,
    plan_name: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Track subscription-related events.

    Args:
        user_id: User's unique identifier
        event_type: Type of subscription event
        subscription_id: Subscription identifier
        plan_name: Name of the plan
        amount: Subscription amount
        currency: Currency code
        properties: Additional properties
    """
    log.set(
        subscription={
            "user_id": user_id,
            "event_type": event_type,
            "plan_name": plan_name,
            "subscription_id": subscription_id,
        }
    )
    event_properties = {
        "subscription_id": subscription_id,
        "plan_name": plan_name,
        "amount": amount,
        "currency": currency,
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
    """
    Track payment-related events.

    Args:
        user_id: User's unique identifier
        event_type: Type of payment event
        payment_id: Payment identifier
        amount: Payment amount
        currency: Currency code
        properties: Additional properties
    """
    event_properties = {
        "payment_id": payment_id,
        "amount": amount,
        "currency": currency,
        **(properties or {}),
    }
    # Remove None values
    event_properties = {k: v for k, v in event_properties.items() if v is not None}

    capture_event(user_id, event_type, event_properties)
