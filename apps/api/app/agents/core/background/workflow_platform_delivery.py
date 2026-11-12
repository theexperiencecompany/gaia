"""Deliver a proactively-produced result into the user's linked messaging platforms.

A result GAIA produces with no user watching — a finished workflow run, a fired
reminder — is pushed by :func:deliver_result_to_platforms into the user's real
Telegram/WhatsApp/Discord/Slack chats as natural GAIA messages (GAIA's voice, no
notification chrome) so the thread can be continued there, AND logged in that
conversation as a Notice, so its next reply knows what was already sent. This is deliberately
separate from the in-app badge each producer also raises: the badge is a web
heads-up, this is the actual conversational delivery, and they target different
surfaces.

Everything here is best-effort: a single platform failing never blocks the others
or propagates to the caller — the result is already persisted to the conversation.
"""

from uuid import uuid4

from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.bot_service import BotService
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.delivery.chat_channel import (
    ChatChannel,
    InApp,
    ProactiveTarget,
    proactive_destination,
    resolve_proactive_target,
)
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.utils.message_breaks import split_message_bubbles
from shared.py.analytics import UserId
from shared.py.analytics.catalog.workflows import WorkflowResultDelivered
from shared.py.wide_events import log


async def deliver_result_to_platforms(
    *,
    user: AuthenticatedUser,
    user_id: str,
    notification_text: str,
    origin: str,
    target: ProactiveTarget,
    exclude_source: ConversationSource | None = None,
) -> ConversationSource | None:
    """Deliver a proactive result to the chat app the caller's resolved target names.

    The caller resolves the target once, so every send of one result follows the
    same rule; an in-app target sends nothing here, and exclude_source skips a
    platform that already received the result. Best-effort: returns the
    platform that got it, or None when nothing was sent.
    """
    if (
        not notification_text.strip()
        or not isinstance(target, ChatChannel)
        or target.source == exclude_source
    ):
        return None

    return await _post_workflow_message(
        user=user,
        user_id=user_id,
        channel=target,
        response=notification_text,
        origin=origin,
    )


async def deliver_workflow_result(
    *, user: AuthenticatedUser, workflow_id: str | None, notification_text: str, origin: str
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
        user_id=user.user_id,
        notification_text=notification_text,
        origin=origin,
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


async def _post_workflow_message(
    *,
    user: AuthenticatedUser,
    user_id: str,
    channel: ChatChannel,
    response: str,
    origin: str,
) -> ConversationSource | None:
    """Persist the result into the platform's session conversation and deliver it.

    Sent whole for the bot to split into bubbles, then logged in that conversation as a Notice.
    Best-effort: logs and swallows a failure. Returns the platform that
    received the message, or None when it was skipped or failed.
    """
    source, platform_user_id = channel.source, channel.platform_user_id
    # The Notice below records the bubbles the user saw, not the raw text with
    # its control tokens; the bot splits the published reply itself.
    bubbles = split_message_bubbles(response)
    try:
        conversation_id = await BotService.get_or_create_session(
            platform=source.value,
            platform_user_id=platform_user_id,
            # No channel: this delivery goes to the user's DM, the only destination
            # publish_outbound_message can resolve from the platform link. See
            # BotService.build_session_key for how a DM keys.
            channel_id=None,
            user=user,
            is_dm=True,
        )
        notice_id = f"notice:{uuid4()}"
        # The channel already carries the account id; a second read of the user
        # document to recompute it is what destination_override exists to skip.
        result = await publish_outbound_message(
            source, user_id, [response], destination_override=platform_user_id
        )
        if result is OutboundResult.FAILED:
            log.error(
                f"{LogTag.AGENT} workflow platform publish failed",
                platform=source.value,
                conversation_id=conversation_id,
                notice_id=notice_id,
                bubbles=len(bubbles),
            )
            return None
        if result is OutboundResult.PUBLISHED:
            # The nonblank bubbles as sent (the outbound path strips sentinels and
            # blanks), not the raw response, which still has control tokens.
            delivered_text = "\n\n".join(b.strip() for b in bubbles if b.strip())
            notice = Notice(id=notice_id, text=delivered_text, origin=origin)
            await accept(runtime_ports(), conversation_id, user_id, notice)
        log.info(
            f"{LogTag.AGENT} workflow result delivered to platform",
            platform=source.value,
            conversation_id=conversation_id,
            notice_id=notice_id,
            bubbles=len(bubbles),
            result=result.value,
        )
        return source if result is OutboundResult.PUBLISHED else None
    except Exception as e:  # best-effort per platform
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=source.value,
            error=str(e),
        )
        return None
