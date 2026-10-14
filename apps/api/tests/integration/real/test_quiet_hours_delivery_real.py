"""A proactive message sent inside the user's quiet hours reaches them when the window ends.

Drives the real chokepoint, the real ARQ enqueue and a real ARQ worker over a
real Redis. The user read and the bot transport are stubbed: what is proven is
the hold and the release, not the Telegram send itself.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from arq.connections import ArqRedis
from arq.constants import default_queue_name, job_key_prefix
from arq.worker import Function, Worker
import pytest
import time_machine

from app.agents.core.background import platform_chat
from app.constants.notifications import DEFERRED_CHAT_MESSAGE_TASK, ProactiveMessageClass
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import QuietHours
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.worker import WorkerSettings
from tests.helpers import worker_redis_url

# 23:30 in Kolkata (UTC+5:30), inside a 22-8 window that ends at 08:00 IST = 02:30 UTC.
SENT_AT = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 15, 2, 30, tzinfo=UTC)
OWNER = UserDocument(
    id="6812f0b3c9a14e2b7d5a91cc",
    email="owner@gaia.local",
    timezone="Asia/Kolkata",
    quiet_hours=QuietHours(start_hour=22, end_hour=8),
)
CHANNEL = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-7")


def _registered(name: str) -> Function:
    """Return the task exactly as the production worker registers it, envelope included."""
    (function,) = [
        f for f in WorkerSettings.functions if isinstance(f, Function) and f.name == name
    ]
    return function


@pytest.fixture
async def arq_pool(redis_url: str) -> AsyncIterator[ArqRedis]:
    """Yield an ARQ pool on this worker's own flushable Redis DB."""
    pool = ArqRedis.from_url(worker_redis_url(redis_url))
    await pool.flushdb()
    yield pool
    await pool.flushdb()
    await pool.aclose()


@pytest.mark.service
async def test_a_message_held_overnight_is_posted_when_the_window_ends(arq_pool: ArqRedis) -> None:
    publish = AsyncMock(return_value=OutboundResult.PUBLISHED)
    with (
        patch.object(platform_chat.user_repository, "get", AsyncMock(return_value=OWNER)),
        patch.object(platform_chat.RedisPoolManager, "get_pool", AsyncMock(return_value=arq_pool)),
        patch.object(
            platform_chat.BotService, "get_or_create_session", AsyncMock(return_value="dm-conv")
        ),
        patch.object(platform_chat, "update_messages", AsyncMock()),
        patch.object(platform_chat, "publish_outbound_message", publish),
        patch.object(platform_chat, "record_platform_delivery", AsyncMock()),
    ):
        with time_machine.travel(SENT_AT, tick=False):
            held = await platform_chat.post_to_platform_chat(
                user=AuthenticatedUser(user_id=OWNER.id),
                channel=CHANNEL,
                text="Your digest is ready.",
                origin="result of workflow digest",
                message_class=ProactiveMessageClass.ROUTINE,
            )

        assert held is OutboundResult.DEFERRED
        publish.assert_not_awaited()
        (job_id,) = [
            key.decode().removeprefix(job_key_prefix)
            for key in await arq_pool.keys(f"{job_key_prefix}*")
        ]
        score_ms = await arq_pool.zscore(default_queue_name, job_id)
        assert score_ms == WINDOW_END.timestamp() * 1000

        with time_machine.travel(WINDOW_END + timedelta(seconds=1), tick=False):
            worker = Worker(
                functions=[_registered(DEFERRED_CHAT_MESSAGE_TASK)],
                redis_pool=arq_pool,
                burst=True,
                poll_delay=0,
                handle_signals=False,
            )
            await worker.main()

    assert worker.jobs_complete == 1
    assert worker.jobs_failed == 0
    publish.assert_awaited_once()
    assert publish.await_args.args == (
        ConversationSource.TELEGRAM,
        OWNER.id,
        ["Your digest is ready."],
    )
