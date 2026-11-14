"""GAIA's in-app delivery of a brief into the user's Briefings conversation: its message, edition attached."""

from datetime import UTC, datetime
from uuid import uuid4

from app.db.repositories.conversations import conversation_repository
from app.models.briefing_models import BriefingCardData
from app.models.chat_models import (
    MessageModel,
    SystemPurpose,
    ToolDataEntry,
    UpdateMessagesRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import create_system_conversation, update_messages

BRIEFING_CONVERSATION_TITLE = "Briefings"
BRIEFING_TOOL_NAME = "briefing_data"
# A card a day plus weeklies; capped like a workflow thread so it never nears 16MB.
BRIEFING_CONVERSATION_MAX_MESSAGES = 60


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


async def post_brief_message(user_id: str, text: str, card: BriefingCardData) -> None:
    """Append GAIA's brief message to the Briefings conversation: its text, with the folded edition attached."""
    now = datetime.now(UTC).isoformat()
    message = MessageModel(
        type="bot",
        response=text,
        date=now,
        message_id=str(uuid4()),
        tool_data=[
            ToolDataEntry(tool_name=BRIEFING_TOOL_NAME, data=card.model_dump(), timestamp=now)
        ],
    )
    await update_messages(
        UpdateMessagesRequest(
            conversation_id=await _briefing_conversation_id(user_id), messages=[message]
        ),
        AuthenticatedUser(user_id=user_id),
        max_messages=BRIEFING_CONVERSATION_MAX_MESSAGES,
    )
