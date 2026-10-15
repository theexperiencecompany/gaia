"""Composio's toolkit catalog as the instance admin browses it.

The whole catalog (~1.6k toolkits, two Composio pages) is cached in Redis and
searched here, so typing in the browser costs no Composio round trip.
"""

from collections.abc import Sequence

import composio_client
from composio_client.types.toolkit_list_response import Item as ToolkitListItem

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.cache import COMPOSIO_TOOLKIT_CATALOG_KEY, COMPOSIO_TOOLKIT_CATALOG_TTL
from app.decorators.caching import Cacheable
from app.schemas.integrations.composio_setup import (
    ComposioCatalogEntry,
    ComposioCatalogResponse,
    ComposioToolkit,
    ComposioToolkitStatus,
)
from app.services.composio.auth_config_resolver import resolve_auth_configs
from app.services.composio.auth_config_setup import composio_key_rejected
from app.services.composio.composio_service import get_composio_service
from app.services.composio.instance_toolkits import stored_toolkits
from shared.py.wide_events import log


def _summary(item: ToolkitListItem) -> ComposioToolkit:
    return ComposioToolkit(
        slug=item.slug.lower(),
        name=item.name,
        description=item.meta.description,
        logo=item.meta.logo or None,
        categories=[c.name for c in item.meta.categories],
        auth_schemes=list(item.auth_schemes or []),
        composio_managed=bool(item.composio_managed_auth_schemes),
        no_auth=bool(item.no_auth),
        tools_count=int(item.meta.tools_count),
        triggers_count=int(item.meta.triggers_count),
    )


@Cacheable(
    key_pattern=COMPOSIO_TOOLKIT_CATALOG_KEY,
    ttl=COMPOSIO_TOOLKIT_CATALOG_TTL,
    model=list[ComposioToolkit],
)
async def cached_toolkits() -> list[ComposioToolkit]:
    """Return every toolkit in Composio's catalog, from cache when warm."""
    try:
        items = await get_composio_service().list_toolkits()
    except composio_client.AuthenticationError as e:
        raise composio_key_rejected(e) from e
    return [_summary(item) for item in items if not item.is_local_toolkit]


def _rank(toolkit: ComposioToolkit, query: str) -> int | None:
    """Lower ranks first; None drops the toolkit from the results."""
    name = toolkit.name.lower()
    if name.startswith(query) or toolkit.slug.startswith(query):
        return 0
    if query in name or query in toolkit.slug:
        return 1
    if any(query in c.lower() for c in toolkit.categories):
        return 2
    if query in toolkit.description.lower():
        return 3
    return None


def search_toolkits(
    toolkits: Sequence[ComposioToolkit], query: str, category: str | None
) -> list[ComposioToolkit]:
    """Filter by category, then order by how closely name, slug, category or description match."""
    in_category = [t for t in toolkits if category is None or category in t.categories]
    needle = query.strip().lower()
    if not needle:
        return in_category
    ranked = [
        (rank, i, t) for i, t in enumerate(in_category) if (rank := _rank(t, needle)) is not None
    ]
    return [t for _, _, t in sorted(ranked, key=lambda entry: (entry[0], entry[1]))]


async def annotate(toolkits: Sequence[ComposioToolkit]) -> list[ComposioCatalogEntry]:
    """Mark each toolkit built-in, enabled, available or unsupported on this instance."""
    resolved = await resolve_auth_configs()
    enabled = await stored_toolkits()
    code_by_toolkit = {
        i.composio_config.toolkit.lower(): i.id for i in OAUTH_INTEGRATIONS if i.composio_config
    }
    entries: list[ComposioCatalogEntry] = []
    for toolkit in toolkits:
        integration_id = code_by_toolkit.get(toolkit.slug) or (
            toolkit.slug if toolkit.slug in enabled else None
        )
        status: ComposioToolkitStatus
        if toolkit.slug in code_by_toolkit:
            status = "built_in"
        elif integration_id is not None:
            status = "enabled"
        elif toolkit.no_auth:
            status = "unsupported"
        else:
            status = "available"
        entries.append(
            ComposioCatalogEntry(
                **toolkit.model_dump(),
                status=status,
                integration_id=integration_id,
                set_up=integration_id is not None and integration_id in resolved,
            )
        )
    return entries


async def catalog_page(
    query: str, category: str | None, offset: int, limit: int
) -> ComposioCatalogResponse:
    """Return one page of the searched catalog with each entry's state here."""
    toolkits = await cached_toolkits()
    matches = search_toolkits(toolkits, query, category)
    page = await annotate(matches[offset : offset + limit])
    categories = sorted({c for t in toolkits for c in t.categories})
    log.set_ns("composio_catalog", total=len(toolkits), matches=len(matches), page=len(page))
    return ComposioCatalogResponse(items=page, total=len(matches), categories=categories)
