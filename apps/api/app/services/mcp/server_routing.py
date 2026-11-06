"""Operations addressed by MCP server URL: resolve the user's connected integration, then use its session."""

import asyncio
import time
from typing import Protocol, cast
import urllib.parse

from langchain_core.tools import BaseTool
from mcp_use.client.session import MCPSession
from pydantic import AnyUrl, BaseModel, ConfigDict, JsonValue

from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.models.integration_models import UserIntegrationDocument
from app.models.mcp_config import McpUiResourceDetails
from app.services.integrations.integration_resolver import IntegrationResolver, ResolvedIntegration
from mcp import ClientSession
from mcp.types import (
    CallToolResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
)
from shared.py.wide_events import McpContext, log


class MCPSessionHost(Protocol):
    """The slice of a user's MCP client that server-URL routing reads: its live sessions and connect gate."""

    user_id: str

    def active_integration_ids(self) -> list[str]: ...

    def session_for(self, integration_id: str) -> MCPSession | None: ...

    async def is_connected_db(self, integration_id: str) -> bool: ...

    async def ensure_connected(self, integration_id: str) -> list[BaseTool]: ...


class _McpContentMeta(BaseModel):
    """A resource content's _meta: the MCP Apps ui hints sit under ui."""

    model_config = ConfigDict(extra="ignore")

    ui: JsonValue = None


class _McpUiHints(BaseModel):
    """The ui hints forwarded to the client verbatim; the MCP Apps spec fixes neither shape."""

    model_config = ConfigDict(extra="ignore")

    csp: JsonValue = None
    permissions: JsonValue = None


def _normalize_server_url(server_url: str) -> str:
    """Normalize server URLs for stable matching."""
    trimmed = (server_url or "").strip()
    if not trimmed:
        return ""

    try:
        parsed = urllib.parse.urlparse(trimmed)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        return urllib.parse.urlunparse((scheme, netloc, path, "", "", ""))
    except Exception:  # nosec B112
        return trimmed.rstrip("/")


def _resolved_matches_server_url(resolved: ResolvedIntegration | None, target: str) -> bool:
    """Check whether a resolved integration's normalized server URL matches target."""
    return bool(
        resolved
        and resolved.mcp_config
        and _normalize_server_url(resolved.mcp_config.server_url) == target
    )


async def _match_active_client_by_server_url(client: MCPSessionHost, target: str) -> str | None:
    """Fast path: currently active in-memory clients for a matching server URL.

    Gated on the stored status, exactly like the slow path — a live session
    on this replica says nothing about whether the user has since revoked
    the integration on another one, and this is the path the MCP proxy
    routes tool calls through.
    """
    for integration_id in client.active_integration_ids():
        resolved = await IntegrationResolver.resolve(integration_id)
        if not _resolved_matches_server_url(resolved, target):
            continue
        if not await client.is_connected_db(integration_id):
            continue
        return integration_id
    return None


def _connectable_candidate_ids(user_integrations: list[UserIntegrationDocument]) -> list[str]:
    """Filter persisted user integrations down to connected candidate ids."""
    return [doc.integration_id for doc in user_integrations if doc.status == "connected"]


async def _find_integration_id_by_server_url(client: MCPSessionHost, server_url: str) -> str | None:
    """Find integration ID for a server URL from active sessions or DB state."""
    target = _normalize_server_url(server_url)
    if not target:
        return None

    # Fast path: check currently active in-memory clients.
    active_match = await _match_active_client_by_server_url(client, target)
    if active_match:
        return active_match

    # Slow path: check user's persisted connected integrations.
    try:
        user_integrations = await user_integration_repository.list_for_user(client.user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.MCP} Failed to load user integrations while matching server_url",
            server_url=server_url,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None

    candidate_ids = _connectable_candidate_ids(user_integrations)
    if not candidate_ids:
        return None

    resolved_results = await asyncio.gather(
        *[IntegrationResolver.resolve(integration_id) for integration_id in candidate_ids],
        return_exceptions=True,
    )

    for integration_id, result in zip(candidate_ids, resolved_results):
        if isinstance(result, BaseException):
            continue
        if _resolved_matches_server_url(result, target):
            return integration_id

    return None


async def call_tool_on_server(
    client: MCPSessionHost,
    server_url: str,
    tool_name: str,
    arguments: dict[str, JsonValue],
) -> CallToolResult:
    """Call a tool on the MCP server identified by server_url.

    Finds the connected integration whose server_url matches, then calls
    the tool via the active session. Raises ValueError if none match.
    """
    matching_integration_id = await _find_integration_id_by_server_url(client, server_url)

    if matching_integration_id is None:
        raise ValueError(f"No connected MCP integration found for server_url: {server_url}")

    log.set(
        mcp=McpContext(
            operation="call_tool",
            server_id=matching_integration_id,
            tool_name=tool_name,
        )
    )

    # Rehydrate a previously-connected integration if its in-memory session was evicted.
    call_start = time.perf_counter()
    await client.ensure_connected(matching_integration_id)

    session = client.session_for(matching_integration_id)
    if session is None:
        raise ValueError(f"MCP integration {matching_integration_id} is not connected in memory")

    # Same surface as the reconnect path's latency_ms; Prometheus sees this call
    # once at the tool wrapper, so a histogram here would double-count. Stamped on
    # failure too, else an exception leaves the event with no success and no latency.
    try:
        result = cast(  # mcp_use ships no py.typed; call_tool is annotated -> CallToolResult
            CallToolResult, await session.call_tool(name=tool_name, arguments=arguments)
        )
    except Exception:
        log.set_ns(
            "mcp",
            success=False,
            latency_ms=round((time.perf_counter() - call_start) * 1000.0, 2),
        )
        raise
    log.set_ns(
        "mcp",
        success=not result.isError,
        latency_ms=round((time.perf_counter() - call_start) * 1000.0, 2),
    )

    return result


