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
    CommunityIntegrationCreator,
    IntegrationTool,
    MCPConfigDetail,
    PublicIntegrationDetailResponse,
    SearchIntegrationItem,
    SearchIntegrationsResponse,
)
from app.services.integrations.integration_connection_service import (
    connect_mcp_integration,
)
from app.services.integrations.user_integrations import add_user_integration
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get("/public/{integration_id}", response_model=PublicIntegrationDetailResponse)
async def get_public_integration(
    integration_id: str,
) -> PublicIntegrationDetailResponse:
    """Get public integration details - no auth required for SEO/sharing."""
    try:
        pipeline = [
            {"$match": {"integration_id": integration_id, "is_public": True}},
            {
                "$lookup": {
                    "from": "users",
                    "let": {
                        "creator_id": {
                            "$convert": {
                                "input": "$created_by",
                                "to": "objectId",
                                "onError": None,
                                "onNull": None,
                            }
                        }
                    },
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$_id", "$$creator_id"]}}},
                        {"$project": {"name": 1, "picture": 1}},
                    ],
                    "as": "creator_info",
                }
            },
            {
                "$addFields": {
                    "creator": {
                        "$cond": {
                            "if": {"$gt": [{"$size": "$creator_info"}, 0]},
                            "then": {"$arrayElemAt": ["$creator_info", 0]},
                            "else": None,
                        }
                    }
                }
            },
            {"$project": {"creator_info": 0}},
        ]

        cursor = integrations_collection.aggregate(pipeline)
        docs = await cursor.to_list(length=1)

        if not docs:
            raise HTTPException(status_code=404, detail="Integration not found")

        doc = docs[0]
        mcp_config_doc = doc.get("mcp_config", {})
        mcp_config = None
        if mcp_config_doc:
            mcp_config = MCPConfigDetail(
                server_url=mcp_config_doc.get("server_url"),
                requires_auth=mcp_config_doc.get("requires_auth", False),
                auth_type=mcp_config_doc.get("auth_type"),
            )

        creator = None
        creator_data = doc.get("creator")
        if creator_data:
            creator = CommunityIntegrationCreator(
                name=creator_data.get("name"),
                picture=creator_data.get("picture"),
            )

        tools = doc.get("tools", [])

        return PublicIntegrationDetailResponse(
            integration_id=doc["integration_id"],
            name=doc["name"],
            description=doc.get("description", ""),
            category=doc.get("category", "custom"),
            icon_url=doc.get("icon_url"),
            creator=creator,
            mcp_config=mcp_config,
            tools=[
                IntegrationTool(
                    name=t.get("name", ""), description=t.get("description")
                )
                for t in tools
            ],
            clone_count=doc.get("clone_count", 0),
            tool_count=len(tools),
            published_at=doc.get("published_at"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching public integration {integration_id}: {e}")
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

        connect_result = await connect_mcp_integration(
            user_id=user_id,
            integration_id=integration_id,
            requires_auth=requires_auth,
            redirect_path=request.redirect_path,
            server_url=server_url,
            is_platform=False,
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
    """Search public integrations using semantic search - no auth required."""
    try:
        if not q or not q.strip():
            return SearchIntegrationsResponse(integrations=[], query=q)

        results = await search_public_integrations(query=q.strip(), limit=20)

        if not results:
            return SearchIntegrationsResponse(integrations=[], query=q)

        integration_ids = [
            r.get("integration_id") for r in results if r.get("integration_id")
        ]

        docs_map = {}
        if integration_ids:
            cursor = integrations_collection.find(
                {"integration_id": {"$in": integration_ids}, "is_public": True}
            )
            docs = await cursor.to_list(length=20)
            docs_map = {doc["integration_id"]: doc for doc in docs}

        formatted = []
        for r in results:
            iid = r.get("integration_id")
            doc = docs_map.get(iid, {}) if iid else {}

            formatted.append(
                SearchIntegrationItem(
                    integration_id=iid or r.get("id", "unknown"),
                    name=r.get("name", doc.get("name", "")),
                    description=r.get("description", doc.get("description", "")),
                    category=r.get("category", doc.get("category", "custom")),
                    relevance_score=r.get("relevance_score", 0.0),
                    clone_count=r.get("clone_count", doc.get("clone_count", 0)),
                    tool_count=r.get("tool_count", len(doc.get("tools", []))),
                    icon_url=doc.get("icon_url"),
                )
            )

        return SearchIntegrationsResponse(integrations=formatted, query=q)

    except Exception as e:
        logger.error(f"Error searching integrations: {e}")
        raise HTTPException(status_code=500, detail="Failed to search integrations")
