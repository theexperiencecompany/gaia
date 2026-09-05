"""Unit tests for the onboarding conversation seeder.

The seeded turn is written once and never regenerated, so the shape it lands in
Mongo with, one bot message per line and the chips on the last, is the only
chance to get it right.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.services.onboarding.first_conversation import (
    FirstConversation,
    compose_first_conversation,
    with_starting_jobs,
)
from app.utils.seeding_utils import seed_first_conversation

MODULE = "app.utils.seeding_utils"


def _composed() -> FirstConversation:
    return with_starting_jobs(
        compose_first_conversation(),
        ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"],
    )


@pytest.mark.unit
class TestSeedFirstConversation:
    async def test_seeds_one_message_per_line_with_chips_on_the_last(self) -> None:
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

        assert all(m.tool_data is None for m in messages)

        # The chips hang off the last message only, so they render once.
        assert messages[-1].follow_up_actions == composed.follow_ups
        assert [m.follow_up_actions for m in messages[:-1]] == [None] * (len(messages) - 1)

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
