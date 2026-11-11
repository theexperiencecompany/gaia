"""GAIA's brief message: one Briefings conversation per user, each brief its text plus the folded edition."""

from datetime import UTC, datetime
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import time_machine

from app.models.briefing_models import BriefingCardData
from app.models.chat_models import SystemPurpose
from app.services.briefing.conversation import (
    BRIEFING_CONVERSATION_MAX_MESSAGES,
    post_brief_message,
)

MODULE = "app.services.briefing.conversation"
CARD = BriefingCardData(
    briefing_id="brief_1",
    date="2026-10-23",
    kind="daily",
    headline="Three decisions are waiting",
    edition_image_url="https://cdn.test/brief_1.png",
    edition_fold=0.3,
    edition_paper=None,
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


@time_machine.travel(datetime(2026, 10, 23, 1, 35, tzinfo=UTC), tick=False)
async def test_a_brief_is_stamped_with_now_a_fresh_id_and_the_conversations_cap() -> None:
    finder = AsyncMock(return_value=SimpleNamespace(conversation_id="conv-1"))
    with (
        patch(f"{MODULE}.conversation_repository.find_system_conversation", finder),
        patch(f"{MODULE}.update_messages", AsyncMock()) as update,
    ):
        await post_brief_message("user-1", "First.", CARD)
        await post_brief_message("user-1", "Second.", CARD)

    finder.assert_awaited_with("user-1", SystemPurpose.BRIEFING)
    first, second = (call.args[0].messages[0] for call in update.await_args_list)
    assert first.date == "2026-10-23T01:35:00+00:00"
    assert first.tool_data is not None
    assert first.tool_data[0]["timestamp"] == "2026-10-23T01:35:00+00:00"
    assert re.fullmatch(r"[0-9a-f-]{36}", first.message_id or "")
    assert first.message_id != second.message_id
    assert update.await_args.kwargs == {"max_messages": BRIEFING_CONVERSATION_MAX_MESSAGES}
    assert BRIEFING_CONVERSATION_MAX_MESSAGES == 60
