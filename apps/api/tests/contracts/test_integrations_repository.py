"""Contract tests for IntegrationsRepository (global, keyed by integration_id)."""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.integrations import IntegrationsRepository
from app.models.integration_models import Integration
from app.models.mcp_config import MCPConfig


@pytest.fixture
def repo(raw_collection) -> IntegrationsRepository:
    return IntegrationsRepository()


def _integration(integration_id: str, name: str, **overrides: object) -> Integration:
    data: dict[str, object] = {
        "integration_id": integration_id,
        "name": name,
        "description": "desc",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "mcp_config": MCPConfig(server_url="https://mcp.example.com", requires_auth=False),
    }
    data.update(overrides)
    return Integration.model_validate(data)


class TestIntegrationsRepository:
    async def test_create_and_get_by_integration_id(self, repo):
        iid = f"int-{uuid.uuid4().hex}"
        created = await repo.create(_integration(iid, "Notion"))
        # _id is incidental; identity is integration_id, so the model id stays empty.
        assert created.id == ""
        assert created.integration_id == iid

        got = await repo.get(iid)
        assert got is not None
        assert got.name == "Notion"
        assert got.mcp_config is not None
        assert got.mcp_config.server_url == "https://mcp.example.com"

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get(f"absent-{uuid.uuid4().hex}") is None

    async def test_find_by_id_prefix_case_insensitive(self, repo):
        iid = f"AbC-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "Prefixed"))
        found = await repo.find_by_id_prefix(iid[:5].lower())
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_matches_id_prefix(self, repo):
        iid = f"pref-{uuid.uuid4().hex}"
        await repo.create(_integration(iid, "SomeName"))
        found = await repo.find_by_id_prefix_or_name(iid[:6])
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_matches_exact_name(self, repo):
        iid = f"byname-{uuid.uuid4().hex}"
        unique_name = f"Exact {uuid.uuid4().hex}"
        await repo.create(_integration(iid, unique_name))
        found = await repo.find_by_id_prefix_or_name(unique_name)
        assert found is not None and found.integration_id == iid

    async def test_find_by_id_prefix_or_name_no_match(self, repo):
        await repo.create(_integration(f"x-{uuid.uuid4().hex}", "Nope"))
        assert await repo.find_by_id_prefix_or_name(f"missing-{uuid.uuid4().hex}") is None
