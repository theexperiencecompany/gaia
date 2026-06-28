"""Dev diagnostic: the favicon every production public integration resolves to."""

import asyncio

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.mongodb.collections import integrations_collection
from app.schemas.dev import FaviconAuditItem
from app.utils.favicon_utils import fetch_favicon_uncached, legacy_favicon_url

# Bounded concurrency so 50+ outbound favicon fetches don't starve each other
# into timeouts, which would make the audit report unstable results.
_AUDIT_CONCURRENCY = 12

# (integration_id, name, source, managed_by, server_url, stored_icon_url)
Entry = tuple[str, str, str, str, str | None, str | None]

# Self-hosted MCP servers not (yet) registered as integrations, surfaced in the
# audit so their before/after favicon resolution is visible.
_EXTRA_SERVERS: list[Entry] = [
    (
        "whoop-mcp",
        "WHOOP MCP (test)",
        "test",
        "mcp",
        "https://calm-forge-de2rt.run.mcp-use.com/mcp",
        None,
    ),
]


async def _collect_entries() -> list[Entry]:
    """Every production public integration: platform (available) + custom public."""
    entries: list[Entry] = list(_EXTRA_SERVERS)

    for integ in OAUTH_INTEGRATIONS:
        if not integ.available:
            continue
        server_url = integ.mcp_config.server_url if integ.mcp_config else None
        entries.append((integ.id, integ.name, "platform", integ.managed_by, server_url, None))

    async for doc in integrations_collection.find({"source": "custom", "is_public": True}):
        server_url = (doc.get("mcp_config") or {}).get("server_url")
        entries.append(
            (
                doc.get("integration_id", ""),
                doc.get("name", ""),
                "custom",
                doc.get("managed_by", "mcp"),
                server_url,
                doc.get("icon_url"),
            )
        )

    return entries


async def get_favicon_audit() -> list[FaviconAuditItem]:
    """Resolve the favicon for every public integration (MCP ones via the patched resolver)."""
    entries = await _collect_entries()
    semaphore = asyncio.Semaphore(_AUDIT_CONCURRENCY)

    async def resolve(server_url: str | None) -> str | None:
        if not server_url:
            return None
        async with semaphore:
            return await fetch_favicon_uncached(server_url)

    afters = await asyncio.gather(*(resolve(e[4]) for e in entries), return_exceptions=True)

    items: list[FaviconAuditItem] = []
    for entry, after in zip(entries, afters, strict=True):
        integration_id, name, source, managed_by, server_url, stored_icon_url = entry
        after_url = after if isinstance(after, str) else None
        before_url = legacy_favicon_url(server_url) if server_url else None
        items.append(
            FaviconAuditItem(
                integration_id=integration_id,
                name=name,
                source=source,
                managed_by=managed_by,
                server_url=server_url,
                stored_icon_url=stored_icon_url,
                before_url=before_url,
                after_url=after_url,
                changed=bool(server_url) and after_url != before_url,
            )
        )

    items.sort(key=lambda i: (not i.changed, i.name.lower()))
    return items
