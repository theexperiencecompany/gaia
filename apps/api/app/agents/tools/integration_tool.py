"""
Integration Management Tools.

Tools for listing, connecting, and managing user integrations.
"""

from typing import Annotated, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.integrations import (
    MAX_AVAILABLE_FOR_LLM,
    MAX_CONNECTED_FOR_LLM,
    MAX_SUGGESTED_FOR_LLM,
)
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators import with_doc
from app.helpers.integration_helpers import build_search_patterns, normalize_server_url
from app.helpers.slug_helpers import generate_integration_slug
from app.models.agent_models import agent_configurable
from app.models.device import Device
from app.models.device_models import DeviceInfo, DeviceServerInfo, ListDevicesResult
from app.models.integration_models import (
    AuthType,
    CreateCustomIntegrationRequest,
    Integration,
    IntegrationInfo,
    ListIntegrationsResult,
    SuggestedIntegration,
)
from app.models.mcp_config import McpProbeResult
from app.services.device.bridge import online_device_ids
from app.services.device.device_service import (
    list_device_servers,
    list_devices as list_devices_service,
)
from app.services.integrations.custom_crud import (
    create_and_connect_custom_integration,
    create_custom_integration,
)
from app.services.mcp.device_exec import DeviceExecError, run_device_command
from app.services.mcp.mcp_client import MCPClient, get_mcp_client
from app.services.oauth.oauth_service import (
    check_integration_status as check_single_integration_status,
    check_multiple_integrations_status,
)
from app.templates.docstrings.integration_tool_docs import (
    ADD_CUSTOM_MCP_SERVER,
    ADD_DEVICE,
    APPROVE_DEVICE_PAIRING,
    CHECK_INTEGRATIONS_STATUS,
    CONNECT_INTEGRATION,
    LIST_DEVICES,
    LIST_INTEGRATIONS,
    RUN_ON_DEVICE,
)
from app.utils.device_onboarding import request_device_approval, request_device_onboarding
from app.utils.integration_checker import request_integration_connection
from app.utils.url_safety import assert_safe_url_shape
from shared.py.wide_events import log


class _ConfiguredUser(BaseModel):
    """The run's ``user_id``, read off its ``AgentConfigurable``."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None


def _configured_user_id(config: RunnableConfig) -> str | None:
    return _ConfiguredUser.model_validate(agent_configurable(config)).user_id


class _IntegrationLists:
    """The connected/available split, plus every id already listed for the user."""

    def __init__(self) -> None:
        self.connected: list[IntegrationInfo] = []
        self.available: list[IntegrationInfo] = []
        self.listed_ids: set[str] = set()

    def add(self, info: IntegrationInfo, integration_id: str, is_connected: bool) -> None:
        self.listed_ids.add(integration_id)
        (self.connected if is_connected else self.available).append(info)


async def _add_platform_integrations(lists: _IntegrationLists, user_id: str) -> None:
    """Platform integrations with their connection status."""
    platform_ids = [i.id for i in OAUTH_INTEGRATIONS if i.available]
    status_map = await check_multiple_integrations_status(platform_ids, user_id)

    for integration in OAUTH_INTEGRATIONS:
        if not integration.available:
            continue

        is_connected = status_map.get(integration.id, False)
        info: IntegrationInfo = {
            "id": integration.id,
            "name": integration.name,
            "description": integration.description,
            "category": integration.category,
            "connected": is_connected,
        }
        lists.add(info, integration.id, is_connected)


async def _add_custom_integrations(lists: _IntegrationLists, user_id: str) -> set[str]:
    """The user's custom integrations; returns the ids the user has added."""
    user_integrations = await user_integration_repository.list_for_user(user_id)
    user_integration_ids = {ui.integration_id for ui in user_integrations}

    if user_integration_ids:
        custom_docs = await integration_repository.find_custom_by_ids(list(user_integration_ids))
        for doc in custom_docs:
            integration_id = doc.integration_id
            is_connected = await user_integration_repository.is_connected(user_id, integration_id)

            custom_info: IntegrationInfo = {
                "id": integration_id,
                "name": doc.name,
                "description": doc.description,
                "category": doc.category,
                "connected": is_connected,
            }
            lists.add(custom_info, integration_id, is_connected)

    return user_integration_ids


