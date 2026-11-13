"""Unit tests for the onboarding conversation seeder.

The seeded turn is written once and never regenerated, so the notices it logs,
one per bubble group and the chips on the last, are the only chance to get it right.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.conversation_log_models import Notice
from app.models.user_models import OnboardingPreferences
from app.services.conversation.runtime import install_runtime_ports
from app.services.onboarding.first_conversation import (
    FirstConversation,
    compose_first_conversation,
    with_starting_jobs,
)
from app.utils.message_breaks import split_message_bubbles
from app.utils.seeding_utils import seed_first_conversation, seed_holo_card_conversation
from tests.unit.services.conversation.runtime_doubles import Runtime

MODULE = "app.utils.seeding_utils"
USER = "user-1"


def _composed() -> FirstConversation:
    return with_starting_jobs(
        compose_first_conversation(
            OnboardingPreferences(profession="founder", needs=[]), "telegram"
        ),
        ["Find investors", "Fix my marketing", "Hire someone", "Write my pitch"],
    )


@pytest.fixture
def runtime() -> Iterator[Runtime]:
    runtime = Runtime()
    install_runtime_ports(runtime.ports)
    return runtime


@pytest.fixture
def create() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.create_conversation_service", AsyncMock()) as create:
        yield create


async def _notices(runtime: Runtime, conversation_id: str) -> list[Notice]:
    logged = await runtime.log.read_after(conversation_id, USER, 0)
    notices = [entry.entry for entry in logged]
    assert all(isinstance(notice, Notice) for notice in notices)
    return [notice for notice in notices if isinstance(notice, Notice)]


@pytest.mark.unit
class TestSeedFirstConversation:
    async def test_logs_three_notices_buttons_between_the_opening_and_the_question(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        composed = _composed()

        conversation_id = await seed_first_conversation(USER, composed)

        assert conversation_id is not None
        conversation = create.await_args.args[0]
        assert conversation.description == "Getting started"
        assert conversation.is_system_generated is True
        assert conversation.is_unread is True
        assert conversation.conversation_id == conversation_id
        assert create.await_args.args[1].user_id == USER

        opening, buttons, question = await _notices(runtime, conversation_id)
        assert opening.text == NEW_MESSAGE_BREAKER.join(composed.opening)
        assert split_message_bubbles(opening.text) == composed.opening
        assert (opening.tool_data, opening.follow_up_actions) == ((), ())
        # Cards render above a message's bubbles, so the buttons live in a
        # message of their own: under the routines, above the question.
        assert buttons.text == ""
        assert buttons.tool_data == (composed.connect_tool_data(),)
        assert buttons.follow_up_actions == ()
        assert question.text == composed.question
        assert question.tool_data == ()
        # The chips hang off the last message only, so they render once.
        assert list(question.follow_up_actions) == composed.follow_ups
        assert len({opening.id, buttons.id, question.id}) == 3

    async def test_the_wide_event_names_the_operation_and_the_user(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        """Fire-and-forget: this context is the only way to find the run in the logs."""
        with patch(f"{MODULE}.log") as log:
            await seed_first_conversation(USER, _composed())

        log.set.assert_called_once_with(operation="seed_first_conversation", user_id=USER)

    async def test_a_failure_is_logged_with_its_cause_and_returns_none(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        """A missing welcome must never fail completion, but the error must name its cause."""
        with (
            patch(f"{MODULE}.accept", AsyncMock(side_effect=RuntimeError("mongo down"))),
            patch(f"{MODULE}.log") as log,
        ):
            assert await seed_first_conversation(USER, _composed()) is None

        log.error.assert_called_once_with(
            f"{LogTag.ONBOARDING} Failed to seed first conversation for user",
            user_id=USER,
            error="mongo down",
            error_type="RuntimeError",
        )


@pytest.mark.unit
class TestSeedHoloCardConversation:
    """The holo card announcement is a one-shot reward turn: written once, never regenerated."""

    async def test_logs_one_notice_in_an_unread_conversation(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        conversation_id = await seed_holo_card_conversation(USER, "Your card is here")

        assert conversation_id is not None
        conversation = create.await_args.args[0]
        assert conversation.conversation_id == conversation_id
        assert conversation.description == "Your holo card is ready"
        assert conversation.is_system_generated is True
        # Unread is what raises the badge: a read conversation is a reward nobody is told about.
        assert conversation.is_unread is True
        assert create.await_args.args[1].user_id == USER
        [notice] = await _notices(runtime, conversation_id)
        assert notice.text == "Your card is here"

    async def test_each_seed_gets_its_own_random_conversation_id(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        """A constant id would land the second user's card in the first user's conversation."""
        first = await seed_holo_card_conversation(USER, "one")
        second = await seed_holo_card_conversation(USER, "two")

        assert first is not None and second is not None
        assert first != second
        UUID(first)

    async def test_the_wide_event_names_the_operation_and_the_user(
        self, runtime: Runtime, create: AsyncMock
    ) -> None:
        with patch(f"{MODULE}.log") as log:
            await seed_holo_card_conversation(USER, "Your card is here")

        log.set.assert_called_once_with(operation="seed_holo_card_conversation", user_id=USER)

    async def test_a_failure_is_swallowed_and_named_with_its_cause(self, runtime: Runtime) -> None:
        """The announcement is a reward, never a reason to fail the pipeline, but the error must name its cause."""
        with (
            patch(
                f"{MODULE}.create_conversation_service",
                AsyncMock(side_effect=RuntimeError("mongo down")),
            ),
            patch(f"{MODULE}.log") as log,
        ):
            assert await seed_holo_card_conversation(USER, "Your card is here") is None

        log.error.assert_called_once_with(
            f"{LogTag.STARTUP} Failed to seed holo card conversation for user",
            user_id=USER,
            error="mongo down",
            error_type="RuntimeError",
        )
