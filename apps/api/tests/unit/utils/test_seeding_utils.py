"""Unit tests for the onboarding conversation seeder.

The seeded turn is written once and never regenerated, so the shape it lands in
Mongo with — one message per line, the connect card on the Gmail line, the chips
on the last message — is the only chance to get it right.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_conversation import (
    FirstConversation,
    compose_first_conversation,
)
from app.utils.seeding_utils import seed_first_conversation

MODULE = "app.utils.seeding_utils"


def _composed() -> FirstConversation:
    return compose_first_conversation(
        OnboardingPreferences(
            profession="founder",
            needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR],
            other_need="chasing invoices",
        ),
        "telegram",
    )


@pytest.mark.unit
class TestSeedFirstConversation:
    async def test_seeds_one_message_per_line_with_card_and_chips(self) -> None:
        composed = _composed()
        create = AsyncMock()
        append = AsyncMock(return_value=["m1", "m2", "m3", "m4"])

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(f"{MODULE}.conversation_repository.append_messages", append),
        ):
            conversation_id = await seed_first_conversation("user-1", composed)

        assert conversation_id is not None

        conversation = create.await_args.args[0]
        assert conversation.description == "Getting started"
        assert conversation.is_system_generated is True
        assert conversation.is_unread is True
        assert conversation.conversation_id == conversation_id

        messages = append.await_args.kwargs["messages"]
        assert [m.response for m in messages] == composed.lines
        assert all(m.type == "bot" for m in messages)

        # The connect card rides the Gmail line, and only that line.
        assert messages[composed.gmail_card_line].tool_data == [
            {
                "tool_name": "integration_connection_required",
                "data": {
                    "integration_id": "gmail",
                    "expired": False,
                    "message": "To use Gmail features, please connect your account first.",
                },
            }
        ]
        assert [i for i, m in enumerate(messages) if m.tool_data] == [composed.gmail_card_line]

        # The chips hang off the last message only, so they render once.
        assert messages[-1].follow_up_actions == composed.follow_ups
        assert [m.follow_up_actions for m in messages[:-1]] == [None] * (len(messages) - 1)

    async def test_a_vanished_conversation_returns_none(self) -> None:
        with (
            patch(f"{MODULE}.create_conversation_service", AsyncMock()),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=None),
            ),
        ):
            assert await seed_first_conversation("user-1", _composed()) is None

    async def test_a_failure_is_swallowed_rather_than_raised(self) -> None:
        with patch(
            f"{MODULE}.create_conversation_service",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await seed_first_conversation("user-1", _composed()) is None
