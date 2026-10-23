"""GAIA's brief message: one Briefings conversation per user, each brief its text plus the folded edition."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.briefing_models import BriefingCardData
from app.models.chat_models import SystemPurpose
from app.services.briefing.conversation import post_brief_message

MODULE = "app.services.briefing.conversation"
CARD = BriefingCardData(
    briefing_id="brief_1",
    date="2026-10-23",
    kind="daily",
    headline="Three decisions are waiting",
    edition_image_url="https://cdn.test/brief_1.png",
    edition_fold=0.3,
    edition_name="Air Mail",
    stamp_city_name="Bogotá",
    needs_you_count=3,
)


async def test_the_first_brief_opens_the_briefings_conversation_and_posts_its_card() -> None:
    with (
        patch(
            f"{MODULE}.conversation_repository.find_system_conversation",
            AsyncMock(return_value=None),
        ),
        patch(
            f"{MODULE}.create_system_conversation",
            AsyncMock(return_value=SimpleNamespace(conversation_id="conv-new")),
        ) as create,
        patch(f"{MODULE}.update_messages", AsyncMock()) as update,
    ):
        await post_brief_message("user-1", "Good morning, Ada.", CARD)

    create.assert_awaited_once_with("user-1", "Briefings", SystemPurpose.BRIEFING)
    request, user = update.await_args.args
    assert (request.conversation_id, user.user_id) == ("conv-new", "user-1")
    [message] = request.messages
    assert (message.type, message.response) == ("bot", "Good morning, Ada.")
    [entry] = message.tool_data or []
    assert (entry["tool_name"], entry["data"]) == ("briefing_data", CARD.model_dump())


async def test_later_briefs_join_the_existing_conversation() -> None:
    with (
        patch(
            f"{MODULE}.conversation_repository.find_system_conversation",
            AsyncMock(return_value=SimpleNamespace(conversation_id="conv-1")),
        ),
        patch(f"{MODULE}.create_system_conversation", AsyncMock()) as create,
        patch(f"{MODULE}.update_messages", AsyncMock()) as update,
    ):
        await post_brief_message("user-1", "Good morning, Ada.", CARD)

    create.assert_not_awaited()
    assert update.await_args.args[0].conversation_id == "conv-1"
