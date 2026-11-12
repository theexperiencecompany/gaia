"""GAIA's reaction on a user message: stored as the message's field, announced as one reaction frame."""

from collections.abc import Iterator
from dataclasses import dataclass
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.reactions import ReactionReason
from app.services.conversation.ack import ReactionDecision
from app.services.conversation.reaction import ReactionTarget

_TARGET = ReactionTarget(
    stream_id="stream-1", conversation_id="conv-1", user_id="user-1", message_id="umsg-1"
)


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
