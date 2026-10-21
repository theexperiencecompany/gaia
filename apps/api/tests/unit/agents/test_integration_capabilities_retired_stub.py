"""A retired integration's tools-only stub must not abort follow-up capabilities.

PR #876 removed browserbase from OAUTH_INTEGRATIONS but left its user_integrations
rows and a {integration_id, tools} stub in integrations; resolving it then
raised pydantic's ValidationError out of every comms turn's end-of-graph hook.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from fakeredis.aioredis import FakeRedis
from pydantic import ValidationError
import pytest

from app.agents.core.integration_capabilities import get_user_integration_capabilities
from app.config.oauth_config import get_integration_by_id
from app.constants.log_tags import LogTag
from app.models import integration_models
from app.models.integration_models import Integration
from tests.helpers import captured_wide_event

MODULE = "app.agents.core.integration_capabilities"
USER_ID = "u-1"
RETIRED_ID = "browserbase"
LIVE_ID = "github"
CACHE_KEY_GLOB = "*integration_capabilities*"

STUB_DOCUMENT: dict[str, Any] = {
    "_id": ObjectId(),
    "integration_id": RETIRED_ID,
    "tools": [{"name": "navigate", "description": "Open a page"}],
}


class _IntegrationsCollection:
    """The integrations collection, holding only the given documents."""

    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    async def find_one(
        self, filter_: dict[str, Any], *_projection: object, **_options: object
    ) -> dict[str, Any] | None:
        return next(
            (d for d in self.documents if d["integration_id"] == filter_.get("integration_id")),
            None,
        )


async def _capabilities(
    connected: list[str], documents: list[dict[str, Any]]
) -> integration_models.UserIntegrationCapabilities:
    """Run the real, cached function with only Mongo and the connected-id read doubled."""
    registry = MagicMock()
    registry.get_core_categories.return_value = []
    with ExitStack() as stack:
        stack.enter_context(patch(f"{MODULE}.get_tool_registry", AsyncMock(return_value=registry)))
        stack.enter_context(
            patch(f"{MODULE}.get_connected_integration_ids", AsyncMock(return_value=connected))
        )
        stack.enter_context(
            patch(
                "app.db.repositories.base.get_async_collection",
                return_value=_IntegrationsCollection(documents),
            )
        )
        return await get_user_integration_capabilities(USER_ID)


class TestRetiredIntegrationStub:
    def test_the_stub_shape_fails_strict_validation_as_in_prod(self) -> None:
        with pytest.raises(ValidationError) as raised:
            Integration.model_validate({k: v for k, v in STUB_DOCUMENT.items() if k != "_id"})
        assert raised.value.error_count() == 4

    @pytest.mark.regression
    async def test_one_unresolvable_integration_does_not_hide_the_rest(
        self, fake_redis: FakeRedis
    ) -> None:
        async with captured_wide_event() as event:
            result = await _capabilities([RETIRED_ID, LIVE_ID], [STUB_DOCUMENT])

        live = get_integration_by_id(LIVE_ID)
        assert live is not None
        assert result.integration_names == [live.name]
        (error,) = [e for e in event["errors"] if e.get("integration_id") == RETIRED_ID]
        assert error["user_id"] == USER_ID
        assert error["error_type"] == "ValidationError"
        assert error["msg"] == (
            f"{LogTag.INTEGRATION} Skipping unresolvable integration in follow-up capabilities"
        )
        assert "4 validation errors for Integration" in error["error"]

    @pytest.mark.regression
    async def test_a_degraded_result_is_not_cached_so_a_later_fix_is_seen(
        self, fake_redis: FakeRedis
    ) -> None:
        first = await _capabilities([RETIRED_ID], [STUB_DOCUMENT])
        assert first.degraded is True
        assert await fake_redis.keys(CACHE_KEY_GLOB) == []

        after_cleanup = await _capabilities([RETIRED_ID], [])
        assert after_cleanup.degraded is False
        assert len(await fake_redis.keys(CACHE_KEY_GLOB)) == 1

    async def test_a_clean_result_round_trips_through_the_cache(
        self, fake_redis: FakeRedis
    ) -> None:
        fresh = await _capabilities([LIVE_ID], [])
        cached = await _capabilities([], [])
        assert cached == fresh
        assert cached.integration_names != []
