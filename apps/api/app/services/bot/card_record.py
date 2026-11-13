"""Writing the cards a bot showed a user into that conversation's record.

The model must know everything the user can see. A card reaches a bot user
outside any model reply (the bot renders it from tool_data), so without this
record the next turn has no idea a button was ever sent, and can claim one was
sent when it was not.
"""

from app.agents.core.background.comms_narrator import record_platform_delivery
from app.db.repositories.bot_sessions import bot_session_repository
from app.schemas.bot_cards import BotCardsReport, ReportedBotCard
from app.services.analytics_service import capture
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.bots import BotCardShown


async def record_bot_cards(report: BotCardsReport, user_id: str) -> int:
    """Record report's cards in its conversation; refuse a conversation that is not this user's."""
    session = await bot_session_repository.get_by_conversation_id(report.conversation_id)
    if (
        session is None
        or session.platform != report.platform.value
        or session.platform_user_id != report.platform_user_id
    ):
        raise AppError(
            message="Conversation not found for this platform account",
            why="The reported conversation is not a bot session of this platform user.",
            status_code=404,
            code="bot_conversation_not_found",
        )

    platform_name = report.platform.display_name
    await record_platform_delivery(
        report.conversation_id,
        "\n\n".join(_record_line(card, platform_name) for card in report.cards),
    )
    for card in report.cards:
        capture(
            UserId(user_id),
            BotCardShown(
                platform=report.platform.value,
                tool_name=card.tool_name,
                delivered=card.delivered,
            ),
        )
    return len(report.cards)


def _record_line(card: ReportedBotCard, platform_name: str) -> str:
    outcome = "Shown to" if card.delivered else "FAILED to show"
    return f"[{outcome} the user on {platform_name}]: {card.text}"
