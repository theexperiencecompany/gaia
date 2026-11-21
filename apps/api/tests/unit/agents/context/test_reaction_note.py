"""The reaction note: comms is told it already reacted only when the instant reaction landed in time."""

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AnyMessage, SystemMessage
import pytest
from tests._harness.context_chain import text_of

from app.agents.context.assemble import AssembledContext
from app.agents.context.slots import REACTION_NOTE_MARKER, has_marker, is_gaia_authored_note
from app.agents.core import messages as messages_module

pytestmark = pytest.mark.unit

QUERY = "find my flight confirmation"


async def _placed(emoji: str | None) -> str | None:
    return emoji


async def _undecided(gate: asyncio.Event) -> str | None:
    await gate.wait()
    return "🔎"


async def _comms_messages(
    instant_reaction: asyncio.Task[str | None] | None,
    *,
    assembly: Callable[[], Awaitable[None]] | None = None,
) -> list[AnyMessage]:
    async def assemble(*_: object) -> AssembledContext:
        if assembly is not None:
            await assembly()
        return AssembledContext(stable=SystemMessage(content="ctx"), volatile=None)

    with (
        patch.object(messages_module, "assemble_context", new=assemble),
        patch.object(messages_module, "presence_note_message", AsyncMock(return_value=None)),
    ):
        return await messages_module.construct_langchain_messages(
            query=QUERY,
            scope=messages_module.MessageScope(user_id="user-1", instant_reaction=instant_reaction),
        )


def _notes(messages: list[AnyMessage]) -> list[AnyMessage]:
    return [message for message in messages if has_marker(message, REACTION_NOTE_MARKER)]


async def test_a_reaction_placed_before_the_input_is_built_is_noted_just_ahead_of_the_message() -> (
    None
):
    reaction = asyncio.create_task(_placed("🔎"))
    await asyncio.wait([reaction])

    messages = await _comms_messages(reaction)

    (note,) = _notes(messages)
    assert "🔎" in text_of(note)
    assert text_of(messages[messages.index(note) + 1]) == QUERY
    assert is_gaia_authored_note(note)


async def test_a_reaction_placed_while_context_assembles_is_noted() -> None:
    reaction = asyncio.create_task(_placed("👌"))

    async def slow_assembly() -> None:
        await asyncio.wait([reaction])

    (note,) = _notes(await _comms_messages(reaction, assembly=slow_assembly))
    assert "👌" in text_of(note)


async def test_a_reaction_still_deciding_is_not_waited_for_and_not_noted() -> None:
    reaction = asyncio.create_task(_undecided(asyncio.Event()))

    messages = await asyncio.wait_for(_comms_messages(reaction), timeout=1)

    assert _notes(messages) == []
    assert not reaction.done()
    reaction.cancel()


async def test_no_note_when_no_reaction_was_placed() -> None:
    reaction = asyncio.create_task(_placed(None))
    await asyncio.wait([reaction])

    assert _notes(await _comms_messages(reaction)) == []


async def test_no_note_when_the_turn_had_no_instant_reaction() -> None:
    assert _notes(await _comms_messages(None)) == []
