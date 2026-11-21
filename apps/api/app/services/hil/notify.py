"""Wake a user who is not watching when an approval is waiting.

The approval's entry in the conversation log is its record: open clients render
it off the events stream and a bot's conversation follower asks about it. The
phone is woken by a push. An approval asked in GAIA's own work (a todo's or a
workflow's chat) has no follower, so it also goes to the chat app that work's
results go to, as its question and a link to that chat. One notification keyed
by the approval, so a replayed gate sends nothing twice.
"""

from app.constants.chat import SourceCategory
from app.constants.notifications import (
    APPROVAL_CHAT_LINK_LABEL,
    APPROVAL_PUSH_TITLE,
    CHANNEL_TYPE_PUSH,
    NotificationKind,
)
from app.db.repositories.conversations import conversation_repository
from app.models.notification.details_models import ApprovalNotification
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    notification_id,
)
from app.services.delivery.chat_channel import ChatChannel, resolve_proactive_target
from app.services.hil.utils import GatedApproval
from app.services.notification_service import notification_service
from app.utils.artifact_utils import FILE_LINKS


async def notify_approval_pending(approval: GatedApproval) -> None:
    """Push the pending approval to the user's phones, and to their chat app when no bot follows its chat."""
    channels = [ChannelConfig(channel_type=CHANNEL_TYPE_PUSH)]
    source = await conversation_repository.get_source(
        approval.conversation_id, user_id=approval.user_id
    )
    if SourceCategory.from_source(source) is SourceCategory.BG:
        target = await resolve_proactive_target(approval.user_id)
        if isinstance(target, ChatChannel):
            channels.append(ChannelConfig(channel_type=target.source.value))
    page = FILE_LINKS.conversation_page(approval.conversation_id)
    await notification_service.notify(
        NotificationRequest(
            id=notification_id(approval.user_id, "approval", approval.approval_id),
            user_id=approval.user_id,
            source=NotificationSourceEnum.APPROVAL,
            channels=channels,
            content=NotificationContent(title=APPROVAL_PUSH_TITLE, body=approval.summary),
            details=ApprovalNotification(
                kind=NotificationKind.APPROVAL,
                conversation_id=approval.conversation_id,
                approval_id=approval.approval_id,
            ),
            message=f"**{approval.question}**\n\n[{APPROVAL_CHAT_LINK_LABEL}]({page})",
        )
    )
