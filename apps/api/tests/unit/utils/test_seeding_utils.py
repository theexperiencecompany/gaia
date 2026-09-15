"""Unit tests for the onboarding conversation seeder.

The seeded turn is written once and never regenerated, so the shape it lands in
Mongo with, one bot message per line and the chips on the last, is the only
chance to get it right.
"""

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.user_models import OnboardingPreferences
from app.services.onboarding.first_conversation import (
    FirstConversation,
    compose_first_conversation,
    with_starting_jobs,
)
from app.utils.message_breaks import split_message_bubbles
from app.utils.seeding_utils import seed_first_conversation, seed_holo_card_conversation

MODULE = "app.utils.seeding_utils"


def _composed() -> FirstConversation:
    return with_starting_jobs(
        compose_first_conversation(
            OnboardingPreferences(profession="founder", needs=[]), "telegram"
        ),
        ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"],
    )


@pytest.mark.unit
class TestSeedFirstConversation:
    async def test_seeds_three_messages_buttons_between_the_opening_and_the_question(
        self,
    ) -> None:
        composed = _composed()
        create = AsyncMock()
        append = AsyncMock(return_value=["m1", "m2", "m3"])

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
        assert len(messages) == 3
        assert all(m.type == "bot" for m in messages)

        opening, buttons, question = messages
        assert opening.response == NEW_MESSAGE_BREAKER.join(composed.opening)
        assert split_message_bubbles(opening.response) == composed.opening
        assert opening.tool_data is None
        assert opening.follow_up_actions is None
        # Cards render above a message's bubbles, so the buttons live in a
        # message of their own: under the routines, above the question.
        assert buttons.response == ""
        assert buttons.tool_data == [composed.connect_tool_data()]
        assert buttons.follow_up_actions is None

        assert question.response == composed.question
        assert question.tool_data is None
        # The chips hang off the last message only, so they render once.
        assert question.follow_up_actions == composed.follow_ups

    async def test_the_messages_are_written_to_that_conversation_for_that_user(self) -> None:
        """The id and owner are what route the write. Sent as None — or dropped —
        the turn lands on nobody's conversation, and the caller still gets an id
        back, so nothing downstream notices the user opening an empty chat."""
        create = AsyncMock()
        append = AsyncMock(return_value=["m1"])

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(f"{MODULE}.conversation_repository.append_messages", append),
        ):
            conversation_id = await seed_first_conversation("user-1", _composed())

        append.assert_awaited_once_with(
            conversation_id,
            user_id="user-1",
            messages=append.await_args.kwargs["messages"],
        )
        assert append.await_args.args == (conversation_id,)
        assert append.await_args.kwargs["user_id"] == "user-1"

    async def test_the_wide_event_names_the_operation_and_the_user(self) -> None:
        """The seed is fire-and-forget: this context is the only way to find the
        run in the logs when a user reports landing on an empty conversation."""
        with (
            patch(f"{MODULE}.create_conversation_service", AsyncMock()),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=["m1"]),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await seed_first_conversation("user-1", _composed())

        log.set.assert_called_once_with(operation="seed_first_conversation", user_id="user-1")

    async def test_a_vanished_conversation_returns_none(self) -> None:
        with (
            patch(f"{MODULE}.create_conversation_service", AsyncMock()),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=None),
            ),
        ):
            assert await seed_first_conversation("user-1", _composed()) is None

    async def test_a_vanished_conversation_is_reported_with_both_ids(self) -> None:
        """Returning None is silent by design, so this error line is the only
        signal that the conversation was created and then lost its messages —
        without both ids it names no user and no conversation to go look at."""
        create = AsyncMock()

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=None),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            assert await seed_first_conversation("user-1", _composed()) is None

        log.error.assert_called_once_with(
            f"{LogTag.ONBOARDING} Seeded first conversation vanished before its messages",
            conversation_id=create.await_args.args[0].conversation_id,
            user_id="user-1",
        )

    async def test_a_failure_is_swallowed_rather_than_raised(self) -> None:
        with patch(
            f"{MODULE}.create_conversation_service",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ):
            assert await seed_first_conversation("user-1", _composed()) is None


