"""A retired integration's tools-only stub must not cost a user every tool namespace.

The stub fails strict Integration validation when resolved. These tests run the real
cached function, resolver and repository, faking only Mongo and the connection status.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from fakeredis.aioredis import FakeRedis
import pytest

from app.agents.tools.core.retrieval import _get_user_context
from app.constants.log_tags import LogTag
from app.models import integration_models
from app.services.integrations.integration_service import get_user_available_tool_namespaces
from tests.helpers import captured_wide_event

SERVICE = "app.services.integrations.integration_service"
USER_ID = "u-1"
RETIRED_ID = "browserbase"
CUSTOM_ID = "my-custom-mcp"
CACHE_KEY_GLOB = "tool_namespaces:*"

STUB: dict[str, Any] = {
    "_id": ObjectId(),
    "integration_id": RETIRED_ID,
    "tools": [{"name": "navigate"}],
}
CUSTOM: dict[str, Any] = {
    "_id": ObjectId(),
    "integration_id": CUSTOM_ID,
    "name": "Custom",
    "description": "d",
    "category": "developer",
    "managed_by": "mcp",
    "mcp_config": {"server_url": "https://example.com/mcp", "requires_auth": False},
}


class _Integrations:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    async def find_one(self, filter_: dict[str, Any], *_a: object, **_k: object) -> Any:
        wanted = filter_.get("integration_id")
        return next((d for d in self.documents if d["integration_id"] == wanted), None)


async def _namespaces(
    connected: list[str], documents: list[dict[str, Any]]
) -> integration_models.UserToolNamespaces:
    status = dict.fromkeys(connected, True)
    with (
        patch(f"{SERVICE}.get_all_integrations_status", AsyncMock(return_value=status)),
        patch(
            "app.db.repositories.base.get_async_collection",
            return_value=_Integrations(documents),
        ),
    ):
        return await get_user_available_tool_namespaces(USER_ID)


class TestToolNamespacesWithRetiredStub:
    @pytest.mark.regression
    async def test_a_good_integration_still_contributes_when_another_is_unresolvable(
        self, fake_redis: FakeRedis
    ) -> None:
        async with captured_wide_event() as event:
            result = await _namespaces([RETIRED_ID, CUSTOM_ID], [STUB, CUSTOM])

        assert any("example" in ns or CUSTOM_ID in ns for ns in result.namespaces)
        assert {"general", "subagents"} <= result.namespaces
        assert result.degraded is True
        (error,) = [e for e in event["errors"] if e.get("integration_id") == RETIRED_ID]
        assert error["user_id"] == USER_ID
        assert error["error_type"] == "ValidationError"
        assert error["msg"] == (
            f"{LogTag.INTEGRATION} Skipping unresolvable integration in tool namespaces"
        )
        assert "4 validation errors for Integration" in error["error"]

    @pytest.mark.regression
    async def test_a_degraded_result_is_not_cached_so_a_later_fix_is_seen(
        self, fake_redis: FakeRedis
    ) -> None:
        first = await _namespaces([RETIRED_ID], [STUB])
        assert first.degraded is True
        assert await fake_redis.keys(CACHE_KEY_GLOB) == []

        after_cleanup = await _namespaces([RETIRED_ID], [])
        assert after_cleanup.degraded is False
        assert len(await fake_redis.keys(CACHE_KEY_GLOB)) == 1

    @pytest.mark.regression
    async def test_executor_tool_retrieval_keeps_the_good_namespaces(
        self, fake_redis: FakeRedis
    ) -> None:
        with (
            patch(
                f"{SERVICE}.get_all_integrations_status",
                AsyncMock(return_value={RETIRED_ID: True, CUSTOM_ID: True}),
            ),
            patch(
                "app.db.repositories.base.get_async_collection",
                return_value=_Integrations([STUB, CUSTOM]),
            ),
        ):
            namespaces, _ = await _get_user_context(USER_ID, "general", include_subagents=False)

        assert {"general", "subagents"} <= namespaces
        assert len(namespaces) > 2
