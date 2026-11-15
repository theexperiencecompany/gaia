"""A per-tool approval setting saved through the settings API wins over the approval mode, in every mode."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest
from redis.asyncio import Redis

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.redis import delete_cache
from app.db.repositories.users import user_repository
from app.models.hil_models import HILMode
from app.services.hil.policy import resolve_policy
from tests.conftest import FAKE_USER
from tests.unit.services.hil.conftest import make_request, make_tool

pytestmark = [pytest.mark.integration, pytest.mark.service]

TOOL = "create_todo"


@pytest.fixture
async def owner(mongo_db: AsyncIOMotorDatabase, real_redis: Redis) -> AsyncIterator[str]:
    """Seed the signed-in user as a real users row, and remove it after."""
    owner_id = ObjectId(FAKE_USER.user_id)
    await mongo_db["users"].delete_many({"_id": owner_id})
    await mongo_db["users"].insert_one({"_id": owner_id, "email": FAKE_USER.email})
    yield FAKE_USER.user_id
    await mongo_db["users"].delete_many({"_id": owner_id})
    await delete_cache(
        user_repository.cache_policy.entity_key(REPO_GLOBAL_SCOPE, FAKE_USER.user_id)
    )


async def _save(client: AsyncClient, mode: HILMode, ask: bool) -> None:
    saved = await client.put("/api/v1/approvals/preferences", json={"mode": mode})
    assert saved.status_code == 200, saved.text
    flipped = await client.put(f"/api/v1/approvals/tools/{TOOL}", json={"ask": ask})
    assert flipped.status_code == 200, flipped.text


async def _policy(user_id: str, *, destructive: bool) -> str:
    # The catalog and classifier are the boundary: no forced-ask stamp, and the
    # classifier's opinion is the opposite of the user's setting.
    with (
        patch(
            "app.services.hil.policy.get_tool_registry",
            new=AsyncMock(return_value=SimpleNamespace(get_tool_meta=lambda name: None)),
        ),
        patch(
            "app.services.hil.policy.is_tool_destructive",
            new=AsyncMock(return_value=destructive),
        ),
    ):
        request = make_request(name=TOOL, tool=make_tool(name=TOOL))
        return await resolve_policy(request, user_id, TOOL)


@pytest.mark.parametrize("mode", ["always_allow", "always_ask", "auto"])
async def test_a_tool_set_to_always_ask_asks_whatever_the_mode(
    client: AsyncClient, owner: str, mode: HILMode
) -> None:
    await _save(client, mode, ask=True)
    assert await _policy(owner, destructive=False) == "ask"


@pytest.mark.parametrize("mode", ["always_allow", "always_ask", "auto"])
async def test_a_tool_set_to_never_ask_runs_whatever_the_mode(
    client: AsyncClient, owner: str, mode: HILMode
) -> None:
    await _save(client, mode, ask=False)
    assert await _policy(owner, destructive=True) == "allow"
