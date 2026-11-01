"""The custom MCP pointer backfill: dry run writes nothing, --apply backs up and re-indexes the stale.

The store is a real InMemoryStore; Mongo is the seam, faked per collection.
"""

from collections.abc import AsyncIterator, Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langgraph.store.memory import InMemoryStore
import pytest

from app.services.mcp.custom_mcp_index import SUBAGENTS_NAMESPACE
from scripts import backfill_custom_mcp_pointer_namespaces as backfill_script

pytestmark = pytest.mark.unit

_LEGACY_ID = "aaa111aaa111"
_CURRENT_ID = "bbb222bbb222"
_UNCONNECTED_ID = "ccc333ccc333"


def _custom(integration_id: str, host: str) -> dict[str, object]:
    return {
        "integration_id": integration_id,
        "name": f"MCP {integration_id}",
        "description": "Lists invoices",
        "category": "custom",
        "managed_by": "mcp",
        "source": "custom",
        "created_by": "u1",
        "mcp_config": {"server_url": f"https://{host}/v1", "requires_auth": False},
        "tools": [{"name": "list_invoices", "description": "List invoices\nmore"}],
    }


class _Collection:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self.docs = docs
        self.insert_many = AsyncMock(
            side_effect=lambda rows: SimpleNamespace(inserted_ids=list(range(len(rows))))
        )

    async def _iterate(self) -> AsyncIterator[dict[str, object]]:
        for doc in self.docs:
            yield doc

    def find(self, filter_: Mapping[str, object]) -> AsyncIterator[dict[str, object]]:
        assert filter_ == {"source": "custom"}
        return self._iterate()


async def _seeded_store() -> InMemoryStore:
    store = InMemoryStore()
    await store.aput(
        SUBAGENTS_NAMESPACE, _LEGACY_ID, {"id": _LEGACY_ID, "name": "old", "source": "custom"}
    )
    await store.aput(
        SUBAGENTS_NAMESPACE,
        _CURRENT_ID,
        {"id": _CURRENT_ID, "name": "kept", "source": "custom", "tool_namespace": "beta.dev/v1"},
    )
    return store


async def _run(apply: bool) -> tuple[InMemoryStore, _Collection, _Collection]:
    store = await _seeded_store()
    integrations = _Collection(
        [
            _custom(_LEGACY_ID, "alpha.dev"),
            _custom(_CURRENT_ID, "beta.dev"),
            _custom(_UNCONNECTED_ID, "gamma.dev"),
        ]
    )
    backup = _Collection([])

    def collection(name: str) -> _Collection:
        return integrations if name == backfill_script.INTEGRATIONS_COLLECTION else backup

    with (
        patch.object(backfill_script, "_tools_store", new=AsyncMock(return_value=store)),
        patch.object(backfill_script, "get_async_collection", side_effect=collection),
    ):
        stale = await backfill_script.backfill(apply=apply)
    assert [entry.integration.integration_id for entry in stale] == [_LEGACY_ID]
    return store, integrations, backup


class TestBackfillCustomMcpPointerNamespaces:
    async def test_a_dry_run_writes_nothing(self) -> None:
        store, _, backup = await _run(apply=False)

        legacy = await store.aget(SUBAGENTS_NAMESPACE, _LEGACY_ID)
        assert legacy is not None and "tool_namespace" not in legacy.value
        backup.insert_many.assert_not_awaited()

    async def test_apply_backs_up_then_reindexes_only_the_stale_pointer(self) -> None:
        store, _, backup = await _run(apply=True)

        backup.insert_many.assert_awaited_once_with(
            [
                {
                    "namespace": ["subagents"],
                    "key": _LEGACY_ID,
                    "value": {"id": _LEGACY_ID, "name": "old", "source": "custom"},
                }
            ]
        )
        legacy = await store.aget(SUBAGENTS_NAMESPACE, _LEGACY_ID)
        assert legacy is not None
        assert legacy.value["tool_namespace"] == "alpha.dev/v1"
        assert legacy.value["name"] == f"MCP {_LEGACY_ID}"
        assert "list_invoices: List invoices" in str(legacy.value["description"])
        current = await store.aget(SUBAGENTS_NAMESPACE, _CURRENT_ID)
        assert current is not None and current.value["name"] == "kept"
        assert await store.aget(SUBAGENTS_NAMESPACE, _UNCONNECTED_ID) is None
