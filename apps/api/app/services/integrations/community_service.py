"""Community marketplace service functions."""

from app.constants.cache import COMMUNITY_CACHE_TTL
from app.constants.log_tags import LogTag
from app.db.chroma.public_integrations_store import search_public_integrations
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.schemas.integrations.responses import CommunityListResponse
from app.services.integrations.integration_service import (
    format_community_integrations,
)
from shared.py.wide_events import log


async def list_community_integrations(
    sort: str = "popular",
    category: str = "all",
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,
) -> CommunityListResponse:
    """List public integrations for the community marketplace."""
    log.set(
        integration={
            "provider": category or "all",
            "action": "list_community_integrations",
        }
    )
    limit = min(limit, 100)

    # Search path - semantic search first, fallback to MongoDB
    if search and search.strip():
        return await _search_community_integrations(search.strip(), category, limit, offset)

    # Browse path - cached MongoDB query
    return await _browse_community_integrations(sort, category, limit, offset)


async def _search_community_integrations(
    query: str,
    category: str,
    limit: int,
    offset: int,
) -> CommunityListResponse:
    """Search community integrations with semantic search + MongoDB fallback."""
    # Try ChromaDB semantic search first. A search-infra outage falls back to
    # the MongoDB regex path below instead of failing the marketplace page —
    # search_public_integrations raises on infra errors rather than returning
    # an empty list, so the fallback must be explicit here.
    try:
        search_results = await search_public_integrations(
            query=query,
            limit=limit,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.INTEGRATION} Semantic search unavailable, using MongoDB fallback",
            error=str(e),
            error_type=type(e).__name__,
        )
        search_results = []

    integration_ids = [str(r["integration_id"]) for r in search_results if r.get("integration_id")]

    if integration_ids:
        integrations = await integration_repository.community_by_ids(integration_ids)
        by_id = {i.integration_id: i for i in integrations}
        ordered = [by_id[iid] for iid in integration_ids if iid in by_id]

        # The category filter is applied here, not in the vector search: ChromaDB
        # indexes only {"integration_id": ...} for these documents, so it has no
        # category to filter on and returns hits from every one. Post-filtering can
        # return fewer than `limit` rows when the top-k is dominated by other
        # categories, which is the honest trade — the browse path beside this one
        # filters by category (_community_search_filter), and a marketplace where
        # picking a category only works until you also type a query is worse.
        if category and category != "all":
            ordered = [i for i in ordered if i.category == category]

        # An empty list here means every semantic hit was in another category, so
        # fall through to the Mongo path exactly as a no-hit search does — it
        # filters by category itself and may reach rows the vector search ranked
        # below the cut.
        if ordered:
            return CommunityListResponse(
                integrations=format_community_integrations(ordered),
                total=len(ordered),
                has_more=False,
            )

    # Fallback to MongoDB regex search
    log.info(f"{LogTag.INTEGRATION} ChromaDB returned no results, falling back to MongoDB")
    total = await integration_repository.count_community_search(query, category)
    integrations = await integration_repository.community_search(
        query, category, offset=offset, limit=limit
    )

    return CommunityListResponse(
        integrations=format_community_integrations(integrations),
        total=total,
        has_more=(offset + len(integrations)) < total,
    )


async def _browse_community_integrations(
    sort: str,
    category: str,
    limit: int,
    offset: int,
) -> CommunityListResponse:
    """Browse community integrations with caching."""
    cache_key = f"marketplace:community:{sort}:{category}:{limit}:{offset}"
    cached = await get_cache(cache_key)
    if cached:
        return CommunityListResponse(**cached)

    total = await integration_repository.count_community_browse(category)
    integrations = await integration_repository.community_browse(
        sort, category, offset=offset, limit=limit
    )

    response = CommunityListResponse(
        integrations=format_community_integrations(integrations),
        total=total,
        has_more=(offset + len(integrations)) < total,
    )

    await set_cache(cache_key, response.model_dump(), ttl=COMMUNITY_CACHE_TTL)
    return response