@pytest.mark.unit
class TestSeedHoloCardConversation:
    """The holo card announcement is a one-shot reward turn: written once, never
    regenerated, and delivered with no user turn to answer it. Nothing else
    exercised this seeder, so every field it writes was unasserted."""

    async def test_seeds_one_unread_bot_turn_holding_the_composed_message(self) -> None:
        create = AsyncMock()
        append = AsyncMock(return_value=["m1"])

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(f"{MODULE}.conversation_repository.append_messages", append),
        ):
            conversation_id = await seed_holo_card_conversation("user-1", "Your card is here")

        assert conversation_id is not None

        conversation = create.await_args.args[0]
        assert conversation.conversation_id == conversation_id
        assert conversation.description == "Your holo card is ready"
        assert conversation.is_system_generated is True
        # Unread is what raises the badge — a read conversation is a reward
        # nobody is told about.
        assert conversation.is_unread is True

        messages = append.await_args.kwargs["messages"]
        assert len(messages) == 1
        assert messages[0].type == "bot"
        assert messages[0].response == "Your card is here"

    async def test_each_seed_gets_its_own_random_conversation_id(self) -> None:
        """The id is minted here, and every user's card is seeded through this
        one call. A constant id would make the second user's card land in the
        first user's conversation instead of their own."""
        create = AsyncMock()

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=["m1"]),
            ),
        ):
            first = await seed_holo_card_conversation("user-1", "Your card is here")
            second = await seed_holo_card_conversation("user-2", "Your card is here")

        assert first is not None and second is not None
        assert UUID(first).version == 4
        assert first != second

    async def test_the_conversation_is_created_for_that_user(self) -> None:
        """The owner is what routes the write; seeded for anyone else the user
        never sees the card and the caller still gets an id back."""
        create = AsyncMock()

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=["m1"]),
            ),
        ):
            await seed_holo_card_conversation("user-1", "Your card is here")

        assert create.await_args.args[1] == {"user_id": "user-1"}

    async def test_the_message_is_written_to_that_conversation_for_that_user(self) -> None:
        create = AsyncMock()
        append = AsyncMock(return_value=["m1"])

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(f"{MODULE}.conversation_repository.append_messages", append),
        ):
            conversation_id = await seed_holo_card_conversation("user-1", "Your card is here")

        assert append.await_args.args == (conversation_id,)
        assert append.await_args.kwargs["user_id"] == "user-1"

    async def test_the_wide_event_names_the_operation_and_the_user(self) -> None:
        """Fire-and-forget, so this context is the only handle on a run that
        left a user without their card."""
        with (
            patch(f"{MODULE}.create_conversation_service", AsyncMock()),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=["m1"]),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            await seed_holo_card_conversation("user-1", "Your card is here")

        log.set.assert_called_once_with(operation="seed_holo_card_conversation", user_id="user-1")

    async def test_a_vanished_conversation_returns_none(self) -> None:
        with (
            patch(f"{MODULE}.create_conversation_service", AsyncMock()),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=None),
            ),
        ):
            assert await seed_holo_card_conversation("user-1", "Your card is here") is None

    async def test_a_vanished_conversation_is_reported_with_both_ids(self) -> None:
        """None is returned silently by design, so this error line is the only
        signal that the conversation was created and then lost its message."""
        create = AsyncMock()

        with (
            patch(f"{MODULE}.create_conversation_service", create),
            patch(
                f"{MODULE}.conversation_repository.append_messages",
                AsyncMock(return_value=None),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            assert await seed_holo_card_conversation("user-1", "Your card is here") is None

        log.error.assert_called_once_with(
            f"{LogTag.STARTUP} Seeded holo card conversation vanished before its message",
            conversation_id=create.await_args.args[0].conversation_id,
            user_id="user-1",
        )

    async def test_a_failure_is_swallowed_and_named_with_its_cause(self) -> None:
        """The announcement is a reward, never a reason to fail the pipeline —
        but a swallowed error that names no cause cannot be diagnosed."""
        with (
            patch(
                f"{MODULE}.create_conversation_service",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            assert await seed_holo_card_conversation("user-1", "Your card is here") is None

        log.error.assert_called_once_with(
            f"{LogTag.STARTUP} Failed to seed holo card conversation for user",
            user_id="user-1",
            error="mongo down",
            error_type="RuntimeError",
        )
