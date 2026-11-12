"""A step-dispatched executor's live cards as work_delta frames on its conversation's stream.

Each frame's index comes from one Redis counter per task, so a run resumed in another
process after an approval continues the indices a client already applied.
"""

import asyncio
from collections.abc import Callable

from app.constants.conversation import EVENTS_STREAM_TTL_SECONDS, WORK_DELTA_INDEX_KEY_PREFIX
from app.db.redis import redis_cache
from app.models.conversation_frame_models import StreamPayload, StreamPayloadType, WorkDeltaFrame
from app.services.conversation.comms_events import payloads_from_event
from app.services.conversation.runtime import runtime_ports
from app.utils.background_tasks import spawn_background_task

#: What a client shows of running work; its words and reasoning reach the user through the reply.
_WORK_PAYLOADS = frozenset(
    {
        StreamPayloadType.TOOL_DATA,
        StreamPayloadType.TOOL_OUTPUT,
        StreamPayloadType.SUBAGENT_START,
        StreamPayloadType.SUBAGENT_END,
        StreamPayloadType.TODO_PROGRESS,
    }
)
_PUBLISH_TASK_NAME = "work-delta-publish"


class WorkDeltas:
    """A sync stream writer that publishes one task's cards in the order they were written."""

    def __init__(self, conversation_id: str, task_id: str) -> None:
        self._conversation_id = conversation_id
        self._task_id = task_id
        self._last: asyncio.Task[None] | None = None

    def __call__(self, data: dict[str, object]) -> None:
        """Queue the event's cards behind every earlier write."""
        payloads = [p for p in payloads_from_event(data) if p.type in _WORK_PAYLOADS]
        if not payloads:
            return
        self._last = spawn_background_task(
            self._publish(self._last, payloads), name=_PUBLISH_TASK_NAME
        )

    def wrap(
        self, writer: Callable[[dict[str, object]], None]
    ) -> Callable[[dict[str, object]], None]:
        """Return writer that also publishes each event's cards."""

        def publishing(data: dict[str, object]) -> None:
            writer(data)
            self(data)

        return publishing

    async def drain(self) -> None:
        """Wait until every write so far was published; a failed one was already logged as its task's failure."""
        if self._last is not None:
            await asyncio.wait([self._last])

    async def _publish(
        self, previous: asyncio.Task[None] | None, payloads: list[StreamPayload]
    ) -> None:
        if previous is not None:
            # Order, not success: one failed publish must not hold back the cards after it.
            await asyncio.wait([previous])
        key = f"{WORK_DELTA_INDEX_KEY_PREFIX}{self._conversation_id}:{self._task_id}"
        frames = runtime_ports().frames
        for payload in payloads:
            index = await redis_cache.client.incr(key) - 1
            await redis_cache.client.expire(key, EVENTS_STREAM_TTL_SECONDS)
            frame = WorkDeltaFrame(task_id=self._task_id, index=index, payload=payload)
            await frames.publish(self._conversation_id, frame)
