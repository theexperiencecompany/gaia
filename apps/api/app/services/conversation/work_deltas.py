"""A step-dispatched executor's live cards: one durable record per task, and work_delta frames announcing each.

The record is a Redis list per task, so its index is the list position and a run resumed in
another process after an approval continues the record a client already saw. Live work items,
reloads and the finished work's cards all fold the same record.
"""

import asyncio
from collections.abc import Callable, Sequence

from pydantic import TypeAdapter

from app.constants.conversation import WORK_DELTAS_KEY_PREFIX, WORK_DELTAS_TTL_SECONDS
from app.db.redis import redis_cache
from app.models.conversation_frame_models import (
    ReasoningEvent,
    StreamPayload,
    StreamPayloadType,
    WorkDeltaFrame,
)
from app.services.conversation.graph_payloads import payloads_of_custom
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.tool_cards import FoldedCards, fold_cards
from app.utils.background_tasks import spawn_background_task

#: What a client shows of running work; its words reach the user through the reply.
_WORK_PAYLOADS = frozenset(
    {
        StreamPayloadType.TOOL_DATA,
        StreamPayloadType.TOOL_OUTPUT,
        StreamPayloadType.REASONING,
        StreamPayloadType.SUBAGENT_START,
        StreamPayloadType.SUBAGENT_END,
        StreamPayloadType.TODO_PROGRESS,
        StreamPayloadType.IMAGE_DATA,
    }
)
_PUBLISH_TASK_NAME = "work-delta-publish"
_PAYLOAD: TypeAdapter[StreamPayload] = TypeAdapter(StreamPayload)


def _key(conversation_id: str, task_id: str) -> str:
    return f"{WORK_DELTAS_KEY_PREFIX}{conversation_id}:{task_id}"


async def work_payloads(conversation_id: str, task_id: str) -> list[StreamPayload]:
    """Return every payload the task's work published, in order."""
    raw = await redis_cache.client.lrange(_key(conversation_id, task_id), 0, -1)
    return [_PAYLOAD.validate_json(payload) for payload in raw]


async def work_cards(conversation_id: str, task_ids: Sequence[str]) -> FoldedCards:
    """Return the cards and image the tasks' work published, folded in task order."""
    payloads = [
        payload for task_id in task_ids for payload in await work_payloads(conversation_id, task_id)
    ]
    return fold_cards(payloads)


class WorkDeltas:
    """A sync stream writer that records one task's cards and announces them, in the order they were written."""

    def __init__(self, conversation_id: str, task_id: str) -> None:
        self._conversation_id = conversation_id
        self._task_id = task_id
        self._last: asyncio.Task[None] | None = None
        # Thinking streams a token at a time; one contiguous block is recorded as one payload.
        self._thinking: ReasoningEvent | None = None

    def __call__(self, data: dict[str, object]) -> None:
        """Queue the event's cards behind every earlier write; thinking is held until its block ends."""
        payloads: list[StreamPayload] = []
        for payload in payloads_of_custom(data):
            if payload.type not in _WORK_PAYLOADS:
                continue
            if isinstance(payload, ReasoningEvent):
                payloads.extend(self._think(payload))
            else:
                payloads.extend((*self._end_thinking(), payload))
        self._queue(payloads)

    def _think(self, payload: ReasoningEvent) -> list[StreamPayload]:
        """Merge thinking into the open block; a block from another subagent ends it first."""
        held = self._thinking
        if held is not None and held.reasoning.subagent_id == payload.reasoning.subagent_id:
            merged = held.reasoning.content + payload.reasoning.content
            self._thinking = ReasoningEvent(
                reasoning=held.reasoning.model_copy(update={"content": merged})
            )
            return []
        ended = self._end_thinking()
        self._thinking = payload
        return ended

    def _end_thinking(self) -> list[StreamPayload]:
        held, self._thinking = self._thinking, None
        return [] if held is None else [held]

    def _queue(self, payloads: list[StreamPayload]) -> None:
        if payloads:
            self._last = spawn_background_task(
                self._publish(self._last, payloads), name=_PUBLISH_TASK_NAME
            )

    def wrap(
        self, writer: Callable[[dict[str, object]], None]
    ) -> Callable[[dict[str, object]], None]:
        """Return writer that also records each event's cards."""

        def publishing(data: dict[str, object]) -> None:
            writer(data)
            self(data)

        return publishing

    async def drain(self) -> None:
        """Record the open thinking block, then wait until every write so far was recorded.

        A failed write was already logged as its task's failure.
        """
        self._queue(self._end_thinking())
        if self._last is not None:
            await asyncio.wait([self._last])

    async def _publish(
        self, previous: asyncio.Task[None] | None, payloads: list[StreamPayload]
    ) -> None:
        if previous is not None:
            # Order, not success: one failed publish must not hold back the cards after it.
            await asyncio.wait([previous])
        key = _key(self._conversation_id, self._task_id)
        announced: list[WorkDeltaFrame] = []
        for payload in payloads:
            index = await redis_cache.client.rpush(key, payload.model_dump_json()) - 1
            announced.append(WorkDeltaFrame(task_id=self._task_id, index=index, payload=payload))
        await redis_cache.client.expire(key, WORK_DELTAS_TTL_SECONDS)
        # Recorded first: the record is what every screen folds; the frames only announce it.
        await runtime_ports().frames.publish(self._conversation_id, *announced)
