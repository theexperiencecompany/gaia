"""Re-index every custom MCP discovery pointer so it carries its ``tool_namespace``.

``retrieve_tools`` shows a custom MCP's ``("subagents",)`` pointer only to a user
whose entitled namespaces include the pointer's ``tool_namespace``, and drops a
custom pointer without one. Pointers written before the field existed are
therefore invisible to everyone, their owner included, until re-indexed.

For every custom integration with a pointer doc whose ``tool_namespace`` is
missing or no longer matches its server URL, re-indexes it through
``index_custom_mcp_as_subagent`` with the integration's stored name,
description and tools. A custom integration with no pointer doc was never
connected and is left alone; connecting it writes one.

Dry run by default: prints the counts and every pointer it would rewrite.
``--apply`` first copies each pointer doc it will rewrite to a timestamped Mongo
backup collection, then re-indexes.

    cd apps/api && uv run python scripts/backfill_custom_mcp_pointer_namespaces.py [--apply]
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import cast

sys.path.insert(0, str(Path(__file__).parent.parent))

from langgraph.store.base import BaseStore, Item
from pydantic import ValidationError

from app.core.lazy_loader import providers
from app.core.provider_registration import register_lazy_providers
from app.db.mongodb.collections import get_async_collection
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.integration_models import Integration
from app.services.mcp.custom_mcp_index import (
    SUBAGENTS_NAMESPACE,
    CustomMcpIndexRequest,
    index_custom_mcp_as_subagent,
)

INTEGRATIONS_COLLECTION = "integrations"
BACKUP_COLLECTION_PREFIX = "custom_mcp_pointers_backup_namespace_"


@dataclass(frozen=True)
class StalePointer:
    """A custom integration whose stored pointer doc lacks the namespace it should carry."""

    integration: Integration
    server_url: str | None
    expected_namespace: str
    pointer: Item


async def _tools_store() -> BaseStore:
    store = await providers.aget("chroma_tools_store")
    if store is None:
        raise SystemExit("chroma_tools_store is unavailable; nothing was read or written")
    return cast(BaseStore, store)


async def find_stale_pointers(store: BaseStore) -> list[StalePointer]:
    """Every custom integration whose pointer doc needs re-indexing, printing the tally."""
    integrations = get_async_collection(INTEGRATIONS_COLLECTION)
    stale: list[StalePointer] = []
    total = without_pointer = current = 0
    async for doc in integrations.find({"source": "custom"}):
        total += 1
        try:
            integration = Integration.model_validate(doc)
        except ValidationError as error:
            raise SystemExit(
                f"custom integration {doc.get('integration_id')} does not validate, nothing "
                f"was written:\n{error}"
            ) from error
        pointer = await store.aget(SUBAGENTS_NAMESPACE, integration.integration_id)
        if pointer is None:
            without_pointer += 1
            continue
        server_url = integration.mcp_config.server_url if integration.mcp_config else None
        expected = derive_integration_namespace(
            integration.integration_id, server_url, is_custom=True
        )
        if pointer.value.get("tool_namespace") == expected:
            current += 1
            continue
        stale.append(StalePointer(integration, server_url, expected, pointer))

    print(
        f"custom integrations: {total}, without a pointer: {without_pointer}, "
        f"already current: {current}, to re-index: {len(stale)}"
    )
    for entry in stale:
        print(
            f"  {entry.integration.integration_id}  tool_namespace "
            f"{entry.pointer.value.get('tool_namespace')!r} -> {entry.expected_namespace!r}"
        )
    return stale


async def _back_up(stale: list[StalePointer]) -> None:
    backup_name = f"{BACKUP_COLLECTION_PREFIX}{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    backup = get_async_collection(backup_name)
    inserted = await backup.insert_many(
        [
            {
                "namespace": list(entry.pointer.namespace),
                "key": entry.pointer.key,
                "value": entry.pointer.value,
            }
            for entry in stale
        ]
    )
    if len(inserted.inserted_ids) != len(stale):
        raise SystemExit(
            f"backup wrote {len(inserted.inserted_ids)} of {len(stale)} pointer docs to "
            f"{backup_name}; nothing was re-indexed"
        )
    print(f"backed up {len(stale)} pointer docs to {backup_name}")


async def backfill(*, apply: bool) -> list[StalePointer]:
    """Find the stale pointers and, when apply is set, back them up and re-index them."""
    store = await _tools_store()
    stale = await find_stale_pointers(store)
    if not apply:
        print("dry run: pass --apply to back up and re-index")
        return stale
    if not stale:
        return stale

    await _back_up(stale)
    for entry in stale:
        integration = entry.integration
        await index_custom_mcp_as_subagent(
            store,
            CustomMcpIndexRequest(
                integration_id=integration.integration_id,
                name=integration.name,
                description=integration.description,
                server_url=entry.server_url,
                tools=integration.tools,
            ),
        )
    print(f"re-indexed {len(stale)} pointer docs")
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Back up and re-index (otherwise dry run only)."
    )
    # A script has no lifespan, so nobody registers the lazy Chroma/embedding providers otherwise.
    register_lazy_providers("main_app")
    asyncio.run(backfill(apply=parser.parse_args().apply))


if __name__ == "__main__":
    main()
