"""Deliver a proactively-produced result into the user's linked messaging platforms.

A result GAIA produces with no user watching — a finished workflow run, a fired
reminder — is pushed by deliver_result_to_platforms into the user's real
Telegram/WhatsApp/Discord/Slack chats as natural GAIA messages (GAIA's voice, no
notification chrome) so the thread can be continued there, AND recorded into that
conversation's langgraph thread so a later turn remembers it (both done by
post_to_platform_chat). This is deliberately separate from the in-app badge
each producer also raises: the badge is a web heads-up, this is the actual
conversational delivery, and they target different surfaces.

Everything here is best-effort: a single platform failing never blocks the others
or propagates to the caller — the result is already persisted to the conversation.
"""

from app.agents.core.background.platform_chat import post_to_platform_chat
from app.constants.log_tags import LogTag
from app.constants.notifications import ProactiveMessageClass
from app.models.chat_models import ConversationSource
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.delivery.chat_channel import (
    ChatChannel,
    InApp,
    ProactiveTarget,
    proactive_destination,
    resolve_proactive_target,
)
from app.services.outbound_delivery import OutboundResult
from shared.py.analytics import UserId
from shared.py.analytics.catalog.workflows import WorkflowResultDelivered
from shared.py.wide_events import log


async def deliver_result_to_platforms(
    *,
    user: AuthenticatedUser,
    notification_text: str,
    origin: str,
    message_class: ProactiveMessageClass,
    target: ProactiveTarget,
    exclude_source: ConversationSource | None = None,
) -> ConversationSource | None:
    """Deliver a proactive result to the chat app the caller's resolved target names.

    An in-app target sends nothing here, and exclude_source skips a platform
    that already received the result. Best-effort: returns the platform that
    has it (posted, or held for the end of the user's quiet hours), or None.
    """
    if (
        not notification_text.strip()
        or not isinstance(target, ChatChannel)
        or target.source == exclude_source
    ):
        return None

    try:
        result = await post_to_platform_chat(
            user=user,
            channel=target,
            text=notification_text,
            origin=f"result of {origin}",
            message_class=message_class,
        )
    except Exception as e:  # best-effort: the result is already in its own conversation
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=target.source.value,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
    accepted = result in (OutboundResult.PUBLISHED, OutboundResult.DEFERRED)
    return target.source if accepted else None


async def deliver_workflow_result(
    *,
    user: AuthenticatedUser,
    workflow_id: str | None,
    notification_text: str,
    origin: str,
    message_class: ProactiveMessageClass,
) -> None:
    """Send a workflow run's result to the user's one proactive place and record where it went.

    Both workflow paths (an agent run and a replayed playbook) deliver here. A
    failed lookup costs only the chat-app copy: the result is already saved.
    """
    try:
        target = await resolve_proactive_target(user.user_id)
    except Exception as e:  # best-effort: the result is already saved
        log.error(
            f"{LogTag.AGENT} workflow result: chat app lookup failed, not sent to the chat app",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        capture(
            UserId(user.user_id),
            WorkflowResultDelivered(workflow_id=workflow_id, outcome="lookup_failed"),
        )
        return
    platform = await deliver_result_to_platforms(
        user=user,
        notification_text=notification_text,
        origin=origin,
        message_class=message_class,
        target=target,
    )
    # In the GAIA app the saved result is the delivery; a chat app must have taken the send.
    delivered = isinstance(target, InApp) or platform is not None
    capture(
        UserId(user.user_id),
        WorkflowResultDelivered(
            workflow_id=workflow_id,
            outcome="delivered" if delivered else "undelivered",
            platform=platform.value if platform else None,
            **proactive_destination(target),
        ),
    )