async def _get_session_for_server(client: MCPSessionHost, server_url: str) -> ClientSession:
    """Resolve the underlying official MCP ClientSession for server_url.

    Bypasses mcp_use's wrapper so resource/prompt calls yield typed
    *Result models — its convenience session returns bare lists and has
    no list_resource_templates at all. Raises ValueError if unavailable.
    """
    matching_integration_id = await _find_integration_id_by_server_url(client, server_url)
    if matching_integration_id is None:
        raise ValueError(f"No connected MCP integration found for server_url: {server_url}")
    await client.ensure_connected(matching_integration_id)
    session = client.session_for(matching_integration_id)
    if session is None:
        raise ValueError(f"MCP integration {matching_integration_id} is not connected in memory")
    client_session = session.connector.client_session
    if client_session is None:
        raise ValueError(f"MCP integration {matching_integration_id} has no active session")
    # mcp_use ships no py.typed marker, so mypy treats its whole surface as
    # Any; BaseConnector.client_session is genuinely typed ClientSession | None
    # in its source (verified), narrowed to non-None by the check above.
    return cast(ClientSession, client_session)


async def list_resources_on_server(
    client: MCPSessionHost,
    server_url: str,
    cursor: str | None = None,
) -> ListResourcesResult:
    """List resources on an MCP server identified by server_url."""
    session = await _get_session_for_server(client, server_url)
    return await session.list_resources(cursor=cursor)


async def list_resource_templates_on_server(
    client: MCPSessionHost,
    server_url: str,
    cursor: str | None = None,
) -> ListResourceTemplatesResult:
    """List resource templates on an MCP server identified by server_url."""
    session = await _get_session_for_server(client, server_url)
    return await session.list_resource_templates(cursor=cursor)


async def read_resource_on_server(
    client: MCPSessionHost,
    server_url: str,
    uri: str,
) -> ReadResourceResult:
    """Read a resource on an MCP server identified by server_url."""
    session = await _get_session_for_server(client, server_url)
    return await session.read_resource(AnyUrl(uri))


async def list_prompts_on_server(
    client: MCPSessionHost,
    server_url: str,
    cursor: str | None = None,
) -> ListPromptsResult:
    """List prompts on an MCP server identified by server_url."""
    session = await _get_session_for_server(client, server_url)
    return await session.list_prompts(cursor=cursor)


async def read_ui_resource_details(
    client: MCPSessionHost, server_url: str, resource_uri: str
) -> McpUiResourceDetails | None:
    """Read a UI resource and return HTML plus content-level UI metadata, or None on failure.

    Finds the active session matching server_url, then reads the resource
    and extracts html plus content-level _meta.ui.csp/permissions when present.
    """
    try:
        matching_integration_id = await _find_integration_id_by_server_url(client, server_url)
        if matching_integration_id is None:
            log.warning(
                f"{LogTag.MCP} No active MCP session found for server_url",
                server_url=server_url,
            )
            return None

        await client.ensure_connected(matching_integration_id)

        session = client.session_for(matching_integration_id)
        if session is None:
            log.warning(
                f"{LogTag.MCP} No active MCP client found for server_url", server_url=server_url
            )
            return None

        result = await asyncio.wait_for(
            session.read_resource(resource_uri),
            timeout=10.0,
        )

        # Extract text content from ReadResourceResult
        for content in result.contents:
            text = getattr(content, "text", None)
            if text is not None:
                content_meta = getattr(content, "_meta", None) or getattr(content, "meta", None)
                raw_ui = (
                    _McpContentMeta.model_validate(content_meta).ui
                    if isinstance(content_meta, dict)
                    else None
                )
                ui = (
                    _McpUiHints.model_validate(raw_ui)
                    if isinstance(raw_ui, dict)
                    else _McpUiHints()
                )

                return McpUiResourceDetails(html=str(text), csp=ui.csp, permissions=ui.permissions)

        return None

    except TimeoutError:
        log.warning(
            f"{LogTag.MCP} Timeout reading UI resource from (10s)",
            resource_uri=resource_uri,
            server_url=server_url,
        )
        return None
    except Exception as e:
        log.warning(
            f"{LogTag.MCP} Failed to read UI resource from",
            resource_uri=resource_uri,
            server_url=server_url,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None
