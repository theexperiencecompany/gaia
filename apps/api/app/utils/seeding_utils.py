from typing import cast
from uuid import uuid4

from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationModel, MessageModel, SystemPurpose, ToolDataEntry
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import create_conversation_service
from app.services.onboarding.first_conversation import FirstConversation
from shared.py.wide_events import log

_HOLO_CARD_CONVERSATION_DESCRIPTION = "Your holo card is ready"
_FIRST_CONVERSATION_DESCRIPTION = "Getting started"


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


async def seed_first_conversation(user_id: str, composed: FirstConversation) -> str | None:
    """Seed the "Getting started" conversation GAIA opens with after onboarding.

    One unread conversation holding ONE bot message whose lines are joined by
    the message breaker, so the web renders them as grouped bubbles that land one
    after another with the same choreography every multi-bubble reply gets, and
    the starting-job chips ride that message. Returns the conversation id, or
    None if seeding failed — a missing welcome must never fail completion.
    """
    log.set(operation="seed_first_conversation", user_id=user_id)
    try:
        conversation_id = str(uuid4())
        conversation = ConversationModel(
            conversation_id=conversation_id,
            description=_FIRST_CONVERSATION_DESCRIPTION,
            is_system_generated=True,
            system_purpose=SystemPurpose.GETTING_STARTED,
            is_unread=True,
        )

        user_dict: AuthenticatedUser = {"user_id": user_id}
        await create_conversation_service(conversation, user_dict)

        # Three bot messages, grouped by the web like iMessage. A message's
        # cards render ABOVE its bubbles, so the buttons get a message of their
        # own between the routines and the question, and the chips ride the
        # question.
        messages = [
            MessageModel(type="bot", response=NEW_MESSAGE_BREAKER.join(composed.opening)),
            MessageModel(
                type="bot",
                response="",
                tool_data=[cast(ToolDataEntry, composed.connect_tool_data())],
            ),
            MessageModel(
                type="bot",
                response=composed.question,
                follow_up_actions=composed.follow_ups,
            ),
        ]

        message_ids = await conversation_repository.append_messages(
            conversation_id,
            user_id=user_id,
            messages=messages,
        )
        if message_ids is None:
            log.error(
                f"{LogTag.ONBOARDING} Seeded first conversation vanished before its messages",
                conversation_id=conversation_id,
                user_id=user_id,
            )
            return None

        log.info(
            f"{LogTag.ONBOARDING} Seeded first conversation for user",
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return conversation_id

    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} Failed to seed first conversation for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
