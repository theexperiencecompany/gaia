"""GAIA's reaction on a user message: stored as the message's field, announced as one reaction frame."""

from collections.abc import Iterator
from dataclasses import dataclass
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.reactions import ReactionReason
from app.models.chat_models import MessageReaction, ReactionBy
from app.services.conversation.ack import ReactionDecision
from app.services.conversation.reaction import (
    InstantReactionInput,
    ReactionTarget,
    react_as_chat_model,
    react_instantly,
)

_TARGET = ReactionTarget(
    stream_id="stream-1", conversation_id="conv-1", user_id="user-1", message_id="umsg-1"
)
_INPUT = InstantReactionInput(message_text="find my flight email", previous_assistant_text="")


@dataclass
class _Io:
    decide: AsyncMock
    write: AsyncMock
    publish: AsyncMock

    def frames(self) -> list[dict[str, object]]:
        return [json.loads(call.args[1][len("data: ") :]) for call in self.publish.await_args_list]


@pytest.fixture
def io() -> Iterator[_Io]:
    decide = AsyncMock(return_value=ReactionDecision(emoji="🔎", reason=ReactionReason.REACTED))
    write = AsyncMock(return_value=True)
    publish = AsyncMock()
    with (
        patch("app.services.conversation.reaction.decide_reaction", new=decide),
        patch(
            "app.services.conversation.reaction.conversation_repository.set_message_reaction",
            new=write,
        ),
        patch("app.services.conversation.reaction.stream_manager.publish_chunk", new=publish),
    ):
        yield _Io(decide=decide, write=write, publish=publish)


class TestReactInstantly:
    async def test_a_fitting_emoji_is_stored_only_if_unset_then_published(self, io: _Io) -> None:
        placed = await react_instantly(_TARGET, _INPUT)

        assert placed == "🔎"
        io.decide.assert_awaited_once_with("find my flight email", "")
        io.write.assert_awaited_once_with(
            "conv-1",
            user_id="user-1",
            message_id="umsg-1",
            reaction=MessageReaction(emoji="🔎", by=ReactionBy.JEV),
            only_if_unset=True,
        )
        assert io.publish.await_args.args[0] == "stream-1"
        assert io.frames() == [{"reaction": {"message_id": "umsg-1", "emoji": "🔎", "by": "jev"}}]

    async def test_no_reaction_when_the_classifier_picks_none(self, io: _Io) -> None:
        io.decide.return_value = ReactionDecision(reason=ReactionReason.UPSET)

        assert await react_instantly(_TARGET, _INPUT) is None
        io.write.assert_not_awaited()
        io.publish.assert_not_awaited()

    async def test_a_message_already_reacted_to_is_left_alone_and_nothing_is_published(
        self, io: _Io
    ) -> None:
        io.write.return_value = False

        assert await react_instantly(_TARGET, _INPUT) is None
        io.publish.assert_not_awaited()

    async def test_a_failed_write_is_no_reaction_and_never_raises(self, io: _Io) -> None:
        io.write.side_effect = RuntimeError("m" * 400)

        with patch("app.services.conversation.reaction.log.error") as log_error:
            assert await react_instantly(_TARGET, _INPUT) is None

        io.publish.assert_not_awaited()
        log_error.assert_called_once_with(
            "reaction_ack.place_failed",
            conversation_id="conv-1",
            error="m" * 300,
            error_type="RuntimeError",
        )


class TestReactAsChatModel:
    async def test_the_chat_models_pick_replaces_whatever_is_there(self, io: _Io) -> None:
        await react_as_chat_model(_TARGET, "👍")

        io.write.assert_awaited_once_with(
            "conv-1",
            user_id="user-1",
            message_id="umsg-1",
            reaction=MessageReaction(emoji="👍", by=ReactionBy.CHAT_MODEL),
        )
        assert io.frames() == [
            {"reaction": {"message_id": "umsg-1", "emoji": "👍", "by": "chat_model"}}
        ]
