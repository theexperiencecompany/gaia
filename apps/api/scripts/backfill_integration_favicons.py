"""
One-time, idempotent migration: re-resolve `icon_url` on custom integrations.

Custom MCP integrations store the favicon resolved at creation time. The resolver
was upgraded to resolve per host (Smithery registry icon -> host <link rel=icon>
-> Google S2), so integrations created before the upgrade keep a stale icon (e.g.
every Smithery server stored Smithery's generic grid). This re-resolves each
custom integration that has an MCP server URL and updates `icon_url` when it
resolves to a specific icon.

Only documents whose resolved icon differs from what's stored are written, and a
generic Google-S2 fallback never overwrites a stored (possibly curated) icon, so
the script is safe to run multiple times.

Run from apps/api:
    uv run python -m scripts.backfill_integration_favicons
"""

import asyncio

from app.db.mongodb.collections import integrations_collection
from app.utils.favicon_utils import fetch_favicon_uncached, legacy_favicon_url


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
            {"_id": doc["_id"]},
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
