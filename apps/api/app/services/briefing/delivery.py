"""Deliver a stored brief: in-app through the notification orchestrator, by email when wanted, and to the chat platform."""

from datetime import UTC, datetime

from app.agents.core.background.platform_chat import PlatformImage, post_to_platform_chat
from app.constants.briefing import EditionVariant
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
from app.services.briefing.edition_image import edition_url
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
from shared.py.wide_events import log


def _wants_email(user: UserDocument) -> bool:
    """Email goes out when the user left it on and has an address on file."""
    prefs = normalize_channel_preferences(user.notification_channel_prefs)
    return prefs[NotificationChannel.EMAIL] and bool((user.email or "").strip())


async def _post_to_chat(
    user: UserDocument,
    channel: ChatChannel,
    text: str,
    image: PlatformImage | None,
    kind: BriefingKind,
) -> OutboundResult:
    """Post the edition image captioned with text's first bubble, the rest after it, into the DM.

    A note has no image and posts as text. A reply there lands with the brief in context.
    """
    return await post_to_platform_chat(
        user=build_user_context(user, auth_provider=None),
        channel=channel,
        text=text,
        origin=f"{kind} brief",
        message_class=ProactiveMessageClass.ROUTINE,
        image=image,
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
    that message is the edition photo, posted through post_to_platform_chat. A quiet day's
    note has no edition: it goes everywhere as plain text, under the note's notification kind.
    """
    kind: BriefingKind = stored.briefing.kind
    message = delivered_message(payload)
    target = await resolve_proactive_target(user.id) if push else None
    channel = target if isinstance(target, ChatChannel) else None
    edition = stored.briefing.edition
    card = briefing_card(await briefing_view(stored.briefing)) if edition is not None else None
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
                rich_content=payload.model_dump() if edition is not None else None,
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
                **(card.model_dump() if card is not None else {}),
                "kind": notification_kind,
                "brief_url": stored.link,
            },
        )
    )
    await post_brief_message(user.id, message, card)
    delivered = [c.channel_type for c in record.channels if c.reached_user]
    if NotificationChannel.EMAIL in channels and NotificationChannel.EMAIL not in delivered:
        log.warning(
            "briefing.email_not_sent",
            statuses={c.channel_type: c.status.value for c in record.channels},
        )
    if channel:
        result = await _post_to_chat(
            user,
            channel,
            chat_text(payload, stored.link) if stored.link is not None else message,
            PlatformImage(
                url=await edition_url(edition.key, EditionVariant.JPG, datetime.now(UTC)),
                filename=f"gaia-{kind}-brief.jpg",
            )
            if edition is not None
            else None,
            kind,
        )
        if result is OutboundResult.PUBLISHED:
            delivered.append(channel.source.value)
    return delivered
