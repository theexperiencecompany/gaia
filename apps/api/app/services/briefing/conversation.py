"""GAIA's in-app delivery of a brief into the user's Briefings conversation: its notice, edition attached."""

from datetime import UTC, datetime

from app.db.repositories.conversations import conversation_repository
from app.models.brief_view_models import BriefCard
from app.models.chat_models import SystemPurpose
from app.models.conversation_log_models import Notice
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.conversation_service import create_system_conversation
from shared.py.conversation_wire import ToolDataEntry

BRIEFING_CONVERSATION_TITLE = "Briefings"
BRIEFING_TOOL_NAME = "briefing_data"


async def _briefing_conversation_id(user_id: str) -> str:
    existing = await conversation_repository.find_system_conversation(
        user_id, SystemPurpose.BRIEFING
    )
    if existing is not None:
        return existing.conversation_id
    created = await create_system_conversation(
        user_id, BRIEFING_CONVERSATION_TITLE, SystemPurpose.BRIEFING
    )
    return created.conversation_id


async def post_brief_message(
    user_id: str, briefing_id: str, text: str, card: BriefCard | None
) -> None:
    """Log the brief as a Notice in the Briefings conversation, keyed by the brief so a retried delivery logs it once.

    A quiet day's note has no edition, so it is the text alone.
    """
    tool_data = (
        (
            ToolDataEntry(
                tool_name=BRIEFING_TOOL_NAME,
                data=card.model_dump(),
                timestamp=datetime.now(UTC).isoformat(),
            ),
        )
        if card is not None
        else ()
    )
    notice = Notice(
        id=f"brief:{briefing_id}",
        text=text,
        origin=f"brief {briefing_id}",
        tool_data=tool_data,
    )
    await accept(runtime_ports(), await _briefing_conversation_id(user_id), user_id, notice)
