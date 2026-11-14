"""A new conversation's title, generated from its first message by the chat path's own generator."""

from app.models.conversation_log_models import UserMessage
from app.models.user_models import AuthenticatedUser
from app.services.conversation.runtime import runtime_ports
from app.utils.chat_utils import generate_and_update_description
from shared.py.analytics.catalog.attribution import Actor
from shared.py.analytics.context import analytics_context, current_analytics_context
from shared.py.conversation_wire import ConversationUpdatedFrame


async def title_conversation(
    conversation_id: str, user: AuthenticatedUser, first: UserMessage
) -> None:
    """Title the conversation from its first message, then tell its open clients."""
    # The title is the agent's work, not the user's.
    with analytics_context(current_analytics_context().acting_as(Actor.AGENT)):
        description = await generate_and_update_description(
            conversation_id,
            {"role": "user", "content": first.text},
            user,
            first.selected_tool,
            first.selected_workflow,
        )
    await runtime_ports().frames.publish(
        conversation_id, ConversationUpdatedFrame(description=description)
    )