def _stream_frame(suggested: SuggestedIntegration) -> dict[str, object]:
    """A suggested integration as the frontend's camelCase stream frame."""
    return {
        "id": suggested["id"],
        "name": suggested["name"],
        "description": suggested["description"],
        "category": suggested["category"],
        "iconUrl": suggested["icon_url"],
        "authType": suggested["auth_type"],
        "relevanceScore": suggested["relevance_score"],
        "slug": suggested["slug"],
    }


async def _search_suggested(query: str, exclude_ids: set[str]) -> list[SuggestedIntegration]:
    """Public integrations matching query, excluding ids the user already has."""
    suggested_list: list[SuggestedIntegration] = []
    try:
        log.info(f"{LogTag.TOOL} Searching public integrations", query=query)

        # Flexible word-based search (regex construction lives in the repo)
        words = build_search_patterns(query)

        docs = await integration_repository.search_public(
            words=words,
            query=query,
            exclude_ids=list(exclude_ids),
            limit=MAX_SUGGESTED_FOR_LLM,
        )

        for doc in docs:
            iid = doc.integration_id
            log.info(
                f"{LogTag.TOOL} Found public integration",
                integration_id=iid,
                integration_name=doc.name,
            )

            suggested_list.append(
                {
                    "id": iid,
                    "name": doc.name,
                    "description": doc.description,
                    "category": doc.category,
                    "icon_url": doc.icon_url,
                    "auth_type": doc.mcp_config.auth_type if doc.mcp_config else None,
                    "relevance_score": 1.0,  # All matches are equal with regex
                    "slug": generate_integration_slug(
                        name=doc.name,
                        category=doc.category,
                    ),
                }
            )

        log.info(
            f"{LogTag.TOOL} Found public integrations",
            integration_count=len(suggested_list),
        )

    except Exception as e:
        log.warning(
            f"{LogTag.TOOL} Failed to search public integrations",
            error_type=type(e).__name__,
        )

    return suggested_list


@tool
@with_doc(LIST_INTEGRATIONS)
async def list_integrations(
    config: RunnableConfig,
    search_public_query: Annotated[
        str | None,
        "Search query to discover public integrations from the marketplace. "
        "Use natural language like 'API testing', 'email automation', 'project management'. "
        "Leave empty to just show user's current integrations.",
    ] = None,
) -> ListIntegrationsResult | str:
    """
    List user integrations and optionally search for suggested public integrations.

    Returns structured data for LLM context and streams suggested integrations
    to the frontend for the 'Discover More' section.
    """
    try:
        log.set(tool={"name": "list_integrations", "action": "list"})
        user_id = _configured_user_id(config)
        if not user_id:
            return "Error: User ID not found in configuration."

        writer = get_stream_writer()

        lists = _IntegrationLists()
        await _add_platform_integrations(lists, user_id)
        user_integration_ids = await _add_custom_integrations(lists, user_id)

        # Search for suggested public integrations if query provided
        suggested_list: list[SuggestedIntegration] = []
        if search_public_query and search_public_query.strip():
            # Exclude IDs the user already has
            suggested_list = await _search_suggested(
                search_public_query.strip(), lists.listed_ids | user_integration_ids
            )

        # Stream suggested integrations to frontend (camelCase)
        writer(
            {
                "integration_list_data": {
                    "hasSuggestions": len(suggested_list) > 0,
                    "suggested": [_stream_frame(s) for s in suggested_list[:MAX_SUGGESTED_FOR_LLM]],
                }
            }
        )

        # Return structured data for LLM (with limits)
        return {
            "connected": lists.connected[:MAX_CONNECTED_FOR_LLM],
            "available": lists.available[:MAX_AVAILABLE_FOR_LLM],
            "suggested": suggested_list[:MAX_SUGGESTED_FOR_LLM],
        }

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error listing integrations", error_type=type(e).__name__)
        return f"Error listing integrations: {e!s}"


@tool
async def suggest_integrations(
    query: Annotated[
        str,
        "Search query to find relevant public integrations from the marketplace. "
        "Examples: 'email tools', 'project management', 'social media', 'CRM', 'Slack alternatives'",
    ],
    config: RunnableConfig,
) -> ListIntegrationsResult | str:
    """
    Search for and suggest public integrations from the marketplace based on a query.

    Use this tool when the user wants to discover new integrations, find alternatives,
    or explore what's available in a specific category.

    This tool will search the marketplace and display suggested integrations
    that the user can add with one click.
    """
    # list_integrations itself declares this exact return type; .ainvoke() is the
    # BaseTool framework boundary and always types its result `Any`.
    return cast(
        "ListIntegrationsResult | str",
        await list_integrations.ainvoke({"search_public_query": query}, config=config),
    )


