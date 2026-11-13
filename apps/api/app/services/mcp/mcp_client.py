"""Per-user MCP client: connects integrations, holds their sessions and live tools, and tears them down."""

import asyncio
from collections.abc import Awaitable, Callable, Collection, Iterable
import re
import time
from typing import TypedDict

from langchain_core.tools import BaseTool
from mcp_use import MCPClient as BaseMCPClient
from mcp_use.client.session import MCPSession

from app.config.settings import settings
from app.constants.cache import OAUTH_DISCOVERY_PREFIX
from app.constants.device_bridge import DEVICE_TRANSPORT
from app.constants.log_tags import LogTag
from app.constants.mcp import COMPOSIO_MCP_HOST, MCP_UNLISTED_CONNECT_MAX
from app.constants.providers import CredentialProviderName
from app.core.lazy_loader import providers
from app.db.chroma.chroma_tools_store import index_tools_to_store
from app.db.redis import delete_cache
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.integration_models import Integration
from app.models.mcp_config import (
    MCPConfig,
    McpProbeResult,
    MCPUseConfig,
    MCPUseServerConfig,
)
from app.services.integrations.integration_resolver import IntegrationResolver, ResolvedIntegration
from app.services.integrations.user_integration_status import (
    update_user_integration_status,
)
from app.services.integrations.user_integrations import (
    connected_tool_records,
    get_connected_integration_ids,
    invalidate_user_integration_caches,
)
from app.services.mcp.custom_mcp_index import (
    CustomMcpIndexRequest,
    index_custom_mcp_as_subagent,
)
from app.services.mcp.device_connector import DeviceConnector
from app.services.mcp.mcp_client_pool import get_mcp_client_pool
from app.services.mcp.mcp_errors import (
    MCPAuthorizationRequiredError,
    StepUpAuthRequiredError,
    is_terminal_auth_failure,
)
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_service import (
    RawToolMetadata,
    store_mcp_tools,
)
from app.services.mcp.oauth_discovery import discover_oauth_config, probe_mcp_connection
from app.services.mcp.resilient_adapter import ResilientLangChainAdapter
from app.services.mcp.token_management import (
    revoke_integration_tokens,
    try_refresh_token,
)
from app.services.mcp.tool_naming import (
    ServerToolNames,
    apply_gaia_names,
    gaia_names_by_integration,
    live_server_tool_names,
    reserved_tool_names,
    server_identity,
    shared_index_tools,
    stamp_tool_metadata,
)
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolve as resolve_composio_config,
)
from app.utils.background_tasks import spawn_background_task
from app.utils.mcp_utils import wrap_tools_with_null_filter
from app.utils.url_safety import assert_endpoint_url_allowed
from shared.py.wide_events import log, log_context, spawn_logged_task


class _SanitizedMcpServer(TypedDict):
    """One mcpServers entry with credentials reduced to presence flags."""

    url: str | None
    transport: str | None
    has_auth: bool
    has_headers: bool


class _SanitizedMcpConfig(TypedDict):
    """Log-safe projection of :class:MCPUseConfig — never fed back to mcp_use."""

    mcpServers: dict[str, _SanitizedMcpServer]


async def _with_wide_event(coro: Awaitable[None], label: str) -> None:
    """Run a background coroutine inside its own wide event boundary.

    Detached tasks escape the request's logging middleware, so without this
    every log.set() they make (mcp_connect, mcp_connect_error, mcp_reconnect)
    would be discarded. log_context binds a fresh accumulator and flushes a
    canonical background_task line on exit so those fields reach Loki.
    """
    async with log_context(f"mcp:{label}"):
        await coro


def _spawn_background(coro: Awaitable[None], label: str) -> asyncio.Task[None] | None:
    """Spawn a fire-and-forget task inside a wide event boundary so its log.set() fields emit.

    Returns None if there is no running event loop (e.g. tests), in which
    case the caller awaits inline instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return None

    return spawn_background_task(_with_wide_event(coro, label), name=f"mcp:{label}")


def _parse_device_server_url(server_url: str) -> tuple[str, str]:
    """Split a device://<device_id>/<server_key> URL into its parts."""
    prefix = f"{DEVICE_TRANSPORT}://"
    if not server_url.startswith(prefix):
        raise ValueError(f"Not a device server URL: {server_url}")
    remainder = server_url[len(prefix) :]
    device_id, _, server_key = remainder.partition("/")
    if not device_id or not server_key:
        raise ValueError(f"Malformed device server URL: {server_url}")
    return device_id, server_key


