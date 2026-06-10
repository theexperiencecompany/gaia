"""
Provider Metadata Service

Service for fetching and storing provider-specific user metadata (e.g., username)
when OAuth integrations are connected. This metadata is used to enhance agent
system prompts with user context.
"""

from datetime import UTC, datetime
import json
from typing import Any

from bson import ObjectId

from app.config.oauth_config import get_integration_by_id
from app.constants.cache import PROVIDER_METADATA_CACHE_TTL
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable, CacheInvalidator
from app.services.composio.composio_service import get_composio_service
from shared.py.wide_events import log


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
        log.error(f"Error extracting field '{field_path}': {e}")
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
            log.error(f"Tool {tool_name} not found for {integration_id}")
            return None

        # Execute the tool to get user info
        result = await tool.ainvoke({})
        data = result.get("data", {})

        log.info(f"Fetched {tool_name} for {integration_id}: {type(data)}")

        # Handle different response types
        if isinstance(data, dict):
            return data
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                log.warning(f"Could not parse tool response as JSON: {data[:100]}")
                return None
        else:
            log.warning(f"Unexpected response type from {tool_name}: {type(data)}")
            return None

    except Exception as e:
        log.error(f"Error fetching {tool_name} for {integration_id}: {e}")
        return None


async def fetch_provider_user_info(user_id: str, integration_id: str) -> dict[str, str] | None:
    """Fetch user info from a provider, calling each tool in metadata_config and
    extracting its configured variables into a name -> value dict (or None)."""
    log.set(provider_metadata_user_id=user_id, provider_metadata_integration=integration_id)
    integration = get_integration_by_id(integration_id)

    if not integration or not integration.metadata_config:
        log.debug(f"No metadata config for integration {integration_id}")
        return None

    metadata: dict[str, str] = {}

    # Iterate through each tool configuration
    for tool_config in integration.metadata_config.tools:
        # Fetch response from this tool
        response = await fetch_tool_response(user_id, tool_config.tool, integration_id)

        if not response:
            log.warning(f"Failed to fetch {tool_config.tool} for {integration_id}, skipping")
            continue

        # Extract each configured variable from the response
        for var in tool_config.variables:
            value = _extract_nested_field(response, var.field_path)
            if value:
                metadata[var.name] = value
                log.debug(f"Extracted {var.name}={value} from {tool_config.tool}")
            else:
                log.warning(
                    f"Could not extract {var.name} from {var.field_path} "
                    f"in {tool_config.tool} response"
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
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    f"provider_metadata.{provider}": metadata,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

        if result.modified_count > 0:
            log.info(f"Stored {provider} metadata for user {user_id}: {metadata}")
            return True
        log.warning(f"No document updated for user {user_id}")
        return False

    except Exception as e:
        log.error(f"Error storing {provider} metadata for user {user_id}: {e}")
        return False


@Cacheable(
    key_pattern="provider_metadata:{user_id}:{provider}",
    ttl=PROVIDER_METADATA_CACHE_TTL,
)
async def get_provider_metadata(user_id: str, provider: str) -> dict[str, str] | None:
    """Retrieve provider metadata for a user, or None if not found."""
    try:
        user = await users_collection.find_one({"_id": ObjectId(user_id)}, {"provider_metadata": 1})

        if not user:
            return None

        provider_metadata = user.get("provider_metadata", {})
        return provider_metadata.get(provider)

    except Exception as e:
        log.error(f"Error getting {provider} metadata for user {user_id}: {e}")
        return None


async def fetch_and_store_provider_metadata(user_id: str, integration_id: str) -> bool:
    """Fetch user info from a provider and store its metadata. Returns success.

    Main entry point called after an OAuth connection succeeds.
    """
    integration = get_integration_by_id(integration_id)

    if not integration:
        log.debug(f"Integration {integration_id} not found")
        return False

    if not integration.metadata_config:
        log.debug(f"No metadata config for integration {integration_id}")
        return False

    # Fetch and extract metadata from all configured tools
    metadata = await fetch_provider_user_info(user_id, integration_id)

    if not metadata:
        log.warning(f"Failed to fetch/extract metadata for {integration_id}")
        return False

    # Store metadata in database
    # Use provider name for storage (matches handoff tool lookup)
    return await store_provider_metadata(user_id, integration.provider, metadata)
