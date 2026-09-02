from uuid import uuid4

from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationModel, MessageModel
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import create_conversation_service
from shared.py.wide_events import log

_HOLO_CARD_CONVERSATION_DESCRIPTION = "Your holo card is ready"


async def seed_holo_card_conversation(user_id: str, message: str) -> str | None:
    """Seed the conversation that hands the user their holo card.

    One unread GAIA turn holding a statically composed message — no LLM, no user
    turn to answer. Returns the conversation id, or None if seeding failed
    (the announcement is a reward, never a reason to fail the pipeline).
    """
    log.set(operation="seed_holo_card_conversation", user_id=user_id)
    try:
        conversation_id = str(uuid4())
        conversation = ConversationModel(
            conversation_id=conversation_id,
            description=_HOLO_CARD_CONVERSATION_DESCRIPTION,
            is_system_generated=True,
            is_unread=True,
        )

        user_dict: AuthenticatedUser = {"user_id": user_id}
        await create_conversation_service(conversation, user_dict)

        message_ids = await conversation_repository.append_messages(
            conversation_id,
            user_id=user_id,
            messages=[MessageModel(type="bot", response=message)],
        )
        if message_ids is None:
            log.error(
                f"{LogTag.STARTUP} Seeded holo card conversation vanished before its message",
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return None

        log.info(
            f"{LogTag.STARTUP} Seeded holo card conversation for user",
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return conversation_id

    except Exception as e:
        log.error(
            f"{LogTag.STARTUP} Failed to seed holo card conversation for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
