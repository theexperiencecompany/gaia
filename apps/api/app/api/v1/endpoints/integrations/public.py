"""Public integration routes (no auth required for SEO/sharing)."""

import contextlib

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.log_tags import LogTag
from app.db.chroma.public_integrations_store import search_public_integrations
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.workflows import workflow_repository
from app.helpers.integration_helpers import (
    format_public_integration_response,
    generate_integration_slug,
    parse_integration_slug,
)
from app.models.workflow_models import PublicWorkflowsResponse
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import (
    AddIntegrationResponse,
    IntegrationTool,
    PublicIntegrationDetailResponse,
    SearchIntegrationItem,
    SearchIntegrationsResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.integrations.integration_connection_service import (
    connect_mcp_integration,
)
from app.services.integrations.user_integrations import add_user_integration
from app.services.mcp.mcp_tools_service import get_integration_tools
from app.utils.creator import format_creator
from shared.py.wide_events import log

router = APIRouter()


@router.get("/public/{identifier}", response_model=PublicIntegrationDetailResponse)
async def get_public_integration(
    identifier: str,
) -> PublicIntegrationDetailResponse:
    """Get public integration details by slug or native integration ID."""
    try:
        log.set(operation="get_public_integration", integration_id=identifier)

        # 1. Check platform (native) integrations first — in-memory, instant
        # Platform integrations use their ID as slug (e.g., "googlecalendar", "slack")
        native = next(
            (i for i in OAUTH_INTEGRATIONS if i.id == identifier and i.managed_by != "internal"),
            None,
        )
        if native:
            auth_type = None
            if native.mcp_config:
                auth_type = native.mcp_config.auth_type
            elif native.managed_by in ("self", "composio"):
                auth_type = "oauth"

            stored_tools = await get_integration_tools(native.id)
            integration_tools = [
                IntegrationTool(name=t["name"], description=t.get("description"))
                for t in stored_tools
            ]

            log.set(integration_name=native.name)
            log.set(outcome="success")
            return PublicIntegrationDetailResponse(
                integration_id=native.id,
                slug=native.id,
                name=native.name,
                description=native.description,
                category=native.category,
                icon_url=None,
                creator=None,
                mcp_config=None,
                tools=integration_tools,
                clone_count=0,
                tool_count=len(integration_tools),
                published_at=None,
                source="platform",
                auth_type=auth_type,
                content=native.content,
            )

        # 2. Try direct slug match first (new format without hash)
        integration = await integration_repository.get_public_by_slug(identifier)

        # Fallback: legacy hash-based lookup
        if not integration:
            slug_parts = parse_integration_slug(identifier)
            short_id = slug_parts.get("shortid")
            if short_id:
                integration = await integration_repository.get_public_by_id_prefix(short_id)

        if not integration:
            raise HTTPException(status_code=404, detail="Integration not found")

        response_data = format_public_integration_response(integration)
        log.set(integration_name=response_data.get("name"))
        log.set(outcome="success")
        return PublicIntegrationDetailResponse(**response_data)

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error fetching public integration",
            identifier=identifier,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to fetch integration") from e


@router.post("/public/{integration_id}/add", response_model=AddIntegrationResponse)
async def add_public_integration(
    integration_id: str,
    request: ConnectIntegrationRequest,
    user_id: str = Depends(get_user_id),
) -> AddIntegrationResponse:
    """Add a public integration to user's workspace and trigger connection."""
    try:
        log.set(
            operation="add_public_integration",
            integration_id=integration_id,
            user={"id": user_id},
            integration={"id": integration_id},
        )
        original = await integration_repository.get_public(integration_id)
        if not original:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration_name = original.name

        existing = await user_integration_repository.get_for_user(user_id, integration_id)
        if existing:
            if existing.status == "connected":
                return AddIntegrationResponse(
                    integration_id=integration_id,
                    name=integration_name,
                    status="connected",
                    message="Integration already connected",
                )
            log.info(
                f"{LogTag.INTEGRATION} User re-attempting integration connection",
                user_id=user_id,
                integration_id=integration_id,
            )
        else:
            with contextlib.suppress(ValueError):
                await add_user_integration(
                    user_id=user_id,
                    integration_id=integration_id,
                    initial_status="created",
                )

            await integration_repository.increment_clone_count(integration_id)

            log.info(
                f"{LogTag.INTEGRATION} User added integration",
                user_id=user_id,
                integration_id=integration_id,
            )

        mcp_config = original.mcp_config
        server_url = mcp_config.server_url if mcp_config else None
        requires_auth = mcp_config.requires_auth if mcp_config else False
        auth_type = mcp_config.auth_type if mcp_config else None

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

        log.set(integration_name=integration_name)
        log.set(outcome="success")
        if connect_result.status == "connected":
            capture_context_event(
                AnalyticsEvents.INTEGRATION_CONNECTED,
                {"integration_id": integration_id, "source": "marketplace"},
            )
        return AddIntegrationResponse(
            integration_id=integration_id,
            name=integration_name,
            status=connect_result.status,
            redirect_url=connect_result.redirect_url,
            tools_count=connect_result.tools_count,
            error=connect_result.error,
            message=connect_result.message or "Integration added successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error adding integration",
            integration_id=integration_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to add integration") from e


@router.get("/search", response_model=SearchIntegrationsResponse)
async def search_integrations(q: str) -> SearchIntegrationsResponse:
    """Search public integrations using semantic search."""
    try:
        log.set(operation="search_integrations")
        if not q or not q.strip():
            log.set(result_count=0)
            log.set(outcome="success")
            return SearchIntegrationsResponse(integrations=[], query=q)

        results = await search_public_integrations(query=q.strip(), limit=20)
        if not results:
            log.set(result_count=0)
            log.set(outcome="success")
            return SearchIntegrationsResponse(integrations=[], query=q)

        relevance_map = {r["integration_id"]: r["relevance_score"] for r in results}
        integration_ids = list(relevance_map.keys())

        integrations = await integration_repository.find_public_by_ids(integration_ids)
        by_id = {i.integration_id: i for i in integrations}

        formatted = []
        for iid in integration_ids:
            integration = by_id.get(iid)
            if not integration:
                continue

            slug = generate_integration_slug(
                name=integration.name,
                category=integration.category,
            )

            formatted.append(
                SearchIntegrationItem(
                    integration_id=iid,
                    slug=slug,
                    name=integration.name,
                    description=integration.description,
                    category=integration.category,
                    relevance_score=relevance_map.get(iid, 0.0),
                    clone_count=integration.clone_count,
                    tool_count=len(integration.tools),
                    icon_url=integration.icon_url,
                )
            )

        log.set(result_count=len(formatted))
        log.set(outcome="success")
        return SearchIntegrationsResponse(integrations=formatted, query=q)

    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error searching integrations",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to search integrations") from e


@router.get(
    "/public/{identifier}/workflows",
    responses={
        500: {"description": "Failed to fetch related workflows"},
    },
)
async def get_related_workflows(
    identifier: str,
    limit: int = 10,
    offset: int = 0,
) -> PublicWorkflowsResponse:
    """Get public community workflows related to an integration by identifier (slug or native ID)."""
    try:
        log.set(operation="get_related_workflows", integration_id=identifier)

        # Normalize limit/offset
        limit = max(1, min(limit, 50))
        offset = max(0, offset)

        # Mix featured (is_explore) and community (is_public) workflows that use
        # this integration, most-run first. The repository regex-escapes the
        # identifier so it matches literally (ReDoS / injection guard).
        rows = await workflow_repository.find_public_by_step_category(
            identifier, limit=limit, offset=offset
        )
        total = await workflow_repository.count_public_by_step_category(identifier)

        formatted_workflows = []
        for row in rows:
            normalized_steps = [
                {
                    "id": step.id,
                    "title": step.title,
                    "description": step.description,
                    "category": step.category or "general",
                }
                for step in row.steps
            ]
            formatted_workflows.append(
                {
                    "id": row.id,
                    "title": row.title,
                    "description": row.description,
                    "slug": row.slug,
                    "prompt": row.prompt,
                    "steps": normalized_steps,
                    "total_executions": row.total_executions,
                    "created_at": row.created_at,
                    "creator": format_creator(row),
                }
            )

        log.set(result_count=len(formatted_workflows))
        log.set(outcome="success")
        return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Error fetching related workflows",
            identifier=identifier,
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to fetch related workflows") from e
