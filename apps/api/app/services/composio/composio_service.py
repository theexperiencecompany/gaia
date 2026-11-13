import asyncio
import time
from typing import cast

from composio import Composio, after_execute, before_execute, schema_modifier
from composio.types import Tool
import composio_client
from composio_client.types import (
    AuthConfigListParams,
    ConnectedAccountRetrieveResponse,
    ToolkitListParams,
    ToolkitRetrieveResponse,
)
from composio_client.types.auth_config_create_params import AuthConfig
from composio_client.types.auth_config_list_response import Item as AuthConfigItem
from composio_client.types.toolkit_list_response import Item as ToolkitListItem
from composio_client.types.trigger_instance_upsert_response import (
    TriggerInstanceUpsertResponse,
)
from pydantic import BaseModel, ConfigDict, Field

from app.config.oauth_config import get_composio_integrations_by_provider
from app.config.settings import settings
from app.constants.integrations import (
    COMPOSIO_ACCOUNT_LIST_LIMIT,
    COMPOSIO_AUTH_CONFIG_PAGE_SIZE,
    COMPOSIO_SERVICE_PROVIDER,
    COMPOSIO_TOOLKIT_PAGE_SIZE,
)
from app.constants.log_tags import LogTag
from app.constants.providers import CredentialProviderName
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from app.models.integrations.composio import ComposioConnectLink
from app.models.trigger_config import TriggerConfig

# Defensive: guarantees Composio's CustomTool monkey-patches run in any process
# that builds a Composio client, not just where an entrypoint imports app.patches.
# Without the user_id-injection patch, custom tools 500 with "Missing user_id in auth_credentials".
import app.patches  # noqa: F401 -- applies monkeypatches on import; must run before patched SDKs are used
from app.services.composio.auth_config_resolver import (
    auth_config_id_for,
    resolve_auth_configs,
)
from app.services.composio.custom_tools.registry import custom_tools_registry
from app.services.composio.langchain_composio_service import (
    LangchainProvider,
    StructuredTool,
)
from app.services.mcp.mcp_tools_service import RawToolMetadata, store_mcp_tools
from app.services.providers.provider_credentials_service import (
    ProviderConfig,
    resolved_config,
)
from app.utils.composio_hooks.registry import (
    master_after_execute_hook,
    master_before_execute_hook,
    master_schema_modifier,
)
from app.utils.exceptions import ProviderNotConfiguredError
from app.utils.query_utils import add_query_param
from shared.py.wide_events import log


class _ComposioEventTotals(BaseModel):
    """The totals this service accumulates on the wide event's composio namespace."""

    model_config = ConfigDict(extra="ignore")

    toolkits: list[str] = Field(default_factory=list)
    tools_loaded: int = 0


class _WideEventComposio(BaseModel):
    """The accumulated wide event, read only for its composio namespace."""

    model_config = ConfigDict(extra="ignore")

    composio: _ComposioEventTotals = Field(default_factory=_ComposioEventTotals)


def _composio_event_totals() -> _ComposioEventTotals:
    return _WideEventComposio.model_validate(log.get()).composio


def _callback_url(state_token: str) -> str:
    return add_query_param(settings.COMPOSIO_REDIRECT_URI, "state", state_token)


