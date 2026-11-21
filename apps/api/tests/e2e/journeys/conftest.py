"""Fixtures for the task journeys: one signed-in user on real Mongo, Redis and Postgres, and their driver."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, patch

from arq.connections import ArqRedis
from bson import ObjectId
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager
from app.api.v1.middleware.tiered_rate_limiter import TieredRateLimiter, tiered_limiter
from app.config.settings import settings
from app.db.mongodb import indexes
from app.services.workflow.scheduler import workflow_scheduler
from app.utils.redis_utils import RedisPoolManager
from tests.conftest import FAKE_USER
from tests.e2e._harness.app_events import WEBHOOK_SECRET, BotOutbox, composio_double
from tests.e2e._harness.live_stack import live_graphs, offline_todo_seams
from tests.e2e._harness.tasks_driver import TasksDriver
from tests.e2e._harness.turn_queue import TurnQueue
from tests.helpers import skip_items_without_real_services, worker_redis_url

OWNED_COLLECTIONS = (
    "tasks",
    "task_runs",
    "todos",
    "projects",
    "workflows",
    "workflow_executions",
    "playbooks",
    "conversations",
    "notifications",
    "approval_ledger",
    "waits",
    "user_integrations",
)
PLAYBOOK_RUNNER = "app.services.workflow.playbook.runner"
OUTBOUND = "app.services.outbound_delivery"
#: The modules an app connect reaches Composio from; the double answers every call.
COMPOSIO_USERS = (
    "app.services.oauth.oauth_service",
    "app.services.integrations.integration_account_lifecycle",
    "app.services.integrations.account_identity",
    "app.services.integrations.integration_connection_service",
    "app.services.triggers.base",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip every journey at collection without real Mongo, Redis and Postgres."""
    here = Path(__file__).resolve().parent
    skip_items_without_real_services(
        [item for item in items if item.path.is_relative_to(here)],
        reason="journeys need USE_REAL_SERVICES=1 (real Mongo/Redis/Postgres)",
    )


@pytest.fixture
async def _clean_user(mongo_db: AsyncIOMotorDatabase) -> AsyncIterator[None]:
    """Seed the signed-in user, with nothing of theirs left from an earlier run."""
    user_id = FAKE_USER.user_id
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})
    await mongo_db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "email": FAKE_USER.email,
                "name": FAKE_USER.name,
                "timezone": "UTC",
                "onboarding.completed": True,
                # Off unless a journey turns them on, so a nudge's time decides when it lands.
                "quiet_hours": {"enabled": False, "start_hour": 22, "end_hour": 8},
            },
            "$unset": {
                "hil_preferences": "",
                "platform_links": "",
                "platform_links_connected_at": "",
            },
        },
        upsert=True,
    )
    # The test database outlives a run: an index from an older spec would stand in for this one.
    conversations = mongo_db["conversations"]
    for spec in await conversations.list_indexes().to_list(None):
        if list(spec["key"].items()) == indexes.CONVERSATION_TODO_BINDING_KEYS:
            await conversations.drop_index(spec["name"])
    await conversations.create_index(
        indexes.CONVERSATION_TODO_BINDING_KEYS, **indexes.CONVERSATION_TODO_BINDING_OPTIONS
    )
    yield
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})


@pytest.fixture
async def _checkpointer(postgres_url: str) -> AsyncIterator[CheckpointerManager]:
    manager = await CheckpointerManager(conninfo=postgres_url, max_pool_size=4).setup()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
async def _worker_pool(redis_url: str, real_redis: object) -> AsyncIterator[ArqRedis]:
    """Install a real ArqRedis on the test's Redis as the worker pool every enqueue reaches."""
    pool = ArqRedis.from_url(worker_redis_url(redis_url))
    with (
        patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)),
        patch.object(workflow_scheduler, "arq_pool", pool),
    ):
        yield pool
    await pool.aclose()


@pytest.fixture
async def tasks(
    _clean_user: None,
    _checkpointer: CheckpointerManager,
    _worker_pool: ArqRedis,
    real_tool_registry: object,
    client: AsyncClient,
) -> AsyncIterator[TasksDriver]:
    """Yield the signed-in, subscribed user's driver, with GAIA's models scripted turn by turn."""
    executor, comms = TurnQueue(responses=[]), TurnQueue(responses=[])
    # The session fence mocks the plan limiter; a journey counts runs on the real one, on real Redis.
    real_limiter = TieredRateLimiter.check_and_increment.__get__(tiered_limiter)
    composio, outbox = composio_double(), BotOutbox()
    with ExitStack() as seams:
        seams.enter_context(offline_todo_seams())
        seams.enter_context(patch.object(tiered_limiter, "check_and_increment", real_limiter))
        seams.enter_context(patch.object(settings, "COMPOSIO_WEBHOOK_SECRET", WEBHOOK_SECRET))
        seams.enter_context(
            patch(f"{OUTBOUND}.get_rabbitmq_publisher", new=AsyncMock(return_value=outbox))
        )
        for module in COMPOSIO_USERS:
            seams.enter_context(patch(f"{module}.get_composio_service", return_value=composio))
        async with live_graphs(_checkpointer, executor_model=executor, comms_model=comms):
            driver = TasksDriver(
                client,
                user_id=FAKE_USER.user_id,
                pool=_worker_pool,
                executor=executor,
                comms=comms,
                outbox=outbox,
            )
            await driver.subscribe()
            # A playbook replay writes its result up with a structured model call of its own.
            seams.enter_context(
                patch(f"{PLAYBOOK_RUNNER}.ainvoke_structured", new=driver.narrate_replay)
            )
            yield driver