@tool
@with_doc(CONNECT_INTEGRATION)
async def connect_integration(
    integration_ids: Annotated[
        list[str],
        "List of exact integration IDs to connect (e.g., ['gmail', 'notion', 'twitter']).",
    ],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "connect_integration", "action": "connect"})
        user_id = _configured_user_id(config)
        if not user_id:
            return "Error: User ID not found in configuration."

        # The Pydantic args_schema declares list[str], but a direct/programmatic
        # invocation can still hand this a bare string — widen before narrowing.
        raw_integration_ids = cast("list[str] | str", integration_ids)
        if isinstance(raw_integration_ids, str):
            integration_ids = [raw_integration_ids]
        integration_ids = list(
            dict.fromkeys(iid.lower().strip() for iid in integration_ids if iid.strip())
        )

        writer = get_stream_writer()

        results = []
        connections_to_initiate = []

        for integration_id in integration_ids:
            integration = next(
                (integ for integ in OAUTH_INTEGRATIONS if integ.id.lower() == integration_id),
                None,
            )

            if not integration:
                available = [i.id for i in OAUTH_INTEGRATIONS if i.available]
                results.append(
                    f"❌ '{integration_id}' not found. "
                    f"Available IDs: {', '.join(available[:5])}{'...' if len(available) > 5 else ''}"
                )
                continue

            if not integration.available:
                results.append(f"⏳ {integration.name} is not available yet. Coming soon!")
                continue

            is_connected = await check_single_integration_status(integration.id, user_id)
            if is_connected:
                results.append(f"✅ {integration.name} is already connected!")
                continue

            connections_to_initiate.append(integration)

        for integration in connections_to_initiate:
            writer({"progress": f"Initiating {integration.name} connection..."})
            results.append(
                await request_integration_connection(integration.id, integration.name, str(user_id))
            )

        return "\n".join(results) if results else "No integrations to connect."

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error connecting integrations",
            integration_ids=integration_ids,
            error_type=type(e).__name__,
        )
        return f"Error connecting integrations: {e!s}"


@tool
@with_doc(CHECK_INTEGRATIONS_STATUS)
async def check_integrations_status(
    integration_names: Annotated[
        list[str],
        "List of integration names or IDs to check status for (e.g., ['gmail', 'notion'])",
    ],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "check_integrations_status", "action": "check"})
        user_id = _configured_user_id(config)
        if not user_id:
            return "Error: User ID not found in configuration."

        results = []

        for integration_name in integration_names:
            search_name = integration_name.lower().strip()
            integration = None

            for integ in OAUTH_INTEGRATIONS:
                if (
                    integ.id.lower() == search_name
                    or integ.name.lower() == search_name
                    or (integ.short_name and integ.short_name.lower() == search_name)
                ):
                    integration = integ
                    break

            if not integration:
                results.append(f"❓ {integration_name}: Not found")
                continue

            # Use unified status checker
            is_connected = await check_single_integration_status(integration.id, user_id)
            status = "✅ Connected" if is_connected else "⚪ Not Connected"
            results.append(f"{integration.name}: {status}")

        return "\n".join(results)

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error checking integration status", error_type=type(e).__name__)
        return f"Error checking status: {e!s}"


def _reject_custom_mcp_add(server_url: str, name: str) -> str | None:
    """A user-facing rejection if this server can't be added as custom, else None.

    Rejects an unsafe/malformed URL, or a name that collides with a built-in
    catalog connector (which must be connected, not re-added as custom)."""
    # Cheap, non-resolving SSRF/shape guard (the request model carries no
    # validators); the DNS-resolving guard fires again inside probe/connect.
    try:
        assert_safe_url_shape(server_url)
    except ValueError as e:
        return f"❌ That server URL can't be used: {e}"

    search_name = name.lower().strip()
    catalog = next(
        (
            integ
            for integ in OAUTH_INTEGRATIONS
            if integ.id.lower() == search_name
            or integ.name.lower() == search_name
            or (integ.short_name and integ.short_name.lower() == search_name)
        ),
        None,
    )
    if catalog:
        return (
            f"{catalog.name} is a built-in integration; use connect_integration with id "
            f"'{catalog.id}' instead of adding it as a custom MCP server."
        )
    return None


