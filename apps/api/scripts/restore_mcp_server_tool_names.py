"""Rewrite stored MCP tool lists that hold master's GAIA renames back to the server's own names.

Master renamed a server tool that a GAIA tool name shadows (``execute`` became
``posthog_execute``) before storing the integration's tool list, and led the
stored description with ``MCP_RENAMED_TOOL_NOTE``, which names the original.
The stored list is now the server's, shared by every user: collision naming is
recomputed from it per user, and the HIL key ``mcp:<integration_id>:<server
name>`` (the settings toggle and migrate_hil_overrides_to_scoped_keys.py) is
built from it. A master rename there gives a key the gate never reads. Any
connect rewrites the list from the live server; this restores the ones nobody
has reconnected yet. Run it before migrate_hil_overrides_to_scoped_keys.py.

An entry is rewritten only when its description starts with the note and the
note's rename is the entry's stored name, which is exactly what master wrote.

Dry run by default: prints every rewrite. ``--apply`` first copies each affected
integration's stored tools to a timestamped backup collection, then writes
through the integrations repository.

    cd apps/api && uv run python scripts/restore_mcp_server_tool_names.py [--apply]
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.db.repositories.integrations import integration_repository
from app.models.integration_models import IntegrationToolsRecord, StoredIntegrationTool
from app.services.mcp.mcp_tools_service import invalidate_mcp_tools_cache
from app.services.mcp.tool_naming import master_rename

BACKUP_COLLECTION_PREFIX = "integrations_backup_mcp_server_tool_names_"


def restored_tools(tools: list[StoredIntegrationTool]) -> list[StoredIntegrationTool] | None:
    """Return the list with master's renames undone, or None when it holds none."""
    restored: list[StoredIntegrationTool] = []
    changed = False
    for tool in tools:
        rename = master_rename(tool)
        if rename is None:
            restored.append(tool)
            continue
        restored.append(
            StoredIntegrationTool(
                name=rename.original, description=(tool.description or "")[rename.note_end :]
            )
        )
        changed = True
    return restored if changed else None


async def _back_up(records: list[IntegrationToolsRecord]) -> None:
    backup_name = f"{BACKUP_COLLECTION_PREFIX}{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    inserted = await get_async_collection(backup_name).insert_many(
        [
            {
                "integration_id": record.integration_id,
                "tools": [tool.model_dump() for tool in record.tools],
            }
            for record in records
        ]
    )
    if len(inserted.inserted_ids) != len(records):
        raise SystemExit(
            f"backup wrote {len(inserted.inserted_ids)} of {len(records)} tool lists to "
            f"{backup_name}; nothing was rewritten"
        )
    print(f"backed up {len(records)} tool lists to {backup_name}")


async def restore(*, apply: bool) -> None:
    records = await integration_repository.all_with_tools()
    planned: list[tuple[IntegrationToolsRecord, list[StoredIntegrationTool]]] = []
    for record in records:
        restored = restored_tools(record.tools)
        if restored is None:
            continue
        planned.append((record, restored))
        for before, after in zip(record.tools, restored, strict=True):
            if before.name != after.name:
                print(f"  REWRITE {record.integration_id}: {before.name} -> {after.name}")

    print(f"integrations with stored tools: {len(records)}, to rewrite: {len(planned)}")
    if not apply:
        print("dry run: pass --apply to back up and rewrite")
        return
    if not planned:
        return

    await _back_up([record for record, _ in planned])
    for record, restored in planned:
        await integration_repository.store_tools(record.integration_id, restored)
    await invalidate_mcp_tools_cache()
    print(f"rewrote {len(planned)} tool lists")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Back up and rewrite (otherwise dry run only)."
    )
    asyncio.run(restore(apply=parser.parse_args().apply))


if __name__ == "__main__":
    main()
