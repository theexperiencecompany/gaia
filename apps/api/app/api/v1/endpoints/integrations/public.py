"""Public integration routes (no auth required for SEO/sharing)."""

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.config.loggers import auth_logger as logger
from app.db.chroma.public_integrations_store import search_public_integrations
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import (
    AddIntegrationResponse,
    PublicIntegrationDetailResponse,
    SearchIntegrationItem,
    SearchIntegrationsResponse,
)
from app.services.integrations.integration_connection_service import (
    connect_mcp_integration,
)
from app.services.integrations.user_integrations import add_user_integration
from app.helpers.integration_helpers import (
    build_public_integration_pipeline,
    format_public_integration_response,
    generate_integration_slug,
    parse_integration_slug,
)
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get("/public/{identifier}", response_model=PublicIntegrationDetailResponse)
async def get_public_integration(
    identifier: str,
) -> PublicIntegrationDetailResponse:
    """Get public integration details by slug."""
    try:
        slug_parts = parse_integration_slug(identifier)
        short_id = slug_parts.get("shortid")

        if not short_id:
            raise HTTPException(
                status_code=404,
                detail="Invalid slug format. Expected: {name}-mcp-{category}-{id}",
            )

        pipeline = build_public_integration_pipeline(short_id)
        cursor = integrations_collection.aggregate(pipeline)
        docs = await cursor.to_list(length=1)

        if not docs:
            raise HTTPException(status_code=404, detail="Integration not found")

        response_data = format_public_integration_response(docs[0])
        return PublicIntegrationDetailResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching public integration {identifier}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch integration")


@router.post("/public/{integration_id}/add", response_model=AddIntegrationResponse)
async def add_public_integration(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddIntegrationResponse:
    """Add a public integration to user's workspace and trigger connection."""
    try:
        original_doc = await integrations_collection.find_one(
            {"integration_id": integration_id, "is_public": True}
        )
        if not original_doc:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration_name = original_doc["name"]

        existing = await user_integrations_collection.find_one(
            {"user_id": user_id, "integration_id": integration_id}
        )
        if existing:
            if existing.get("status") == "connected":
                return AddIntegrationResponse(
                    integration_id=integration_id,
                    name=integration_name,
                    status="connected",
                    message="Integration already connected",
                )
            logger.info(f"User {user_id} re-attempting connection to {integration_id}")
        else:
            try:
                await add_user_integration(
                    user_id=user_id,
                    integration_id=integration_id,
                    initial_status="created",
                )
            except ValueError:
                pass

            await integrations_collection.update_one(
                {"integration_id": integration_id},
                {"$inc": {"clone_count": 1}},
            )

            logger.info(f"User {user_id} added integration {integration_id}")

        mcp_config = original_doc.get("mcp_config", {})
        server_url = mcp_config.get("server_url")
        requires_auth = mcp_config.get("requires_auth", False)
        auth_type = mcp_config.get("auth_type")

        # For bearer auth without token provided, return bearer_required status
        if auth_type == "bearer" and requires_auth and not request.bearer_token:
            return AddIntegrationResponse(
                integration_id=integration_id,
                name=integration_name,
                status="error",
                error="bearer_required",
                message="Bearer token required for this integration",
            )

        connect_result = await connect_mcp_integration(
            user_id=user_id,
            integration_id=integration_id,
            integration_name=integration_name,
            requires_auth=requires_auth,
            redirect_path=request.redirect_path,
            server_url=server_url,
            is_platform=False,
            bearer_token=request.bearer_token,
        )

        return AddIntegrationResponse(
            integration_id=integration_id,
            name=integration_name,
            status=connect_result.status,
            redirect_url=connect_result.redirect_url,
            tools_count=connect_result.tools_count,
            message=connect_result.message or "Integration added successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding integration {integration_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add integration")


@router.get("/search", response_model=SearchIntegrationsResponse)
async def search_integrations(q: str) -> SearchIntegrationsResponse:
    """Search public integrations using semantic search."""
    try:
        if not q or not q.strip():
            return SearchIntegrationsResponse(integrations=[], query=q)

        results = await search_public_integrations(query=q.strip(), limit=20)
        if not results:
            return SearchIntegrationsResponse(integrations=[], query=q)

        relevance_map = {r["integration_id"]: r["relevance_score"] for r in results}
        integration_ids = list(relevance_map.keys())

        cursor = integrations_collection.find(
            {"integration_id": {"$in": integration_ids}, "is_public": True}
        )
        docs = await cursor.to_list(length=20)
        docs_map = {doc["integration_id"]: doc for doc in docs}

        formatted = []
        for iid in integration_ids:
            doc = docs_map.get(iid)
            if not doc:
                continue

            slug = generate_integration_slug(
                name=doc.get("name", ""),
                category=doc.get("category", "custom"),
                integration_id=iid,
            )

            formatted.append(
                SearchIntegrationItem(
                    integration_id=iid,
                    slug=slug,
                    name=doc.get("name", ""),
                    description=doc.get("description", ""),
                    category=doc.get("category", "custom"),
                    relevance_score=relevance_map.get(iid, 0.0),
                    clone_count=doc.get("clone_count", 0),
                    tool_count=len(doc.get("tools", [])),
                    icon_url=doc.get("icon_url"),
                )
            )

        return SearchIntegrationsResponse(integrations=formatted, query=q)

    except Exception as e:
        logger.error(f"Error searching integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to search integrations")