async def _reuse_existing_custom_server(existing: Integration, user_id: str) -> str:
    """A server at this URL already exists — report it or hand off to reconnect."""
    if await user_integration_repository.is_connected(user_id, existing.integration_id):
        return f"✅ {existing.name} is already added and connected."
    return await request_integration_connection(existing.integration_id, existing.name, user_id)


async def _create_and_report_custom_server(
    user_id: str, name: str, server_url: str, probe: McpProbeResult, mcp_client: MCPClient
) -> str:
    """Create the custom integration from a successful probe and report the outcome.

    A bearer server needs a secret we must never take through chat, so it is created
    and handed to the secure UI card rather than connected here."""
    requires_auth = bool(probe.get("requires_auth"))
    probed_type = probe.get("auth_type")

    # description/is_public/bearer_token are left at their model defaults
    # (None/False/None) — in particular the token is never set here: the secret
    # is collected by the secure card, never through the LLM.
    if requires_auth and probed_type == "bearer":
        integration = await create_custom_integration(
            user_id,
            CreateCustomIntegrationRequest(
                name=name,
                server_url=server_url,
                requires_auth=True,
                auth_type="bearer",
            ),
        )
        return await request_integration_connection(integration.integration_id, name, user_id)

    resolved_type = cast(
        AuthType | None, probed_type if probed_type in ("none", "oauth", "bearer") else None
    )
    integration, connection = await create_and_connect_custom_integration(
        user_id,
        CreateCustomIntegrationRequest(
            name=name,
            server_url=server_url,
            requires_auth=requires_auth,
            auth_type=resolved_type,
        ),
        mcp_client,
    )
    status = connection.get("status")
    if status == "connected":
        count = connection.get("tools_count") or 0
        return f"✅ Added and connected {integration.name} ({count} tools available)."
    if status == "requires_oauth":
        return await request_integration_connection(integration.integration_id, name, user_id)
    return (
        f"❌ Added {name} but couldn't connect: {connection.get('error', 'unknown error')}. "
        f"It's saved (id {integration.integration_id}); you can ask me to retry connecting it."
    )


@tool
@with_doc(ADD_CUSTOM_MCP_SERVER)
async def add_custom_mcp_server(
    server_url: Annotated[
        str,
        "The exact MCP server endpoint URL resolved from the vendor's docs via web search "
        "(e.g. 'https://mcp.sentry.dev/mcp'). Never guess it.",
    ],
    name: Annotated[str, "Human-facing server name, e.g. 'Sentry'."],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "add_custom_mcp_server", "action": "create"})
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."
        user_id = str(user_id)

        rejection = _reject_custom_mcp_add(server_url, name)
        if rejection:
            return rejection

        normalized_url = normalize_server_url(server_url)
        mcp_client = await get_mcp_client(user_id=user_id)

        # Idempotency: reuse an existing server at the same URL rather than duplicating.
        existing = await integration_repository.find_custom_by_server_url(normalized_url, user_id)
        if existing:
            return await _reuse_existing_custom_server(existing, user_id)

        # Probe and persist the exact user-provided URL: normalization is for
        # dedup only, and some servers distinguish /mcp from /mcp/.
        original_url = server_url.strip()
        probe = await mcp_client.probe_connection(original_url)
        if probe.get("error"):
            return f"❌ Couldn't reach that MCP server: {probe['error']}"

        return await _create_and_report_custom_server(
            user_id, name, original_url, probe, mcp_client
        )
    except Exception as e:
        log.error(f"{LogTag.TOOL} Error adding custom MCP server", error_type=type(e).__name__)
        return f"Error adding MCP server: {e!s}"


