"""E2E: a hand-off's ack reaches the conversation log while the model is still writing the hand-off.

Real: the send route, the step, the comms graph with its real call_executor, the comms ledger,
the executor graph and its run, on real Mongo, Redis and the Postgres checkpointer.
Substituted: both graphs' model (scripted, streaming each call's arguments a key at a time, as
providers do), the tool store, the memory engine and the WebSocket fan-out (the e2e step stack).

Not exercised: a real LLM writing ack first, and a provider's own argument chunking.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient
from langchain_core.messages import AIMessageChunk
from pydantic import PrivateAttr
import pytest

from app.agents.tools import executor_tool
from app.models.conversation_log_models import Entry, Reply, ReplySettled, UserMessage, WorkStarted
from app.models.user_models import AuthenticatedUser
from shared.py.conversation_wire import ReplyOutcome
from tests.e2e._harness.background import drain_background_runs
from tests.e2e._harness.graph_run import StreamingScriptedModel, call, scripted_model
from tests.e2e._harness.step_stack import OpenStack, entries_of, replayed

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("conversation_indexes")]

ASK = "clean my inbox"
ACK = "on it, clearing the promos"
CLEANED = "Inbox cleaned."
NARRATED = "Done: 12 promos archived."
NOT_STARTED = "that didn't start, give me a sec to retry?"
_WAIT_SECONDS = 20.0
#: The ack is whole once the next argument begins: the hand-off's second streamed fragment.
_FRAGMENTS_UNTIL_ACK_WHOLE = 2


class _HeldAfterAck(StreamingScriptedModel):
    """Streams like the scripted model, but pauses a hand-off right after its ack is whole."""

    _ack_whole: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _release: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _fragments: int = PrivateAttr(default=0)

    async def after_chunk(self, chunk: AIMessageChunk) -> None:
        if not chunk.tool_call_chunks or self._release.is_set():
            return
        self._fragments += 1
        if self._fragments == _FRAGMENTS_UNTIL_ACK_WHOLE:
            self._ack_whole.set()
            await self._release.wait()


def _held_comms(script: list[Any]) -> _HeldAfterAck:
    return _HeldAfterAck(responses=scripted_model(script).responses)


async def _send(client: AsyncClient, conversation_id: str) -> None:
    sent = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"message_id": str(uuid4()), "text": ASK},
    )
    assert sent.status_code == 202, sent.text


async def _logged_reply(conversation_id: str, user_id: str) -> list[Entry]:
    """Return the log once a reply with words is in it."""
    async with asyncio.timeout(_WAIT_SECONDS):
        while True:
            shown = await replayed(conversation_id, user_id)
            if any(reply.text for reply in entries_of(shown, Reply)):
                return shown
            await asyncio.sleep(0.05)


def _shape(shown: list[Entry]) -> list[tuple[str, object]]:
    """Each entry's kind with what distinguishes it: a reply's text, a settle's outcome and answer count."""
    shape: list[tuple[str, object]] = []
    for entry in shown:
        match entry:
            case Reply(text=text):
                shape.append(("reply", text))
            case ReplySettled(outcome=outcome, answers=answers):
                shape.append(("reply_settled", (outcome, len(answers))))
            case _:
                shape.append((entry.kind, None))
    return shape


async def test_the_ack_is_logged_before_the_hand_off_finishes_and_ends_the_turn(
    open_stack: OpenStack, owner: AuthenticatedUser, client: AsyncClient
) -> None:
    conversation_id = str(uuid4())
    comms = _held_comms([call("call_executor", {"task": ASK, "ack": ACK}, "tc_exec"), NARRATED])
    async with open_stack(executor=[CLEANED, CLEANED], comms=comms) as stack:
        await _send(client, conversation_id)
        try:
            async with asyncio.timeout(_WAIT_SECONDS):
                await comms._ack_whole.wait()
            while_writing = await _logged_reply(conversation_id, owner.user_id)
        finally:
            comms._release.set()
        await drain_background_runs()

    # The model is still writing the hand-off: its call has not run, yet the ack is shown.
    assert [reply.text for reply in entries_of(while_writing, Reply)] == [ACK]
    assert entries_of(while_writing, WorkStarted) == []
    assert len(stack.comms_model.prompts) == 2, (
        "one model call for the hand-off, one for the result"
    )
    shown = await replayed(conversation_id, owner.user_id)
    [asked] = entries_of(shown, UserMessage)
    [handed] = [s for s in entries_of(shown, ReplySettled) if s.reply_id == "r1.1"]
    assert handed.answers == (asked.id,)
    assert _shape(shown) == [
        ("user_message", None),
        ("reply", ACK),
        ("work_started", None),
        ("reply_settled", (ReplyOutcome.ANSWERED, 1)),
        ("work_finished", None),
        ("reply", NARRATED),
        ("reply_settled", (ReplyOutcome.ANSWERED, 2)),
    ]


async def test_a_hand_off_that_fails_after_its_ack_goes_back_to_the_model_to_say_so(
    open_stack: OpenStack, owner: AuthenticatedUser, client: AsyncClient
) -> None:
    conversation_id = str(uuid4())
    comms = [call("call_executor", {"task": ASK, "ack": ACK}, "tc_exec"), NOT_STARTED]
    with patch.object(
        executor_tool, "_dispatch_executor", AsyncMock(side_effect=ConnectionError("redis down"))
    ):
        async with open_stack(executor=[], comms=comms) as stack:
            await _send(client, conversation_id)
            await drain_background_runs()

    shown = await replayed(conversation_id, owner.user_id)
    assert len(stack.comms_model.prompts) == 2
    failed = stack.comms_model.prompts[1][-1]
    assert "Your ack already reached the user" in str(failed.content)
    [reply] = entries_of(shown, Reply)
    assert reply.text.index(ACK) < reply.text.index(NOT_STARTED)
    assert entries_of(shown, WorkStarted) == []
    [settled] = entries_of(shown, ReplySettled)
    assert settled.outcome is ReplyOutcome.ANSWERED
