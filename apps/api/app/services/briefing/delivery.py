"""Deliver a stored brief: in-app through the notification orchestrator, by email when wanted, and to the chat platform."""

from app.agents.core.background.platform_chat import PlatformImage, post_to_platform_chat
from app.constants.notifications import (
    NotificationChannel,
    ProactiveMessageClass,
)
from app.models.briefing_models import (
    BriefingKind,
    BriefingPayload,
)
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    RedirectConfig,
)
from app.models.user_models import UserDocument
from app.services.briefing.conversation import post_brief_message
from app.services.briefing.message import (
    brief_path,
    chat_text,
    delivered_message,
)
from app.services.briefing.store import StoredBrief
from app.services.briefing.view import briefing_card, briefing_view
from app.services.delivery.chat_channel import ChatChannel, resolve_proactive_target
from app.services.notification_service import notification_service
from app.services.outbound_delivery import OutboundResult
from app.utils.auth_utils import build_user_context
from app.utils.notification.channel_preferences import normalize_channel_preferences


def _wants_email(user: UserDocument) -> bool:
    """Email goes out when the user left it on and has an address on file."""
    prefs = normalize_channel_preferences(user.notification_channel_prefs)
    return prefs[NotificationChannel.EMAIL] and bool((user.email or "").strip())


async def _post_to_chat(
    user: UserDocument, channel: ChatChannel, text: str, image_url: str, kind: BriefingKind
) -> OutboundResult:
    """Post the edition image captioned with text's first bubble, the rest after it, into the DM.

    A reply there lands with the brief in context.
    """
    return await post_to_platform_chat(
        user=build_user_context(user, auth_provider=None),
        channel=channel,
        text=text,
        origin=f"{kind} brief",
        message_class=ProactiveMessageClass.ROUTINE,
        image=PlatformImage(url=image_url, filename=f"gaia-{kind}-brief.jpg"),
    )


async def deliver_brief(
    user: UserDocument,
    stored: StoredBrief,
    payload: BriefingPayload,
    notification_kind: str,
    *,
    push: bool,
) -> list[str]:
    """Deliver one brief in-app and, when pushed, to email and the user's chat.

    The orchestrator gets only in-app (plus email when wanted), never the chat platform:
    that message is the edition photo, posted through post_to_platform_chat.
    """
    kind: BriefingKind = stored.briefing.kind
    message = delivered_message(payload)
    target = await resolve_proactive_target(user.id) if push else None
    channel = target if isinstance(target, ChatChannel) else None
    card = briefing_card(briefing_view(stored.briefing))
    channels = [NotificationChannel.INAPP] + (
        [NotificationChannel.EMAIL] if push and _wants_email(user) else []
    )
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=user.id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            priority=2,
            channels=[ChannelConfig(channel_type=c) for c in channels],
            content=NotificationContent(
                title=payload.headline,
                body=message,
                rich_content=payload.model_dump(),
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label="Open briefing",
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url=brief_path(stored.briefing.id),
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata={
                **card.model_dump(exclude={"kind"}),
                "kind": notification_kind,
                "brief_url": stored.link,
            },
        )
    )
    await post_brief_message(user.id, message, card)
    delivered = [c.channel_type for c in record.channels if c.reached_user]
    if channel:
        text = chat_text(payload, stored.link)
        result = await _post_to_chat(user, channel, text, stored.image.chat_url, kind)
        if result is OutboundResult.PUBLISHED:
            delivered.append(channel.source.value)
    return delivered