@tool
@with_doc(LIST_DEVICES)
async def list_devices(config: RunnableConfig) -> ListDevicesResult | str:
    try:
        log.set(tool={"name": "list_devices", "action": "list"})
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        devices = await list_devices_service(str(user_id))
        device_ids = [d.id for d in devices]
        online = await online_device_ids(device_ids)
        servers_by_device = await list_device_servers(device_ids)

        return ListDevicesResult(
            devices=[
                DeviceInfo(
                    id=d.id,
                    name=d.name,
                    platform=d.platform,
                    online=d.id in online,
                    last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
                    servers=[
                        DeviceServerInfo(
                            server_key=s.server_key,
                            display_name=s.display_name,
                            integration_id=s.integration_id,
                            kind=s.kind,
                            status=s.status.value,
                            tools_synced_at=(
                                s.tools_synced_at.isoformat() if s.tools_synced_at else None
                            ),
                        )
                        for s in servers_by_device.get(d.id, [])
                    ],
                )
                for d in devices
            ]
        )
    except Exception as e:
        log.error(f"{LogTag.TOOL} Error listing devices", error_type=type(e).__name__)
        return f"Error listing devices: {e!s}"


@tool
@with_doc(ADD_DEVICE)
async def add_device() -> str:
    log.set(tool={"name": "add_device", "action": "onboard"})
    return request_device_onboarding()


@tool
@with_doc(APPROVE_DEVICE_PAIRING)
async def approve_device_pairing(user_code: str) -> str:
    log.set(tool={"name": "approve_device_pairing", "action": "surface_approval"})
    code = (user_code or "").strip()
    if not code:
        return (
            "Ask the user for the pairing code that `gaia bridge login` printed, "
            "then call this again with it."
        )
    return request_device_approval(code)


def _full_disk_access_hint(device: Device) -> str:
    """Guidance appended when a device command hits a macOS TCC (privacy) block.

    The grantee differs by client: the desktop app is itself the grantee (reopen
    it), while the CLI daemon inherits its terminal's grant (restart it)."""
    if device.client == "desktop":
        fix = (
            "This device is the GAIA desktop app. Tell the user to grant it Full Disk "
            "Access in System Settings > Privacy & Security > Full Disk Access (enable "
            "GAIA), then reopen the app — the grant carries into the commands it runs."
        )
    else:
        fix = (
            "This device is the gaia CLI. Tell the user to grant their terminal Full Disk "
            "Access in System Settings > Privacy & Security > Full Disk Access, then "
            "restart the bridge with `gaia bridge down && gaia bridge up`."
        )
    return (
        "\nmacOS blocked this path with its privacy protection (TCC); you cannot grant "
        f"this yourself. {fix} They can open that pane with "
        '`open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`.'
    )


@tool
@with_doc(RUN_ON_DEVICE)
async def run_on_device(device_id: str, command: str, config: RunnableConfig) -> str:
    log.set(tool={"name": "run_on_device", "action": "exec"})
    configurable = agent_configurable(config)
    user_id = configurable.get("user_id") if configurable else None
    if not user_id:
        return "Error: User ID not found in configuration."

    # Authz: the device must belong to this user. Never trust a device_id the
    # model produced — a wrong or spoofed id must not reach another user's machine.
    devices = await list_devices_service(str(user_id))
    device = next((d for d in devices if d.id == device_id), None)
    if device is None:
        return (
            f"No device '{device_id}' is linked to your account. "
            "Call list_devices to see your paired machines and their ids."
        )

    try:
        result = await run_device_command(device_id, command)
    except DeviceExecError as e:
        return f"Could not run the command: {e}"
    except Exception as e:
        log.error(f"{LogTag.TOOL} Error running command on device", error_type=type(e).__name__)
        return f"Error running the command: {e!s}"

    parts = [f"exit code: {result.exit_code}"]
    if result.stdout:
        parts.append(f"--- stdout ---\n{result.stdout}")
    if result.stderr:
        parts.append(f"--- stderr ---\n{result.stderr}")
    if not result.stdout and not result.stderr:
        parts.append("(no output)")
    if result.truncated:
        parts.append("(output truncated: command produced more than the cap)")
    # macOS TCC denies protected folders (Downloads/Desktop/Documents) without Full
    # Disk Access: reopen the desktop app (grantee) or restart the CLI daemon
    # (inherits its grant). Checks `result.stderr` first, not `(stderr or "")`, to kill a None-vs-"" mutant.
    if result.stderr and "operation not permitted" in result.stderr.lower():
        parts.append(_full_disk_access_hint(device))
    return "\n".join(parts)


# Export all tools
tools = [
    list_integrations,
    suggest_integrations,
    connect_integration,
    check_integrations_status,
    add_custom_mcp_server,
    list_devices,
    add_device,
    approve_device_pairing,
    run_on_device,
]
