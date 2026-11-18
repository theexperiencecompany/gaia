"""Deliver a stored brief step by step, recording each step on the brief the moment it succeeds.

The steps are the notification (in-app, plus email when wanted), GAIA's message in the Briefings
conversation, and, when pushed, the edition in the user's chat app. A run that dies mid-delivery
leaves the done steps recorded, so the retry sends only what is left; the step that completes the
delivery consumes the held results the brief carries.
"""

from datetime import UTC, datetime

from app.agents.core.background.platform_chat import PlatformImage, post_to_platform_chat
from app.constants.briefing import (
    BRIEF_NOTIFICATION_ACTION_LABEL,
    BRIEF_NOTIFICATION_PRIORITY,
    EditionVariant,
)
from app.constants.notifications import (
    NotificationChannel,
    NotificationKind,
    ProactiveMessageClass,
)
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.pending_brief_items import pending_brief_items_repository
from app.models.brief_document_models import BriefDelivery, BriefingModel, DeliveryStep
from app.models.brief_view_models import (
    BriefCard,
    BriefEditionNotification,
    BriefNoteNotification,
    BriefNotificationMetadata,
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
from app.services.briefing.view import briefing_card
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


def _notification_metadata(
    brief: BriefingModel, kind: NotificationKind, card: BriefCard | None
) -> BriefNotificationMetadata:
    """Return what the brief's notification carries: a note its kind, an edition its link and card."""
    if kind is NotificationKind.BRIEFING_NOTE:
        return BriefNoteNotification(kind=kind)
    if brief.payload.link is None or card is None:
        raise ValueError(f"{kind} brief {brief.id} was stored without its link or edition")
    return BriefEditionNotification(kind=kind, brief_url=brief.payload.link, card=card)


async def _notify(
    user: UserDocument, brief: BriefingModel, plan: BriefDelivery, card: BriefCard | None
) -> list[str]:
    """Notify in-app and, when pushed and wanted, by email; return the channels it reached."""
    payload = brief.payload
    channels = [NotificationChannel.INAPP] + (
        [NotificationChannel.EMAIL] if plan.push and _wants_email(user) else []
    )
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=user.id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            priority=BRIEF_NOTIFICATION_PRIORITY,
            channels=[ChannelConfig(channel_type=c) for c in channels],
            content=NotificationContent(
                title=payload.headline,
                body=delivered_message(payload),
                actions=[
                    NotificationAction(
                        type=ActionType.REDIRECT,
                        label=BRIEF_NOTIFICATION_ACTION_LABEL,
                        style=ActionStyle.PRIMARY,
                        config=ActionConfig(
                            redirect=RedirectConfig(
                                url=brief_path(brief.id),
                                open_in_new_tab=False,
                                close_notification=True,
                            )
                        ),
                    )
                ],
            ),
            metadata=_notification_metadata(brief, plan.notification_kind, card).model_dump(),
        )
    )
    reached = [c.channel_type for c in record.channels if c.reached_user]
    if NotificationChannel.EMAIL in channels and NotificationChannel.EMAIL not in reached:
        log.warning(
            "briefing.email_not_sent",
            statuses={c.channel_type: c.status.value for c in record.channels},
        )
    return reached


async def _post_to_chat(user: UserDocument, channel: ChatChannel, brief: BriefingModel) -> bool:
    """Post the edition captioned with the headline, then the message, into the user's DM.

    A note has no edition and posts as text. A reply there lands with the brief in context.
    """
    payload, edition = brief.payload, brief.edition
    result = await post_to_platform_chat(
        user=build_user_context(user, auth_provider=None),
        channel=channel,
        text=chat_text(payload, payload.link)
        if payload.link is not None
        else delivered_message(payload),
        origin=f"{brief.kind} brief",
        message_class=ProactiveMessageClass.ROUTINE,
        image=PlatformImage(
            url=await edition_url(edition.key, EditionVariant.JPG, datetime.now(UTC)),
            filename=f"gaia-{brief.kind}-brief.jpg",
        )
        if edition is not None
        else None,
    )
    return result is OutboundResult.PUBLISHED


async def deliver_brief(user: UserDocument, brief: BriefingModel) -> list[str]:
    """Run every delivery step the stored brief has left, then complete it; return the channels it reached.

    The orchestrator gets only in-app (plus email when wanted), never the chat platform: that
    message is the edition photo, posted through post_to_platform_chat.
    """
    plan = brief.delivery
    if plan is None:
        raise ValueError(f"brief {brief.id} was stored without a delivery plan")
    reached = list(brief.delivered_channels)
    card = await briefing_card(brief) if brief.edition is not None else None
    if DeliveryStep.NOTIFICATION not in plan.done:
        notified = await _notify(user, brief, plan, card)
        await briefing_repository.record_step(
            user.id, brief.id, DeliveryStep.NOTIFICATION, notified
        )
        reached += notified
    if DeliveryStep.CONVERSATION not in plan.done:
        await post_brief_message(user.id, delivered_message(brief.payload), card)
        await briefing_repository.record_step(user.id, brief.id, DeliveryStep.CONVERSATION, [])
    if plan.push and DeliveryStep.CHAT not in plan.done:
        target = await resolve_proactive_target(user.id)
        posted = isinstance(target, ChatChannel) and await _post_to_chat(user, target, brief)
        platform = [target.source.value] if isinstance(target, ChatChannel) and posted else []
        await briefing_repository.record_step(user.id, brief.id, DeliveryStep.CHAT, platform)
        reached += platform
    if plan.held_ids:
        await pending_brief_items_repository.consume(user.id, plan.held_ids)
    await briefing_repository.complete_delivery(user.id, brief.id)
    return reached
