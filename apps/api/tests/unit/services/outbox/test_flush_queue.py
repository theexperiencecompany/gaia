from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.constants.outbox import OUTBOX_JOB_QUEUE
from app.constants.outbox_attention import OUTBOX_FLUSH_TASK
from app.services.outbox.flush_queue import schedule_flush


async def test_a_flush_is_scheduled_on_the_outbox_queue_for_the_instant_it_is_due() -> None:
    at = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)
    pool = object()
    with (
        patch(
            "app.services.outbox.flush_queue.RedisPoolManager.get_pool",
            AsyncMock(return_value=pool),
        ),
        patch("app.services.outbox.flush_queue.enqueue_worker_job", AsyncMock()) as enqueue,
    ):
        await schedule_flush("user-1", at)

    enqueue.assert_awaited_once()
    assert enqueue.await_args.args == (pool, OUTBOX_FLUSH_TASK, "user-1")
    assert enqueue.await_args.kwargs["_queue_name"] == OUTBOX_JOB_QUEUE
    assert enqueue.await_args.kwargs["_defer_until"] == at