class MCPClient:
    """One user's MCP connections: their sessions, live tools and connect/disconnect lifecycle."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.token_store = MCPTokenStore(user_id)
        self._clients: dict[str, BaseMCPClient] = {}
        self._tools: dict[str, list[BaseTool]] = {}
        self._connecting: dict[str, asyncio.Event] = {}
        self._connect_results: dict[str, list[BaseTool] | None] = {}
        # Integrations whose token refresh is already in flight on this call
        # stack. _handle_connect_failure recurses through _do_connect, and this
        # is what stops the two refreshing each other forever.
        self._refresh_attempts: set[str] = set()

    def _sanitize_config(self, config: MCPUseConfig) -> _SanitizedMcpConfig:
        """Sanitize config for logging by removing sensitive data."""
        sanitized: dict[str, _SanitizedMcpServer] = {}
        servers: dict[str, MCPUseServerConfig] = config["mcpServers"]
        for server_id, server_config in servers.items():
            sanitized[server_id] = _SanitizedMcpServer(
                url=server_config.get("url"),
                transport=server_config.get("transport"),
                has_auth=server_config.get("auth") is not None,
                has_headers="headers" in server_config,
            )
        return _SanitizedMcpConfig(mcpServers=sanitized)

    async def probe_connection(self, server_url: str) -> McpProbeResult:
        """Probe an MCP server to determine auth requirements."""
        return await probe_mcp_connection(server_url)

    async def update_integration_auth_status(
        self,
        integration_id: str,
        requires_auth: bool,
        auth_type: str,
    ) -> None:
        """Update integration auth status in MongoDB after probe discovery.

        Keeps the stored mcp_config in sync with the auth requirements actually
        discovered from the server, fixing stale requires_auth flags.
        """
        try:
            updated = await integration_repository.set_mcp_auth(
                integration_id, requires_auth, auth_type
            )
            if updated:
                log.info(
                    f"{LogTag.MCP} Updated auth status",
                    integration_id=integration_id,
                    requires_auth=requires_auth,
                    auth_type=auth_type,
                )
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} Failed to update auth status for",
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _build_config(
        self,
        integration_id: str,
        mcp_config: MCPConfig,
    ) -> MCPUseConfig:
        """Build mcp-use config dict.

        Defaults transport to "streamable-http" per MCP spec 2025-11-25 (SSE
        is deprecated there) unless mcp_config.transport is set. A string
        auth token uses BearerAuth directly, skipping OAuth discovery.
        """
        server_config: MCPUseServerConfig = {"url": mcp_config.server_url}

        # Transport: explicit config or let mcp_use auto-detect
        # Per MCP spec 2025-11-25, streamable HTTP is preferred over deprecated SSE
        if mcp_config.transport:
            server_config["transport"] = mcp_config.transport
        else:
            server_config["transport"] = "streamable-http"

        # Check for stored tokens: bearer first (user-provided), then OAuth
        # Bearer tokens can be stored even when requires_auth=False
        stored_token = await self.token_store.get_bearer_token(integration_id)
        token_source = "bearer"  # nosec B105

        # If no bearer token, try OAuth token (only if auth is required)
        if not stored_token and mcp_config.requires_auth:
            # Check if OAuth token is expiring soon and try to refresh
            if await self.token_store.is_token_expiring_soon(integration_id):
                log.info(
                    f"{LogTag.MCP} Token expiring soon, attempting refresh",
                    integration_id=integration_id,
                )
                await self._try_refresh_token(integration_id, mcp_config)

            stored_token = await self.token_store.get_oauth_token(integration_id)
            token_source = "oauth"  # nosec B105

        if stored_token:
            log.set_ns(
                "mcp",
                operation="connect",
                server_id=integration_id,
                transport=server_config.get("transport"),
            )
            log.info(
                f"{LogTag.MCP} Retrieved stored token",
                integration_id=integration_id,
                token_source=token_source,
                token_length=len(stored_token),
            )
            # Strip Bearer prefix if present - mcp-use adds it automatically
            raw_token = stored_token
            if stored_token.lower().startswith("bearer "):
                raw_token = stored_token[7:]

            # Primary: Pass token via auth config
            server_config["auth"] = raw_token

            # Fallback: Also pass via headers for servers where mcp-use OAuth
            # discovery fails (e.g., Smithery servers that don't expose
            # .well-known/oauth-authorization-server endpoints)
            server_config["headers"] = {"Authorization": f"Bearer {raw_token}"}
        elif mcp_config.requires_auth:
            log.warning(
                f"{LogTag.MCP} _build_config: no stored token, but requires_auth=True for user — raising 'OAuth authorization required'",
                integration_id=integration_id,
                user_id=self.user_id,
            )
            raise MCPAuthorizationRequiredError(integration_id)
        else:
            # No auth required and no bearer token - set auth to None
            log.info(
                f"{LogTag.MCP} _build_config: no auth required, connecting unauthenticated",
                integration_id=integration_id,
            )
            server_config["auth"] = None

        # Composio gateway auth is a platform x-api-key header, not per-user
        # OAuth; requires_auth stays False because there is no user credential.
        if mcp_config.server_url and COMPOSIO_MCP_HOST in mcp_config.server_url:
            # Resolved store-first so a key configured in Settings applies
            # without a restart; env remains the fallback.
            composio_config: ProviderConfig | None = await resolve_composio_config(
                CredentialProviderName.COMPOSIO
            )
            composio_api_key = composio_config.api_key if composio_config else None
            if composio_api_key:
                server_config.setdefault("headers", {})["x-api-key"] = composio_api_key

        return {"mcpServers": {integration_id: server_config}}

    async def connect(self, integration_id: str) -> list[BaseTool]:
        """Connect to an MCP server and return LangChain tools, deduplicating concurrent connects.

        Unauthenticated MCPs connect directly; OAuth MCPs use stored
        credentials. Supports both platform and custom integrations.
        """
        # Return cached tools if already connected
        if integration_id in self._tools:
            return self._tools[integration_id]

        # If another coroutine is already connecting this integration, wait for it
        if integration_id in self._connecting:
            log.info(
                f"{LogTag.MCP} Waiting for concurrent connect to finish",
                integration_id=integration_id,
            )
            await self._connecting[integration_id].wait()
            if integration_id in self._tools:
                return self._tools[integration_id]
            raise ValueError(f"Concurrent connect for {integration_id} failed")

        # Mark as connecting to prevent duplicate work
        self._connecting[integration_id] = asyncio.Event()
        try:
            tools = await self._do_connect(integration_id)
            return tools
        finally:
            event = self._connecting.pop(integration_id, None)
            if event:
                event.set()

    async def reconnect_and_call(
        self, integration_id: str, tool_name: str, kwargs: dict[str, object]
    ) -> object:
        """Force a fresh connect for integration_id then call tool_name once.

        Invoked when a call hits a dead connector; telemetry tracks how often
        this fires. Waits for and reuses any in-flight connect/reconnect
        rather than racing — without that guard, popping _clients/_tools
        mid-flight raises "Concurrent connect failed" in the other coroutine.
        """
        start = time.monotonic()
        log.warning(
            f"{LogTag.MCP} transparent reconnect requested for tool",
            integration_id=integration_id,
            tool_name=tool_name,
        )

        # If another caller (warmup, sibling reconnect) is already connecting,
        # wait on their event and reuse the result they produce.
        in_flight_event = self._connecting.get(integration_id)
        if in_flight_event is not None:
            log.info(
                f"{LogTag.MCP} transparent reconnect waiting on in-flight connect",
                integration_id=integration_id,
            )
            try:
                await in_flight_event.wait()
            except Exception as wait_err:
                log.warning(
                    f"{LogTag.MCP} in-flight connect wait raised",
                    integration_id=integration_id,
                    error=str(wait_err),
                    error_type=type(wait_err).__name__,
                )

        # Take the connecting lock ourselves before clearing caches so any
        # concurrent caller after this point waits on us instead of racing.
        if integration_id not in self._connecting:
            our_event = asyncio.Event()
            self._connecting[integration_id] = our_event
            try:
                # Drop stale references and force a fresh _do_connect.
                self._clients.pop(integration_id, None)
                self._tools.pop(integration_id, None)
                try:
                    await self._do_connect(integration_id)
                except Exception as e:
                    log.set_ns(
                        "mcp",
                        operation="connect",
                        server_id=integration_id,
                        tool_name=tool_name,
                        success=False,
                        error_type=type(e).__name__,
                    )
                    raise
            finally:
                our_event.set()
                self._connecting.pop(integration_id, None)

        fresh_tools = self._tools.get(integration_id, [])
        if not fresh_tools:
            log.set_ns(
                "mcp",
                operation="connect",
                server_id=integration_id,
                tool_name=tool_name,
                success=False,
                error_type=RuntimeError.__name__,
            )
            raise RuntimeError(f"No tools available for {integration_id} after reconnect")

        fresh_tool = next((t for t in fresh_tools if t.name == tool_name), None)
        if fresh_tool is None:
            log.set_ns(
                "mcp",
                operation="connect",
                server_id=integration_id,
                tool_name=tool_name,
                success=False,
                error_type=RuntimeError.__name__,
            )
            raise RuntimeError(f"Tool '{tool_name}' not found in {integration_id} after reconnect")

        # Bypass the wrapper to avoid recursion (it already retried once). LangChain
        # types BaseTool._arun as -> Any and stashes the original dynamically, so
        # `object` is the narrowest knowable type here — and what filtered_arun wants.
        underlying = getattr(fresh_tool, "_original_arun", None)
        if underlying is None:
            underlying = fresh_tool._arun

        try:
            result: object = await underlying(**kwargs)
        except Exception as e:
            log.set_ns(
                "mcp",
                operation="connect",
                server_id=integration_id,
                tool_name=tool_name,
                success=False,
                error_type=type(e).__name__,
            )
            raise

        latency_ms = int((time.monotonic() - start) * 1000)
        log.info(
            f"{LogTag.MCP} transparent reconnect succeeded for tool",
            integration_id=integration_id,
            tool_name=tool_name,
            latency_ms=latency_ms,
        )
        log.set_ns(
            "mcp",
            operation="connect",
            server_id=integration_id,
            tool_name=tool_name,
            success=True,
        )
        return result

    async def _reset_to_disconnected(self, integration_id: str) -> None:
        """Tear down a dead integration: Mongo status, PG creds, DCR client, Redis cache.

        Each step is swallowed so one failure doesn't block the rest.
        """

        async def _swallow(coro: Awaitable[object], what: str) -> None:
            try:
                await coro
            except Exception as e:
                log.warning(
                    f"{LogTag.MCP} failed during teardown",
                    integration_id=integration_id,
                    what=what,
                    error=str(e),
                    error_type=type(e).__name__,
                )

        await _swallow(
            update_user_integration_status(self.user_id, integration_id, "created"),
            "mongo status reset",
        )
        await _swallow(
            self.token_store.delete_credentials(integration_id),
            "credential delete",
        )
        await _swallow(
            self.token_store.delete_dcr_client(integration_id),
            "dcr client delete",
        )
        await _swallow(
            delete_cache(f"{OAUTH_DISCOVERY_PREFIX}:{integration_id}"),
            "oauth discovery cache clear",
        )

    async def _build_device_client(
        self, integration_id: str, mcp_config: MCPConfig
    ) -> BaseMCPClient:
        """Build an mcp_use client whose only session tunnels to a paired device.

        The device MCP server has no outbound URL, so we bypass config-based
        connector creation and inject a :class:DeviceConnector-backed session
        directly. Everything downstream (adapter, tool conversion) reads from
        get_all_active_sessions(), which this populates.
        """
        device_id, server_key = _parse_device_server_url(mcp_config.server_url)

        # Defense in depth (hard gate: user must own the device) — a leaked or
        # stale id can't cross the user boundary or reach a revoked device.
        # Deferred import: device-service loaded lazily until a paired-device tunnel is built.
        from app.services.device.device_service import (  # noqa: PLC0415 -- deferred
            get_active_device,
        )

        device = await get_active_device(device_id)
        if device is None or device.user_id != self.user_id:
            raise ValueError(
                f"Device {device_id} is not an active device owned by user {self.user_id}"
            )

        connector = DeviceConnector(device_id, server_key)
        session = MCPSession(connector, auto_connect=True)
        await session.initialize()

        client = BaseMCPClient(config={"mcpServers": {}})
        client.sessions[integration_id] = session
        if integration_id not in client.active_sessions:
            client.active_sessions.append(integration_id)
        return client

    async def _open_session(self, integration_id: str, mcp_config: MCPConfig) -> BaseMCPClient:
        """Create the MCP client and its session for one integration.

        Device servers have no outbound URL (device://...) and are reached over
        the tunnel, so the SSRF re-check below doesn't apply to them.
        """
        if mcp_config.transport == DEVICE_TRANSPORT:
            log.info(
                f"{LogTag.MCP} Opening device-tunnel MCP session", integration_id=integration_id
            )
            return await self._build_device_client(integration_id, mcp_config)

        # SSRF re-check (DNS-rebinding defense): the schema validator only did a
        # shape check at create/update time. Re-resolved here, before _build_config
        # (which can itself trigger outbound I/O via an OAuth refresh).
        await assert_endpoint_url_allowed(
            mcp_config.server_url, allow_private=settings.deployment.private_network_endpoints
        )

        config = await self._build_config(integration_id, mcp_config)

        log.info(
            f"{LogTag.MCP} Starting connection to MCP server",
            integration_id=integration_id,
            config=self._sanitize_config(config),
        )
        log.info(f"{LogTag.MCP} Creating BaseMCPClient instance", integration_id=integration_id)
        client = BaseMCPClient(config)
        log.info(
            f"{LogTag.MCP} Creating session with integration_id", integration_id=integration_id
        )
        await client.create_session(integration_id)
        log.info(f"{LogTag.MCP} Session created successfully", integration_id=integration_id)
        return client

    async def _convert_tools_safe(
        self, client: BaseMCPClient, integration_id: str
    ) -> list[BaseTool]:
        """Convert MCP tools via the resilient adapter, closing the session on failure."""
        # Use resilient adapter that handles invalid schemas gracefully
        # It will skip tools with bad schemas and return the ones that work
        adapter = ResilientLangChainAdapter()
        log.info(
            f"{LogTag.MCP} Converting MCP tools to LangChain format",
            integration_id=integration_id,
        )
        try:
            raw_tools = await adapter.create_tools(client)
        except Exception:
            # Session was created but tool conversion failed — close to avoid leak
            try:
                await client.close_all_sessions()
            except Exception as close_err:
                log.warning(
                    f"{LogTag.MCP} Failed to close leaked session",
                    integration_id=integration_id,
                    error=str(close_err),
                    error_type=type(close_err).__name__,
                )
            raise
        log.info(
            f"{LogTag.MCP} Successfully converted tools to LangChain format",
            integration_id=integration_id,
            raw_tools_count=len(raw_tools),
        )
        return raw_tools

    async def _user_server_tool_names(self, leaving: str | None) -> dict[str, ServerToolNames]:
        """Server-side tool names of the user's MCP integrations: warm ones from memory, other connected ones from Mongo.

        leaving is being disconnected: its stored record can still read connected here.
        """
        server_tools = {
            integration_id: live_server_tool_names(tools)
            for integration_id, tools in self._tools.items()
            if tools
        }
        records = [
            record
            for record in await connected_tool_records(self.user_id)
            if record.integration_id not in server_tools and record.integration_id != leaving
        ]
        if not records:
            return server_tools
        resolved = await asyncio.gather(
            *(IntegrationResolver.resolve(record.integration_id) for record in records)
        )
        # gather returns exactly one result per record, so zip's strict check can never trip
        for record, integration in zip(records, resolved, strict=True):  # pragma: no mutate
            # Composio integrations also store catalog tools; only MCP servers share a namespace here.
            if integration is not None and integration.mcp_config is not None:
                server_tools[record.integration_id] = ServerToolNames(
                    source_name=integration.name,
                    server_names=[tool.name for tool in record.tools],
                )
        return server_tools

    async def _gaia_tool_names(
        self,
        joining: dict[str, ServerToolNames],
        reserved: set[str],
        *,
        leaving: str | None = None,
    ) -> dict[str, dict[str, str]]:
        """GAIA-facing names for every user MCP integration, with joining overriding what is stored."""
        server_tools = {**await self._user_server_tool_names(leaving), **joining}
        return gaia_names_by_integration(server_tools, reserved)

    def _rename_warm_tools(self, names: dict[str, dict[str, str]]) -> None:
        for integration_id, tools in self._tools.items():
            if integration_id in names:
                apply_gaia_names(tools, names[integration_id])

    def _make_evict_callback(self, iid: str) -> Callable[[], None]:
        """Build a callback that evicts a stale session after a connection error.

        Pops from dicts and schedules async session close via fire-and-forget task.
        """

        def _evict() -> None:
            # Evict the in-memory cache to force a fresh _do_connect. Do NOT flip
            # MongoDB status here — a hiccup is usually transient; _do_connect's
            # exception path resets status only if the reconnect proves the credentials dead.
            stale_client = self._clients.pop(iid, None)
            self._tools.pop(iid, None)
            if stale_client:
                _spawn_background(
                    self._safe_close_client(stale_client),
                    f"evict_close_{iid}",
                )
            log.info(f"{LogTag.MCP} Evicted stale session after connection error", iid=iid)

        return _evict

    def _make_reconnect_callback(
        self, iid: str
    ) -> Callable[[str, dict[str, object]], Awaitable[object]]:
        async def _reconnect_and_retry(tool_name: str, kwargs: dict[str, object]) -> object:
            return await self.reconnect_and_call(iid, tool_name, kwargs)

        return _reconnect_and_retry

    @staticmethod
    async def _await_logged(
        integration_id: str, labelled: list[tuple[str, Awaitable[object]]]
    ) -> None:
        """Run independent post-connect writes concurrently, logging each outcome."""
        results = await asyncio.gather(*(task for _, task in labelled), return_exceptions=True)
        # gather returns exactly one result per task, so zip's strict check can never trip
        for (label, _), result in zip(labelled, results, strict=True):  # pragma: no mutate
            if isinstance(result, Exception):
                log.warning(
                    f"{LogTag.MCP} post-connect task failed",
                    integration_id=integration_id,
                    label=label,
                    error=str(result),
                    error_type=type(result).__name__,
                )
            else:
                log.info(
                    f"{LogTag.MCP} post-connect task ok",
                    integration_id=integration_id,
                    label=label,
                )

    async def _record_connection(self, mcp_config: MCPConfig, integration_id: str) -> None:
        """Write the connection state; awaited because ensure_connected trusts the DB status."""
        # Awaitable, not Coroutine: update_user_integration_status is wrapped in
        # @CacheInvalidator, whose decorator erases the coroutine type.
        labelled: list[tuple[str, Awaitable[object]]] = []
        if not mcp_config.requires_auth:
            labelled.append(
                ("store_unauthenticated", self.token_store.store_unauthenticated(integration_id))
            )
        labelled.append(
            (
                "update_status_connected",
                update_user_integration_status(self.user_id, integration_id, "connected"),
            )
        )
        await self._await_logged(integration_id, labelled)

    async def _persist_and_index_tools(
        self,
        resolved: ResolvedIntegration,
        mcp_config: MCPConfig,
        integration_id: str,
        index_tools: list[BaseTool],
    ) -> None:
        """Store the server's tool names in Mongo and index the tools in Chroma (off the connect path)."""
        # Mongo and Chroma are shared by every user of the integration, so they
        # hold user-independent identities: server names in Mongo (collision
        # naming is recomputed from them per user), GAIA-reserved renames only in Chroma.
        tool_metadata = [
            RawToolMetadata(name=server_name, description=server_description)
            for server_name, server_description in map(server_identity, index_tools)
        ]
        labelled: list[tuple[str, Awaitable[object]]] = [
            ("store_tools_mongo", store_mcp_tools(integration_id, tool_metadata))
        ]
        # Custom MCPs use a URL-derived namespace and register a subagent doc;
        # platform MCPs use tool_space. index_tools_to_store's Redis cache dedupes across users.
        if resolved.source == "custom":
            custom_doc = (
                Integration.model_validate(resolved.custom_doc) if resolved.custom_doc else None
            )
            labelled.append(
                (
                    "index_custom_chroma",
                    self._handle_custom_integration_connect(
                        integration_id,
                        mcp_config.server_url,
                        index_tools,
                        name=custom_doc.name if custom_doc else None,
                        description=custom_doc.description if custom_doc else None,
                    ),
                )
            )
        else:
            labelled.append(
                (
                    "index_platform_chroma",
                    self._index_platform_mcp_tools(integration_id, index_tools),
                )
            )
        await self._await_logged(integration_id, labelled)

        # The status mutator's decorator invalidates before its write, which raced
        # store_tools; bust once more now that tools are persisted so a concurrent
        # read can't cache an empty-but-connected catalog for the TTL.
        await invalidate_user_integration_caches(self.user_id)

    async def _handle_connect_failure(
        self,
        e: Exception,
        integration_id: str,
        mcp_config: MCPConfig,
    ) -> list[BaseTool] | None:
        """Shared connect-failure handling.

        Raises StepUpAuthRequiredError for 403 insufficient_scope, retries once
        via token refresh, marks missing credentials as needing OAuth, and tears
        down only demonstrably dead credentials. Returns None to re-raise.
        """
        error_str = str(e).lower()

        log.set_ns(
            "mcp",
            operation="connect",
            server_id=integration_id,
            success=False,
            error_type=type(e).__name__,
        )
        if isinstance(e, MCPAuthorizationRequiredError):
            if await self.token_store.get_refresh_token(integration_id) is not None:
                # Refresh retained: the grant may still recover, so keep the
                # saved status (a dead refresh is cleared separately).
                log.warning(
                    f"{LogTag.MCP} OAuth token unavailable but refresh retained for",
                    integration_id=integration_id,
                    user_id=self.user_id,
                )
                return None
            await update_user_integration_status(self.user_id, integration_id, "created")
            log.warning(
                f"{LogTag.MCP} OAuth authorization required for",
                integration_id=integration_id,
                user_id=self.user_id,
            )
            return None

        # Log comprehensive error details for debugging
        log.error(
            f"{LogTag.MCP} Connection failed with exception",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )

        # Check for 403 insufficient_scope per MCP spec
        # This indicates step-up authorization is needed
        if "403" in str(e) and "insufficient_scope" in error_str:
            # Try to extract required scopes from error message
            # Format: scope="required_scope1 required_scope2"
            scope_match = re.search(r'scope="([^"]+)"', str(e))
            required_scopes: list[str] = []
            if scope_match:
                required_scopes = scope_match.group(1).split()
            log.info(
                f"{LogTag.MCP} Step-up auth required",
                integration_id=integration_id,
                required_scopes=required_scopes,
            )
            raise StepUpAuthRequiredError(integration_id, required_scopes) from e

        # Retry once on auth-related failures: 401 (expired token) or
        # 405 (mcp-use OAuth fallback hit a wrong endpoint because the
        # token we passed was rejected). Refresh the token and retry.
        is_auth_error = (
            any(code in str(e) for code in ("401", "405", "403"))
            or "unauthorized" in error_str
            or "method not allowed" in error_str
        )
        refresh_attempted = integration_id in self._refresh_attempts
        if is_auth_error and mcp_config.requires_auth and not refresh_attempted:
            log.info(
                f"{LogTag.MCP} Auth-related connection failure, attempting token refresh and retry",
                integration_id=integration_id,
            )
            self._refresh_attempts.add(integration_id)
            refresh_attempted = True
            try:
                refreshed = await self._try_refresh_token(integration_id, mcp_config)
                if refreshed:
                    log.info(
                        f"{LogTag.MCP} Token refreshed, retrying connection",
                        integration_id=integration_id,
                    )
                    return await self._do_connect(integration_id)
                log.warning(
                    f"{LogTag.MCP} Token refresh failed, user may need to re-authorize",
                    integration_id=integration_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            finally:
                self._refresh_attempts.discard(integration_id)

        log.error(
            f"{LogTag.MCP} Failed to connect to MCP",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )

        # Only reset on demonstrably dead credentials — transient errors
        # (5xx, network blip, transport mismatch) keep the existing tokens.
        if is_terminal_auth_failure(e, refresh_attempted=refresh_attempted):
            # error_str is already lowered; the pattern is digits-only so case
            # cannot matter, but matching against it (not a fresh .lower())
            # keeps the normalization in exactly one place.
            if getattr(e, "response", None) is None and re.search(
                r"(?<![:\w/])(?:401|403)(?![\w/])", error_str
            ):
                log.warning(
                    f"{LogTag.MCP} Resetting on message-only status signal after refresh",
                    integration_id=integration_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            await self._reset_to_disconnected(integration_id)
        else:
            log.warning(
                f"{LogTag.MCP} Transient connection failure — keeping "
                f"connected status so next attempt retries with current tokens",
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )
        return None

    async def _do_connect(self, integration_id: str) -> list[BaseTool]:
        """Connect, with a single retry on auth failures (401, 405) that refreshes the token."""
        # Resolve integration from platform config or MongoDB
        resolved = await IntegrationResolver.resolve(integration_id)
        if not resolved or not resolved.mcp_config:
            raise ValueError(f"MCP integration {integration_id} not found")

        mcp_config = resolved.mcp_config
        is_custom = resolved.source == "custom"

        try:
            client = await self._open_session(integration_id, mcp_config)

            raw_tools = await self._convert_tools_safe(client, integration_id)
            stamp_tool_metadata(raw_tools, integration_id, mcp_config.server_url, resolved.name)
            joining = ServerToolNames(
                source_name=resolved.name, server_names=[tool.name for tool in raw_tools]
            )
            reserved = await reserved_tool_names()
            names = await self._gaia_tool_names({integration_id: joining}, reserved)
            renamed_tools = apply_gaia_names(raw_tools, names[integration_id])
            index_tools = shared_index_tools(raw_tools, joining, reserved)

            # CRITICAL: Wrap tools to filter None values before MCP invocation.
            # MCP servers expect optional params to be OMITTED, not sent as null.
            # Without this, Pydantic defaults (None) cause MCP validation errors.
            tools = wrap_tools_with_null_filter(
                raw_tools,
                on_connection_error=self._make_evict_callback(integration_id),
                reconnect_and_retry=self._make_reconnect_callback(integration_id),
            )

            # A newly shared name prefixes the already-warm integration's tool too.
            self._rename_warm_tools(names)
            self._clients[integration_id] = client
            self._tools[integration_id] = tools

            tool_names_sample = [t.name for t in tools[:5]]
            log.set_ns(
                "mcp",
                operation="connect",
                server_id=integration_id,
                tool_count=len(tools),
                success=True,
            )
            log.info(
                f"{LogTag.MCP} Connected to MCP, got tools for user",
                integration_id=integration_id,
                tools_count=len(tools),
                user_id=self.user_id,
                is_custom=is_custom,
                tool_names_sample=tool_names_sample,
                renamed_tools=renamed_tools,
            )

            await self._record_connection(mcp_config, integration_id)
            spawn_logged_task(
                "mcp_post_connect",
                self._persist_and_index_tools(resolved, mcp_config, integration_id, index_tools),
                integration_id=integration_id,
            )

            return tools

        except Exception as e:
            retried = await self._handle_connect_failure(e, integration_id, mcp_config)
            if retried is not None:
                return retried
            raise

    async def _index_platform_mcp_tools(self, integration_id: str, tools: list[BaseTool]) -> None:
        """Index platform MCP tools (e.g. posthog, deepwiki) to ChromaDB.

        Uses subagent_config.tool_space as the namespace; skips indexing if
        absent rather than falling back to integration_id, which can collide
        with a URL-derived custom-MCP namespace and silently corrupt
        retrieve_tools for the other integration.
        """
        from app.config.oauth_config import (  # noqa: PLC0415 -- oauth_config transitively imports the langchain tool subgraphs, far too heavy on this module's import path
            get_integration_by_id,
        )

        integration = get_integration_by_id(integration_id)
        namespace = (
            integration.subagent_config.tool_space
            if integration and integration.subagent_config
            else None
        )
        if not namespace:
            log.warning(
                f"{LogTag.MCP} platform integration has no subagent_config.tool_space; skipping Chroma indexing to avoid namespace collisions",
                integration_id=integration_id,
            )
            return

        try:
            tools_with_space = [(tool, namespace) for tool in tools]
            await index_tools_to_store(tools_with_space)
            log.info(
                f"{LogTag.MCP} indexed platform MCP tools to Chroma namespace",
                integration_id=integration_id,
                tools_count=len(tools),
                namespace=namespace,
            )
        except Exception as e:
            log.error(
                f"{LogTag.MCP} _index_platform_mcp_tools failed",
                integration_id=integration_id,
                namespace=namespace,
                error_type=type(e).__name__,
            )

    async def _handle_custom_integration_connect(
        self,
        integration_id: str,
        server_url: str,
        tools: list[BaseTool],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Handle custom integration: index tools and register as subagent."""
        namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)
        log.set_ns(
            "mcp",
            operation="connect",
            server_id=integration_id,
            tool_count=len(tools),
        )
        log.info(
            f"{LogTag.MCP} _handle_custom_integration_connect: indexed namespace tools",
            integration_id=integration_id,
            namespace=namespace,
            tools_count=len(tools),
        )

        # Index tools in ChromaDB for semantic discovery.
        # index_tools_to_store() manages its own Redis cache (chroma:indexed:{namespace})
        # with a 24h TTL and hash-based change detection — no need to duplicate here.
        try:
            tools_with_space = [(tool, namespace) for tool in tools]
            await index_tools_to_store(tools_with_space)
        except Exception as e:
            log.error(
                f"{LogTag.MCP} index_tools_to_store failed",
                integration_id=integration_id,
                namespace=namespace,
                error_type=type(e).__name__,
            )

        # Index as subagent for discovery via retrieve_tools
        try:
            store = await providers.aget("chroma_tools_store")
            if store:
                resolved_name = name
                resolved_description = description

                if resolved_name is None:
                    resolved = await IntegrationResolver.resolve(integration_id)
                    if resolved and resolved.custom_doc:
                        custom_doc = Integration.model_validate(resolved.custom_doc)
                        resolved_name = custom_doc.name
                        resolved_description = custom_doc.description

                if resolved_name:
                    await index_custom_mcp_as_subagent(
                        store=store,
                        request=CustomMcpIndexRequest(
                            integration_id=integration_id,
                            name=resolved_name,
                            description=resolved_description or "",
                            tools=tools,
                        ),
                    )
                    log.info(
                        f"{LogTag.MCP} Indexed custom MCP as subagent in namespace ('subagents',)",
                        integration_id=integration_id,
                        resolved_name=resolved_name,
                    )
                else:
                    log.warning(
                        f"{LogTag.MCP} no resolved_name; skipping subagent index (name will not be discoverable via retrieve_tools)",
                        integration_id=integration_id,
                    )
            else:
                log.warning(
                    f"{LogTag.MCP} chroma_tools_store provider unavailable; cannot index as subagent",
                    integration_id=integration_id,
                )
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} index_custom_mcp_as_subagent failed",
                integration_id=integration_id,
                error_type=type(e).__name__,
            )

    async def connect_after_oauth(self, integration_id: str) -> None:
        """Dispatch the full connect for a just-authorized integration in the background.

        Handshake, tools/list, schema conversion and indexing can take 5-15s for
        servers like posthog (339 tools), and the already-authenticated user
        shouldn't wait on it.
        """

        async def _bg_connect_after_oauth() -> None:
            try:
                await self.connect(integration_id)
                log.info(
                    f"{LogTag.MCP} background connect after OAuth succeeded",
                    integration_id=integration_id,
                )
            except Exception as e:
                is_auth_error = "401" in str(e) or "authentication" in str(e).lower()
                terminal = is_terminal_auth_failure(e) or is_auth_error
                log.error(
                    f"{LogTag.MCP} background connect after OAuth failed",
                    integration_id=integration_id,
                    error_type=type(e).__name__,
                    terminal=terminal,
                )
                if terminal:
                    await self._reset_to_disconnected(integration_id)

        bg_task = _spawn_background(_bg_connect_after_oauth(), f"oauth_bg_connect_{integration_id}")
        if bg_task is None:
            # No running loop (test contexts) — fall back to awaiting inline so
            # we don't silently lose the connect.
            await _bg_connect_after_oauth()

    async def _try_refresh_token(self, integration_id: str, mcp_config: MCPConfig) -> bool:
        """Attempt to refresh OAuth token using stored refresh_token."""
        oauth_config = await discover_oauth_config(self.token_store, integration_id, mcp_config)
        return await try_refresh_token(self.token_store, integration_id, mcp_config, oauth_config)

    async def drop_local(self, integration_id: str) -> None:
        """Close this process's session for an integration and rename the peers it forced a prefix on.

        Local only: it writes nothing, so it also serves an integration that is already
        disconnected or deleted elsewhere, which a full disconnect would recreate a row for.
        """
        # Clean up in-memory state with a tight timeout — mcp_use's
        # session.__aexit__ can block on the upstream MCP server's TCP close,
        # producing a "silent" multi-second gap. Local state still gets cleared.
        if integration_id in self._clients:
            try:
                await asyncio.wait_for(
                    self._clients[integration_id].close_all_sessions(),
                    timeout=2.0,
                )
            except TimeoutError:
                log.warning(
                    f"{LogTag.MCP} close_all_sessions timed out; proceeding with local cleanup. Upstream session may linger until server-side timeout.",
                    integration_id=integration_id,
                )
            except Exception as e:
                log.warning(
                    f"{LogTag.MCP} Error closing MCP session",
                    error=str(e),
                    error_type=type(e).__name__,
                    integration_id=integration_id,
                )
            del self._clients[integration_id]

        if integration_id in self._tools:
            del self._tools[integration_id]

        # A name this integration shared is no longer shared: drop the prefix it forced.
        if self._tools:
            names = await self._gaia_tool_names(
                {}, await reserved_tool_names(), leaving=integration_id
            )
            self._rename_warm_tools(names)

    async def disconnect(self, integration_id: str) -> None:
        """Disconnect from an MCP server.

        Revokes tokens (RFC 7009) in the background — local state invalidates
        first since the revoke can take up to 20s. Client cleanup is
        timeout-bounded (Loki trace 2026-05-26 12:04:53); also clears OAuth
        discovery cache and deletes PostgreSQL credentials.
        """
        # Fire-and-forget the upstream OAuth revoke — the user has already
        # been disconnected locally; provider-side revocation is best-effort.
        if (
            _spawn_background(
                revoke_integration_tokens(self.token_store, integration_id),
                f"revoke_{integration_id}",
            )
            is None
        ):
            # Tests or non-asyncio contexts — fall back to awaiting.
            await revoke_integration_tokens(self.token_store, integration_id)

        await self.drop_local(integration_id)

        # The stored tool list is the server's, shared by every user, so it stays: a
        # reader scopes it to a user through connected_tool_records.

        # Invalidate ChromaDB namespace cache so tools are re-indexed on reconnect
        try:
            resolved = await IntegrationResolver.resolve(integration_id)
            if resolved and resolved.mcp_config:
                server_url = resolved.mcp_config.server_url
                is_custom = resolved.source == "custom"
                namespace = derive_integration_namespace(
                    integration_id, server_url, is_custom=is_custom
                )
                await delete_cache(f"chroma:indexed:{namespace}")
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} Failed to invalidate ChromaDB cache",
                error=str(e),
                error_type=type(e).__name__,
                integration_id=integration_id,
            )

        # Wipe persistent auth artifacts (Mongo status, PG creds, DCR client,
        # Redis OAuth cache) via the shared teardown helper.
        await self._reset_to_disconnected(integration_id)

        log.info(f"{LogTag.MCP} Disconnected MCP", integration_id=integration_id)

    async def get_tools(self, integration_id: str) -> list[BaseTool]:
        """Get tools for a connected integration."""
        return self._tools.get(integration_id, [])

    def find_integration(self, tool_name: str) -> str | None:
        """Find which connected integration owns a given tool name.

        Returns the integration_id, or None if no connected MCP exposes the tool.
        Scans the in-memory _tools map; with ~N integrations × ~M tools per
        user this is sub-millisecond and avoids needing a separate reverse
        index (which would have to stay in sync with connect/disconnect).
        """
        for integration_id, tools in self._tools.items():
            for tool in tools:
                if tool.name == tool_name:
                    return integration_id
        return None

    async def resolve_tool_owner(self, tool_name: str) -> str | None:
        """Which of the user's connected MCP integrations exposes tool_name; the DB status is authoritative."""
        owner = self.find_integration(tool_name)
        if owner is None:
            names = await self._gaia_tool_names({}, await reserved_tool_names())
            # Another process may have renamed since these tools warmed; match the current names.
            self._rename_warm_tools(names)
            owner = next(
                (iid for iid, own in names.items() if tool_name in own.values()),
                None,
            )
            if owner is None:
                await self._connect_unlisted(listed=names.keys())
                owner = self.find_integration(tool_name)
        if owner is None or not await self._connected_in_db(owner):
            return None
        return owner

    async def _connect_unlisted(self, listed: Collection[str]) -> None:
        """Connect the user's connected MCPs that no name source covers, so their tools exist to match.

        An integration disconnected on master has no stored tool list until a connect
        rewrites it, so its names are known only once it is live. Bounded, and a connect
        also stores the list, so each integration is paid for once.
        """
        candidates = sorted(
            integration_id
            for integration_id in await get_connected_integration_ids(self.user_id)
            if integration_id not in listed and integration_id not in self._tools
        )
        resolved = await asyncio.gather(*(IntegrationResolver.resolve(iid) for iid in candidates))
        # gather returns exactly one result per candidate, so zip's strict check can never trip
        unlisted = [
            iid
            for iid, integration in zip(candidates, resolved, strict=True)  # pragma: no mutate
            if integration is not None and integration.mcp_config is not None
        ]
        for integration_id in unlisted[:MCP_UNLISTED_CONNECT_MAX]:
            log.info(
                f"{LogTag.MCP} Connecting an MCP with no stored tool list to resolve a tool name",
                integration_id=integration_id,
            )
            try:
                await self.connect(integration_id)
            except Exception as e:
                # One unreachable server must not hide the tools of the next.
                log.warning(
                    f"{LogTag.MCP} Unlisted MCP unreachable; its tools are not resolvable",
                    integration_id=integration_id,
                    error_type=type(e).__name__,
                )
        if len(unlisted) > MCP_UNLISTED_CONNECT_MAX:
            log.warning(
                f"{LogTag.MCP} More unlisted MCPs than one tool lookup connects",
                skipped=len(unlisted) - MCP_UNLISTED_CONNECT_MAX,
            )

    def is_connected(self, integration_id: str) -> bool:
        """Check if an integration is connected (in memory)."""
        return integration_id in self._clients

    def active_integration_ids(self) -> list[str]:
        """Return the integrations with a live client in this process."""
        return list(self._clients.keys())

    def session_for(self, integration_id: str) -> MCPSession | None:
        """Return the integration's live mcp_use session, or None when it has no client in memory."""
        client = self._clients.get(integration_id)
        if client is None:
            return None
        return client.get_session(integration_id)

    async def is_connected_db(self, integration_id: str) -> bool:
        """Check if integration is connected (in MongoDB user_integrations)."""
        return await user_integration_repository.is_connected(self.user_id, integration_id)

    async def _connected_in_db(self, integration_id: str) -> bool:
        """Read the DB status, dropping this process's session when another replica disconnected it."""
        if await self.is_connected_db(integration_id):
            return True
        if integration_id in self._tools or integration_id in self._clients:
            await self.drop_local(integration_id)
        return False

    async def ensure_connected(self, integration_id: str) -> list[BaseTool]:
        """Ensure connection to an MCP server, reconnecting via stored tokens if needed.

        DB status is checked before the warm _tools map (a transport cache
        only): disconnect() clears just the local process's dicts, so a
        revoked integration could stay live on other replicas (pool caps at
        5000, no TTL).
        """
        if not await self._connected_in_db(integration_id):
            raise ValueError(
                f"MCP {integration_id} not connected. User needs to complete OAuth flow."
            )

        if integration_id in self._tools:
            return self._tools[integration_id]

        return await self.connect(integration_id)

    async def _safe_close_client(self, client: BaseMCPClient) -> None:
        """Close a BaseMCPClient session, swallowing errors."""
        try:
            await client.close_all_sessions()
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} Error closing MCP client session",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def close_all_client_sessions(self) -> None:
        """Close all active MCP client sessions.

        Public method for graceful shutdown - used by MCPClientPool.
        """
        for integration_id in list(self._clients.keys()):
            try:
                await self._clients[integration_id].close_all_sessions()
            except Exception as e:
                log.warning(
                    f"{LogTag.MCP} Error closing MCP session for",
                    integration_id=integration_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )


async def get_mcp_client(user_id: str) -> MCPClient:
    """Get MCP client for a user from the pool."""
    pool = await get_mcp_client_pool()
    return await pool.get(user_id)


async def drop_local_sessions(integration_id: str, user_ids: Iterable[str]) -> None:
    """Drop this process's live sessions of a deleted integration for the given users."""
    pool = await get_mcp_client_pool()
    for user_id in user_ids:
        if (client := pool.peek(user_id)) is not None:
            await client.drop_local(integration_id)
