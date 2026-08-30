"""
Provider Metadata Service

Service for fetching and storing provider-specific user metadata (e.g., username)
when OAuth integrations are connected. This metadata is used to enhance agent
system prompts with user context.
"""

import json
from typing import TYPE_CHECKING, Any

from app.config.oauth_config import get_integration_by_id
from app.constants.cache import PROVIDER_METADATA_CACHE_TTL
from app.db.repositories.users import user_repository
from app.decorators.caching import Cacheable, CacheInvalidator
from shared.py.wide_events import log

if TYPE_CHECKING:
    from app.services.composio.composio_service import ComposioService


def get_composio_service() -> "ComposioService":
    """Resolve the Composio service at call time rather than importing
    ``app.services.composio.composio_service`` (Composio SDK, ``app.patches``,
    every custom tool: seconds of import) into everything that imports this
    module, e.g. the agent context sections."""
    from app.services.composio.composio_service import (  # noqa: PLC0415 -- defers the Composio SDK import chain out of module import
        get_composio_service as _get_composio_service,
    )

    return _get_composio_service()


def _extract_nested_field(data: dict[str, Any], field_path: str) -> str | None:
    """Extract a value from a nested dict using dot-notation (e.g. "data.login")."""
    try:
        keys = field_path.split(".")
        value: Any = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return str(value) if value is not None else None
    except Exception as e:
        log.error(
            "Error extracting field",
            field_path=field_path,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def fetch_tool_response(
    user_id: str, tool_name: str, integration_id: str
) -> dict[str, Any] | None:
    """Call a single tool and return its raw response dict, or None on failure."""
    log.set(
        provider_metadata_user_id=user_id,
        provider_metadata_tool=tool_name,
        provider_metadata_integration=integration_id,
    )
    try:
        composio_service = get_composio_service()

        # Get the tool without hooks (we just need the data)
        tool = composio_service.get_tool(
            tool_name=tool_name,
            use_before_hook=False,
            use_after_hook=False,
            user_id=user_id,
        )

        if not tool:
            log.error(
                "Tool not found for",
                tool_name=tool_name,
                integration_id=integration_id,
                user_id=user_id,
            )
            return None

        # Execute the tool to get user info
        result = await tool.ainvoke({})
        data = result.get("data", {})

        log.info(
            "Fetched provider metadata tool result",
            tool_name=tool_name,
            integration_id=integration_id,
            data_type=type(data).__name__,
        )

        # Handle different response types
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                log.warning(
                    "Could not parse tool response as JSON",
                    tool_name=tool_name,
                    response_length=len(data),
                )
                return None
            if isinstance(parsed, dict):
                return parsed
            log.warning(
                "Tool response JSON was not an object",
                tool_name=tool_name,
                data_type=type(parsed).__name__,
            )
            return None
        log.warning(
            "Unexpected response type from tool",
            tool_name=tool_name,
            data_type=type(data).__name__,
        )
        return None

    except Exception as e:
        log.error(
            "Error fetching for",
            tool_name=tool_name,
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


async def fetch_provider_user_info(user_id: str, integration_id: str) -> dict[str, str] | None:
    """Fetch user info from a provider, calling each tool in metadata_config and
    extracting its configured variables into a name -> value dict (or None)."""
    log.set(provider_metadata_user_id=user_id, provider_metadata_integration=integration_id)
    integration = get_integration_by_id(integration_id)

    if not integration or not integration.metadata_config:
        log.debug("No metadata config for integration", integration_id=integration_id)
        return None

    metadata: dict[str, str] = {}

    # Iterate through each tool configuration
    for tool_config in integration.metadata_config.tools:
        # Fetch response from this tool
        response = await fetch_tool_response(user_id, tool_config.tool, integration_id)

        if not response:
            log.warning(
                "Failed to fetch provider metadata, skipping",
                tool=tool_config.tool,
                integration_id=integration_id,
                user_id=user_id,
            )
            continue

        # Extract each configured variable from the response
        for var in tool_config.variables:
            value = _extract_nested_field(response, var.field_path)
            if value:
                metadata[var.name] = value
                log.debug("Extracted = from", name=var.name, value=value, tool=tool_config.tool)
            else:
                log.warning(
                    "Could not extract from in response",
                    name=var.name,
                    field_path=var.field_path,
                    tool=tool_config.tool,
                    user_id=user_id,
                    integration_id=integration_id,
                )

    return metadata if metadata else None


@CacheInvalidator(key_patterns=["provider_metadata:{user_id}:{provider}"])
async def store_provider_metadata(user_id: str, provider: str, metadata: dict[str, str]) -> bool:
    """Store provider metadata in the user's document. Returns success."""
    log.set(
        provider_metadata_user_id=user_id,
        provider_metadata_provider=provider,
        provider_metadata_keys=list(metadata.keys()),
    )
    try:
        stored = await user_repository.set_provider_metadata(user_id, provider, metadata)

        if stored:
            log.info(
                "Stored metadata for user", provider=provider, user_id=user_id, metadata=metadata
            )
            return True
        log.warning("No document updated for user", user_id=user_id)
        return False

    except Exception as e:
        log.error(
            "Error storing metadata for user",
            provider=provider,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return False


@Cacheable(
    key_pattern="provider_metadata:{user_id}:{provider}",
    ttl=PROVIDER_METADATA_CACHE_TTL,
)
async def get_provider_metadata(user_id: str, provider: str) -> dict[str, str] | None:
    """Retrieve provider metadata for a user, or None if not found."""
    try:
        user = await user_repository.get(user_id)

        if not user:
            return None

        metadata = (user.provider_metadata or {}).get(provider)
        return metadata if isinstance(metadata, dict) else None

    except Exception as e:
        log.error(
            "Error getting metadata for user",
            provider=provider,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


async def fetch_and_store_provider_metadata(user_id: str, integration_id: str) -> bool:
    """Fetch user info from a provider and store its metadata. Returns success.

    Main entry point called after an OAuth connection succeeds.
    """
    integration = get_integration_by_id(integration_id)

    if not integration:
        log.debug("Integration not found", integration_id=integration_id)
        return False

    if not integration.metadata_config:
        log.debug("No metadata config for integration", integration_id=integration_id)
        return False

    # Fetch and extract metadata from all configured tools
    metadata = await fetch_provider_user_info(user_id, integration_id)

    if not metadata:
        log.warning(
            "Failed to fetch/extract metadata for", integration_id=integration_id, user_id=user_id
        )
        return False

    # Store metadata in database
    # Use provider name for storage (matches handoff tool lookup)
    stored: bool = await store_provider_metadata(user_id, integration.provider, metadata)
    return stored
