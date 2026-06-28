"""
One-time, idempotent migration: re-resolve `icon_url` on custom integrations.

Custom MCP integrations store the favicon resolved at creation time. The resolver
was upgraded to resolve per host (Smithery registry icon -> host <link rel=icon>
-> Google S2), so integrations created before the upgrade keep a stale icon (e.g.
every Smithery server stored Smithery's generic grid). This re-resolves each
custom integration that has an MCP server URL and updates `icon_url` when it
changed.

Only documents whose resolved icon differs from what's stored are written, so the
script is safe to run multiple times.

Run from repo root:
    cd apps/api && uv run python scripts/backfill_integration_favicons.py
"""

import asyncio
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import integrations_collection  # noqa: E402
from app.utils.favicon_utils import fetch_favicon_uncached, legacy_favicon_url  # noqa: E402


async def backfill() -> None:
    """Re-resolve and update icon_url for custom MCP integrations."""
    query = {"source": "custom", "mcp_config.server_url": {"$exists": True}}
    total = await integrations_collection.count_documents(query)
    if total == 0:
        print("No custom MCP integrations found. Nothing to backfill.")
        return

    print(f"Re-resolving favicons for {total} custom MCP integration(s)...")

    updated = 0
    unchanged = 0
    skipped_generic = 0
    failed = 0

    async for doc in integrations_collection.find(query):
        integration_id = doc.get("integration_id", "")
        name = doc.get("name", "")
        server_url = (doc.get("mcp_config") or {}).get("server_url")
        if not server_url:
            continue

        try:
            new_icon = await fetch_favicon_uncached(server_url)
        except Exception as e:
            print(f"  FAILED {name}: {e}")
            failed += 1
            continue

        # Only apply a *specific* icon (Smithery registry / host <link> / CDN logo).
        # If resolution fell back to the generic Google-S2 favicon, leave the stored
        # value alone — it may be a better, manually-curated icon and we never want
        # to regress one to a generic placeholder.
        if not new_icon or new_icon == legacy_favicon_url(server_url):
            skipped_generic += 1
            continue

        if new_icon == doc.get("icon_url"):
            unchanged += 1
            continue

        await integrations_collection.update_one(
            {"integration_id": integration_id},
            {"$set": {"icon_url": new_icon}},
        )
        print(f"  {name}: {doc.get('icon_url')} -> {new_icon}")
        updated += 1

    print(
        f"\nBackfill complete. Updated: {updated}, Unchanged: {unchanged}, "
        f"Skipped (generic fallback): {skipped_generic}, Failed: {failed}"
    )


if __name__ == "__main__":
    asyncio.run(backfill())
