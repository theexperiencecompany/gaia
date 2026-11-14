from typing import cast
from uuid import uuid4

from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationModel, SystemPurpose
from app.models.conversation_log_models import Notice
from app.models.user_models import AuthenticatedUser
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.conversation_service import create_conversation_service
from app.services.onboarding.first_conversation import FirstConversation
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER, ToolDataEntry
from shared.py.wide_events import log

_HOLO_CARD_CONVERSATION_DESCRIPTION = "Your holo card is ready"
_FIRST_CONVERSATION_DESCRIPTION = "Getting started"
#: The origin of what GAIA says in a conversation it seeds.
_SEEDED = "seeded"


async def _say(conversation_id: str, user_id: str, notices: list[Notice]) -> None:
    """Log what GAIA opens a seeded conversation with, in order, each under an id of its place."""
    for n, notice in enumerate(notices, 1):
        entry = notice.model_copy(update={"id": f"seed:{conversation_id}:{n}"})
        await accept(runtime_ports(), conversation_id, user_id, entry)


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

        await create_conversation_service(conversation, AuthenticatedUser(user_id=user_id))

        await _say(conversation_id, user_id, [Notice(id=_SEEDED, text=message, origin=_SEEDED)])

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

    Returns the conversation id, or None if seeding failed — a missing
    welcome must never fail completion.
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

        await create_conversation_service(conversation, AuthenticatedUser(user_id=user_id))

        # A message's cards render ABOVE its bubbles, so the buttons get a
        # message of their own between the routines and the question.
        notices = [
            Notice(id=_SEEDED, text=NEW_MESSAGE_BREAKER.join(composed.opening), origin=_SEEDED),
            Notice(
                id=_SEEDED,
                text="",
                origin=_SEEDED,
                tool_data=(cast(ToolDataEntry, composed.connect_tool_data()),),
            ),
            Notice(
                id=_SEEDED,
                text=composed.question,
                origin=_SEEDED,
                follow_up_actions=tuple(composed.follow_ups),
            ),
        ]
        await _say(conversation_id, user_id, notices)

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
