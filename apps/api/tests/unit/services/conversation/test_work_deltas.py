"""WorkDeltas: a running task's cards are recorded in order, then announced as work_delta frames."""

import asyncio
from unittest.mock import MagicMock

import fakeredis.aioredis
import pytest

from app.constants.conversation import WORK_DELTAS_TTL_SECONDS
from app.models.conversation_frame_models import (
    OutputFrame,
    ReasoningEvent,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.stream_events import ReasoningPayload
from app.services.conversation import work_deltas
from app.services.conversation.work_deltas import WorkDeltas, work_payloads
from shared.py.conversation_wire import ToolDataEntry

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

CONVERSATION = "conv-work"
TASK = "t1"


def _card(name: str) -> ToolDataEntry:
    return {"tool_name": "search", "data": {"q": name}}


class _Announced:
    """The frames port: every publish, with the conversation and the task it ran in."""

    def __init__(self) -> None:
        self.published: list[tuple[str, tuple[OutputFrame, ...], str]] = []

    async def publish(self, conversation_id: str, *frames: OutputFrame) -> None:
        task = asyncio.current_task()
        name = task.get_name() if task is not None else ""
        self.published.append((conversation_id, frames, name))


@pytest.fixture
def announced(monkeypatch: pytest.MonkeyPatch) -> _Announced:
    frames = _Announced()
    monkeypatch.setattr(work_deltas, "runtime_ports", lambda: MagicMock(frames=frames))
    return frames


async def test_cards_are_recorded_in_write_order_and_announced_at_their_index(
    announced: _Announced, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    deltas = WorkDeltas(CONVERSATION, TASK)
    deltas({"tool_data": [_card("a"), _card("b")]})
    deltas({"response": "words reach the user through the reply"})
    deltas({"tool_data": _card("c")})
    await deltas.drain()

    cards = [ToolDataEvent(tool_data=_card(name)) for name in ("a", "b", "c")]
    assert await work_payloads(CONVERSATION, TASK) == cards
    assert announced.published == [
        (
            CONVERSATION,
            (
                WorkDeltaFrame(task_id=TASK, index=0, payload=cards[0]),
                WorkDeltaFrame(task_id=TASK, index=1, payload=cards[1]),
            ),
            "work-delta-publish",
        ),
        (
            CONVERSATION,
            (WorkDeltaFrame(task_id=TASK, index=2, payload=cards[2]),),
            "work-delta-publish",
        ),
    ]
    ttl = await fake_redis.ttl(f"conv:work_deltas:{CONVERSATION}:{TASK}")
    assert WORK_DELTAS_TTL_SECONDS - 5 < ttl <= WORK_DELTAS_TTL_SECONDS


async def test_one_thinking_block_is_recorded_whole_once_it_ends(announced: _Announced) -> None:
    deltas = WorkDeltas(CONVERSATION, TASK)
    deltas({"reasoning": {"content": "think"}})
    deltas({"reasoning": {"content": "ing"}})
    assert await work_payloads(CONVERSATION, TASK) == []
    await deltas.drain()

    thought = ReasoningEvent(reasoning=ReasoningPayload(content="thinking"))
    assert await work_payloads(CONVERSATION, TASK) == [thought]


async def test_a_card_ends_the_open_thinking_block_before_it(announced: _Announced) -> None:
    deltas = WorkDeltas(CONVERSATION, TASK)
    deltas({"reasoning": {"content": "plan"}})
    deltas({"tool_data": _card("a")})
    await deltas.drain()

    assert await work_payloads(CONVERSATION, TASK) == [
        ReasoningEvent(reasoning=ReasoningPayload(content="plan")),
        ToolDataEvent(tool_data=_card("a")),
    ]
