"""Community marketplace service functions."""

from typing import Optional

from app.config.loggers import app_logger as logger
from app.constants.cache import COMMUNITY_CACHE_TTL
from app.db.chroma.public_integrations_store import search_public_integrations
from app.db.mongodb.collections import integrations_collection
from app.db.redis import get_cache, set_cache
from app.schemas.integrations.responses import CommunityListResponse
from app.services.integrations.integration_service import (
    build_creator_lookup_stages,
    format_community_integrations,
)


async def list_community_integrations(
    sort: str = "popular",
    category: str = "all",
    limit: int = 20,
    offset: int = 0,
    search: Optional[str] = None,
) -> CommunityListResponse:
    """List public integrations for the community marketplace."""
    limit = min(limit, 100)

    # Search path - semantic search first, fallback to MongoDB
    if search and search.strip():
        return await _search_community_integrations(
            search.strip(), category, limit, offset
        )

    # Browse path - cached MongoDB query
    return await _browse_community_integrations(sort, category, limit, offset)


async def _search_community_integrations(
    query: str,
    category: str,
    limit: int,
    offset: int,
) -> CommunityListResponse:
    """Search community integrations with semantic search + MongoDB fallback."""
    # Try ChromaDB semantic search first
    search_results = await search_public_integrations(
        query=query,
        limit=limit,
        category=category if category != "all" else None,
    )

    integration_ids = [
        r.get("integration_id") for r in search_results if r.get("integration_id")
    ]

    if integration_ids:
        pipeline = [
            {"$match": {"integration_id": {"$in": integration_ids}, "is_public": True}},
            *build_creator_lookup_stages(),
        ]
        cursor = integrations_collection.aggregate(pipeline)
        docs = await cursor.to_list(length=limit)

        docs_map = {doc["integration_id"]: doc for doc in docs}
        ordered_docs = [docs_map[iid] for iid in integration_ids if iid in docs_map]

        return CommunityListResponse(
            integrations=format_community_integrations(ordered_docs),
            total=len(ordered_docs),
            has_more=False,
        )

    # Fallback to MongoDB regex search
    logger.info(f"ChromaDB returned no results for '{query}', falling back to MongoDB")
    mongo_query = {"is_public": True}
    search_regex = {"$regex": query, "$options": "i"}
    mongo_query["$or"] = [
        {"name": search_regex},
        {"description": search_regex},
        {"tools.name": search_regex},
        {"tools.description": search_regex},
    ]

    if category and category != "all":
        mongo_query["category"] = category

    total = await integrations_collection.count_documents(mongo_query)
    pipeline = [
        {"$match": mongo_query},
        {"$sort": {"clone_count": -1, "published_at": -1}},
        {"$skip": offset},
        {"$limit": limit},
        *build_creator_lookup_stages(),
    ]
    cursor = integrations_collection.aggregate(pipeline)
    docs = await cursor.to_list(length=limit)

    return CommunityListResponse(
        integrations=format_community_integrations(docs),
        total=total,
        has_more=(offset + len(docs)) < total,
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

    query = {"is_public": True, "published_at": {"$ne": None}}

    if category and category != "all":
        query["category"] = category

    sort_dict = {"clone_count": -1, "published_at": -1}
    if sort == "recent":
        sort_dict = {"published_at": -1}
    elif sort == "name":
        sort_dict = {"name": 1}

    total = await integrations_collection.count_documents(query)
    pipeline = [
        {"$match": query},
        {"$sort": sort_dict},
        {"$skip": offset},
        {"$limit": limit},
        *build_creator_lookup_stages(),
    ]
    cursor = integrations_collection.aggregate(pipeline)
    docs = await cursor.to_list(length=limit)

    response = CommunityListResponse(
        integrations=format_community_integrations(docs),
        total=total,
        has_more=(offset + len(docs)) < total,
    )

    await set_cache(cache_key, response.model_dump(), ttl=COMMUNITY_CACHE_TTL)
    return response