class ComposioService:
    """GAIA's Composio client: connect links, connected accounts, toolkits and triggers."""

    def __init__(self, api_key: str):
        from app.config.oauth_config import all_integrations

        toolkit_versions: dict[str, str] = {}
        for integration in all_integrations():
            if integration.composio_config and integration.composio_config.toolkit_version:
                toolkit_name = integration.composio_config.toolkit.lower()
                toolkit_versions[toolkit_name] = integration.composio_config.toolkit_version

        self.composio = Composio(
            provider=LangchainProvider(),
            api_key=api_key,
            timeout=120,
            toolkit_versions=toolkit_versions or None,
        )
        custom_tools_registry.initialize(self.composio)

    async def connect_account(
        self, provider: str, user_id: str, state_token: str
    ) -> ComposioConnectLink:
        """Mint a hosted Connect Link for this user; the account stays pending until they authorize it."""
        integration = get_composio_integrations_by_provider().get(provider)
        if integration is None:
            raise ValueError(f"Provider '{provider}' not supported")
        auth_config_id = await auth_config_id_for(integration)
        if auth_config_id is None:
            raise ValueError(f"{integration.name} is not set up on this instance")

        log.set(composio_provider=provider, composio_user_id=user_id)
        try:
            # link(), not initiate(): the legacy endpoint retires 2026-07-03 and
            # then raises ComposioLegacyConnectedAccountsEndpointRetiredError. Same
            # return shape/allow_multiple semantics; redirect now goes to Composio's hosted Connect Link.
            loop = asyncio.get_event_loop()
            connection_request = await loop.run_in_executor(
                None,
                lambda: self.composio.connected_accounts.link(
                    user_id=user_id,
                    auth_config_id=auth_config_id,
                    callback_url=_callback_url(state_token),
                    allow_multiple=True,
                ),
            )

            return {
                "status": "pending",
                "redirect_url": connection_request.redirect_url,
                "connection_id": connection_request.id,
            }
        except Exception as e:
            log.error(
                f"{LogTag.COMPOSIO} Error connecting for",
                provider=provider,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def reauthorize_account(
        self, connected_account_id: str, state_token: str
    ) -> ComposioConnectLink:
        """Start a fresh sign-in for an existing account, keeping its id (and so its place in GAIA)."""
        log.set(composio_connected_account_id=connected_account_id)
        refreshed = await asyncio.to_thread(
            self.composio.connected_accounts.refresh,
            connected_account_id,
            body_redirect_url=_callback_url(state_token),
        )
        if not refreshed.redirect_url:
            raise RuntimeError(
                f"Composio returned no sign-in URL for {connected_account_id} ({refreshed.status})"
            )
        return {
            "status": "pending",
            "redirect_url": refreshed.redirect_url,
            "connection_id": refreshed.id,
        }

    async def get_tools(
        self, tool_kit: str, exclude_tools: list[str] | None = None
    ) -> list[StructuredTool]:
        """Get tools for a toolkit with unified master hooks."""
        log.set(composio_toolkit=tool_kit)
        log.info(f"{LogTag.COMPOSIO} Loading toolkit...", tool_kit=tool_kit)

        tools = await asyncio.to_thread(
            lambda: self.composio.tools.get(
                user_id="",
                toolkits=[tool_kit],
                limit=1000,
            )
        )

        exclude_tools = exclude_tools or []
        tool_names = [t.name for t in tools]

        custom_tool_names = custom_tools_registry.get_tool_names(tool_kit)
        for custom_tool_name in custom_tool_names:
            if custom_tool_name not in tool_names:
                tool_names.append(custom_tool_name)
        master_before_modifier = before_execute(tools=tool_names)(master_before_execute_hook)
        master_after_modifier = after_execute(tools=tool_names)(master_after_execute_hook)
        master_schema_mod = schema_modifier(tools=tool_names)(master_schema_modifier)

        tools = await asyncio.to_thread(
            lambda: self.composio.tools.get(
                user_id="",
                toolkits=[tool_kit],
                modifiers=[
                    master_schema_mod,
                    master_before_modifier,
                    master_after_modifier,
                ],
                limit=1000,
            )
        )

        if custom_tool_names:
            custom_tools = await self.get_tools_by_name(custom_tool_names)
            seen_names = {tool.name for tool in tools}
            for tool in custom_tools:
                if tool.name in seen_names:
                    continue
                tools.append(tool)
                seen_names.add(tool.name)

        result = [tool for tool in tools if tool.name not in exclude_tools]
        await self._store_tool_metadata(tool_kit, result)
        totals = _composio_event_totals()
        log.set(
            composio={
                "toolkits": [*totals.toolkits, tool_kit],
                "tools_loaded": totals.tools_loaded + len(result),
            }
        )
        return result

    async def _store_tool_metadata(self, toolkit_name: str, tools: list) -> None:
        """Store Composio tool metadata in MongoDB for frontend visibility."""
        if not tools:
            return

        try:
            tool_metadata = [
                RawToolMetadata(name=t.name, description=getattr(t, "description", ""))
                for t in tools
            ]

            await store_mcp_tools(toolkit_name.lower(), tool_metadata)
            log.debug(
                f"{LogTag.COMPOSIO} Stored Composio tool metadata for",
                tool_metadata_count=len(tool_metadata),
                toolkit_name=toolkit_name,
            )
        except Exception as e:
            log.warning(
                f"{LogTag.COMPOSIO} Failed to store Composio tool metadata for",
                toolkit_name=toolkit_name,
                error=str(e),
                error_type=type(e).__name__,
            )

    async def get_tools_by_name(
        self,
        tool_names: list[str],
        use_before_hook: bool = True,
        use_after_hook: bool = True,
        use_schema_modifier: bool = True,
    ) -> list[StructuredTool]:
        """Get specific tools by names with unified master hooks."""
        log.set(composio_tool_names=tool_names, composio_tool_count=len(tool_names))
        start_time = time.time()

        modifiers = []

        if use_schema_modifier:
            master_schema_mod = schema_modifier(tools=tool_names)(master_schema_modifier)
            modifiers.append(master_schema_mod)

        if use_before_hook:
            master_before_modifier = before_execute(tools=tool_names)(master_before_execute_hook)
            modifiers.append(master_before_modifier)

        if use_after_hook:
            master_after_modifier = after_execute(tools=tool_names)(master_after_execute_hook)
            modifiers.append(master_after_modifier)

        result = await asyncio.to_thread(
            self.composio.tools.get,
            tools=tool_names,
            user_id="",
            modifiers=modifiers,
        )

        tools_time = time.time() - start_time
        log.info(
            f"{LogTag.COMPOSIO} Tools loaded: tools",
            result_count=len(result),
            tools_time=tools_time,
        )
        log.set(composio={"tools_loaded": _composio_event_totals().tools_loaded + len(result)})
        return result

    async def get_raw_tools_metadata(
        self,
        tool_kit: str | None = None,
        specific_tools: list[str] | None = None,
    ) -> list[Tool]:
        """Fetch raw Composio tool definitions without wrapping them.

        get_tools/get_tools_by_name wrap via LangchainProvider (~100KB per
        tool), the dominant source of resident memory across the ~1.6k-tool
        catalog. Warmup only needs name+description; StructuredTools
        materialize lazily per provider when a subagent is first created.
        """

        def _fetch() -> list[Tool]:
            if specific_tools:
                return self.composio.tools.get_raw_composio_tools(tools=specific_tools)
            return self.composio.tools.get_raw_composio_tools(toolkits=[tool_kit], limit=1000)

        return await asyncio.to_thread(_fetch)

    def get_tool(
        self,
        tool_name: str,
        use_before_hook: bool = True,
        use_after_hook: bool = True,
        use_schema_modifier: bool = True,
        user_id: str = "",
    ) -> StructuredTool | None:
        """Get a specific tool by name with configurable hooks."""
        try:
            modifiers = []

            if use_schema_modifier:
                master_schema_mod = schema_modifier(tools=[tool_name])(master_schema_modifier)
                modifiers.append(master_schema_mod)

            if use_before_hook:
                master_before_modifier = before_execute(tools=[tool_name])(
                    master_before_execute_hook
                )
                modifiers.append(master_before_modifier)

            if use_after_hook:
                master_after_modifier = after_execute(tools=[tool_name])(master_after_execute_hook)
                modifiers.append(master_after_modifier)

            tools = self.composio.tools.get(
                user_id=user_id,
                tools=[tool_name],
                modifiers=modifiers,
            )

            return tools[0] if tools else None
        except Exception as e:
            log.error(
                f"{LogTag.COMPOSIO} Error getting tool",
                tool_name=tool_name,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return None

    async def check_connection_status(self, providers: list[str], user_id: str) -> dict[str, bool]:
        """Check if a user has active connections for given providers."""
        log.set(composio_user_id=user_id, composio_providers=providers)
        result = dict.fromkeys(providers, False)
        resolved = await resolve_auth_configs()
        auth_config_provider_map: dict[str, str] = {}
        for provider in providers:
            integration = get_composio_integrations_by_provider().get(provider)
            auth_config = resolved.get(integration.id) if integration else None
            if auth_config is not None:
                auth_config_provider_map[auth_config.auth_config_id] = provider
        if not auth_config_provider_map:
            return result

        try:
            loop = asyncio.get_event_loop()
            user_accounts = await loop.run_in_executor(
                None,
                lambda: self.composio.connected_accounts.list(
                    user_ids=[user_id],
                    auth_config_ids=list(auth_config_provider_map),
                    statuses=["ACTIVE"],
                    limit=COMPOSIO_ACCOUNT_LIST_LIMIT,
                ),
            )

            for account in user_accounts.items:
                if not account.auth_config.is_disabled and account.status == "ACTIVE":
                    account_auth_config_id = account.auth_config.id
                    if account_auth_config_id in auth_config_provider_map:
                        result[auth_config_provider_map[account_auth_config_id]] = True

            return result

        except Exception as e:
            log.error(
                f"{LogTag.COMPOSIO} Error checking connection status for providers and user",
                providers=providers,
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return result

    async def list_enabled_auth_configs(self) -> list[AuthConfigItem]:
        """Return every enabled auth config in this key's Composio project, across all pages."""
        configs: list[AuthConfigItem] = []
        cursor: str | None = None  # pragma: no mutate — only read for truthiness
        while True:
            params: AuthConfigListParams = {"limit": COMPOSIO_AUTH_CONFIG_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            page = await asyncio.to_thread(self.composio.auth_configs.list, **params)
            configs.extend(item for item in page.items if item.status == "ENABLED")
            if not page.next_cursor:
                return configs
            cursor = page.next_cursor

    async def list_toolkits(self) -> list[ToolkitListItem]:
        """Return Composio's whole toolkit catalog, across all pages."""
        toolkits: list[ToolkitListItem] = []
        cursor: str | None = None  # pragma: no mutate — only read for truthiness
        while True:
            params: ToolkitListParams = {"limit": COMPOSIO_TOOLKIT_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            page = await asyncio.to_thread(self.composio.client.toolkits.list, **params)
            toolkits.extend(page.items)
            if not page.next_cursor:
                return toolkits
            cursor = page.next_cursor

    async def get_toolkit(self, slug: str) -> ToolkitRetrieveResponse:
        """Return one toolkit with its auth schemes and the fields each needs."""
        return await asyncio.to_thread(self.composio.toolkits.get, slug)

    async def create_auth_config(self, slug: str, options: AuthConfig) -> str:
        """Create an auth config for the toolkit in this key's project; return its id."""
        created = await asyncio.to_thread(
            self.composio.client.auth_configs.create, toolkit={"slug": slug}, auth_config=options
        )
        return created.auth_config.id

    def get_connected_account_by_id(
        self, connected_account_id: str
    ) -> ConnectedAccountRetrieveResponse | None:
        """Fetch one connected account by its nanoid, or None when Composio cannot return it."""
        try:
            connected_account = self.composio.connected_accounts.get(
                nanoid=connected_account_id,
            )
            return connected_account
        except Exception as e:
            log.error(
                f"{LogTag.COMPOSIO} Error retrieving connected account",
                connected_account_id=connected_account_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    async def delete_connected_account(self, connected_account_id: str) -> None:
        """Revoke one connected account on Composio; one Composio no longer has is already gone."""
        log.set(composio_connected_account_id=connected_account_id)
        try:
            await asyncio.to_thread(
                self.composio.connected_accounts.delete, nanoid=connected_account_id
            )
        except composio_client.NotFoundError:
            log.info(
                f"{LogTag.COMPOSIO} Connected account already gone on Composio",
                connected_account_id=connected_account_id,
            )

    async def delete_all_connected_accounts(self, user_id: str, provider: str) -> int:
        """Revoke every account, of any status, the user holds on the provider; returns how many."""
        log.set(composio_user_id=user_id, composio_provider=provider)
        integration = get_composio_integrations_by_provider().get(provider)
        if integration is None:
            raise ValueError(f"Provider '{provider}' not supported")
        auth_config_id = await auth_config_id_for(integration)
        if auth_config_id is None:
            log.info(
                f"{LogTag.COMPOSIO} Integration not set up on this instance; no accounts to revoke",
                provider=provider,
            )
            return 0
        user_accounts = await asyncio.to_thread(
            lambda: self.composio.connected_accounts.list(
                user_ids=[user_id],
                auth_config_ids=[auth_config_id],
                limit=COMPOSIO_ACCOUNT_LIST_LIMIT,
            )
        )
        await asyncio.gather(
            *(self.delete_connected_account(account.id) for account in user_accounts.items)
        )
        log.info(
            f"{LogTag.COMPOSIO} Deleted connected account(s) for user",
            deleted_count=len(user_accounts.items),
            provider=provider,
            user_id=user_id,
        )
        return len(user_accounts.items)

    async def handle_subscribe_trigger(
        self, user_id: str, connected_account_id: str, triggers: list[TriggerConfig]
    ) -> list[TriggerInstanceUpsertResponse] | None:
        """Subscribe one connected account to the integration's auto-active triggers."""
        log.set(
            composio_user_id=user_id,
            composio_connected_account_id=connected_account_id,
            composio_trigger_count=len(triggers),
        )
        active_triggers = [t for t in triggers if t.auto_activate]

        if not active_triggers:
            log.info(
                f"{LogTag.COMPOSIO} No auto-active triggers to subscribe for user", user_id=user_id
            )
            return []

        log.info(
            f"{LogTag.COMPOSIO} Subscribing to auto-active triggers for user",
            active_triggers_count=len(active_triggers),
            user_id=user_id,
        )

        try:

            def create_trigger(trigger: TriggerConfig) -> TriggerInstanceUpsertResponse:
                """Create one trigger instance on this connected account."""
                return self.composio.triggers.create(
                    connected_account_id=connected_account_id,
                    slug=trigger.slug,
                    trigger_config=trigger.config,
                )

            tasks = [
                asyncio.get_event_loop().run_in_executor(None, create_trigger, trigger)
                for trigger in active_triggers
            ]

            return await asyncio.gather(*tasks)
        except Exception as e:
            log.error(
                f"{LogTag.COMPOSIO} Error handling subscribe trigger for",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None


@lazy_provider(
    name=COMPOSIO_SERVICE_PROVIDER,
    # Empty on purpose: the key is resolved at LOAD time from the credential
    # store (see _load), so availability must not be decided by import-time
    # env — a key saved in Settings has to register the service.
    required_keys=[],
    strategy=MissingKeyStrategy.WARN,
    warning_message="Composio is not configured. Composio-backed integrations and tools will not work.",
)
def init_composio_service() -> ComposioService:
    """Build the Composio service from a store-first resolved key (sync: the SDK is synchronous)."""
    return ComposioService(_composio_api_key())


def _composio_api_key() -> str:
    """Return the store-first resolved Composio key; raise ProviderNotConfiguredError when none resolves."""
    config: ProviderConfig | None = resolved_config(CredentialProviderName.COMPOSIO)
    api_key = config.api_key if config else None
    if not api_key:
        raise ProviderNotConfiguredError(
            "COMPOSIO_KEY is not set in settings and no composio credential is stored"
        )
    return api_key


def get_composio_service() -> ComposioService:
    """Return the registered ComposioService.

    Raises ProviderNotConfiguredError when no key resolves, RuntimeError when
    a key resolves but the service failed to build.
    """
    service = providers.get(COMPOSIO_SERVICE_PROVIDER)
    if service is None:
        _composio_api_key()
        raise RuntimeError("ComposioService is not available")
    # providers.get() is typed Any | None; "composio_service" is always
    # registered via init_composio_service(), which returns ComposioService.
    return cast(ComposioService, service)
