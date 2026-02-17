"""
Provider Metadata Service

Service for fetching and storing provider-specific user metadata (e.g., username)
when OAuth integrations are connected. This metadata is used to enhance agent
system prompts with user context.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config.loggers import app_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.constants.cache import ONE_HOUR_TTL
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable, CacheInvalidator
from app.services.composio.composio_service import get_composio_service
from bson import ObjectId


def _extract_nested_field(data: Dict[str, Any], field_path: str) -> Optional[str]:
    """
    Extract a value from a nested dictionary using dot notation.

    Args:
        data: The dictionary to extract from
        field_path: Dot-separated path (e.g., "data.login" or "data.data.username")

    Returns:
        The extracted value as string, or None if not found
    """
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
        logger.error(f"Error extracting field '{field_path}': {e}")
        return None


async def fetch_tool_response(
    user_id: str, tool_name: str, integration_id: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch response from a single tool.

    Args:
        user_id: The user ID to fetch info for
        tool_name: The tool to call (e.g., "TWITTER_USER_LOOKUP_ME")
        integration_id: The integration ID (for logging)

    Returns:
        The raw response from the tool as dict, or None if failed
    """
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
            logger.error(f"Tool {tool_name} not found for {integration_id}")
            return None

        # Execute the tool to get user info
        result = await tool.ainvoke({})
        data = result.get("data", {})

        logger.info(f"Fetched {tool_name} for {integration_id}: {type(data)}")

        # Handle different response types
        if isinstance(data, dict):
            return data
        elif isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                logger.warning(f"Could not parse tool response as JSON: {data[:100]}")
                return None
        else:
            logger.warning(f"Unexpected response type from {tool_name}: {type(data)}")
            return None

    except Exception as e:
        logger.error(f"Error fetching {tool_name} for {integration_id}: {e}")
        return None


async def fetch_provider_user_info(
    user_id: str, integration_id: str
) -> Optional[Dict[str, str]]:
    """
    Fetch user info from a provider using configured tools and extract variables.

    Iterates through all configured tools in metadata_config, calls each tool,
    and extracts the configured variables from responses.

    Args:
        user_id: The user ID to fetch info for
        integration_id: The integration ID (e.g., "github", "twitter")

    Returns:
        Dictionary of extracted variables (name -> value), or None if failed
    """
    integration = get_integration_by_id(integration_id)

    if not integration or not integration.metadata_config:
        logger.debug(f"No metadata config for integration {integration_id}")
        return None

    metadata: Dict[str, str] = {}

    # Iterate through each tool configuration
    for tool_config in integration.metadata_config.tools:
        # Fetch response from this tool
        response = await fetch_tool_response(user_id, tool_config.tool, integration_id)

        if not response:
            logger.warning(
                f"Failed to fetch {tool_config.tool} for {integration_id}, skipping"
            )
            continue

        # Extract each configured variable from the response
        for var in tool_config.variables:
            value = _extract_nested_field(response, var.field_path)
            if value:
                metadata[var.name] = value
                logger.debug(f"Extracted {var.name}={value} from {tool_config.tool}")
            else:
                logger.warning(
                    f"Could not extract {var.name} from {var.field_path} "
                    f"in {tool_config.tool} response"
                )

    return metadata if metadata else None


@CacheInvalidator(key_patterns=["provider_metadata:{user_id}:{provider}"])
async def store_provider_metadata(
    user_id: str, provider: str, metadata: Dict[str, str]
) -> bool:
    """
    Store provider metadata in the user's document.

    Args:
        user_id: The user ID
        provider: The provider name (e.g., "github", "twitter")
        metadata: The metadata to store

    Returns:
        True if successful, False otherwise
    """
    try:
        result = await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    f"provider_metadata.{provider}": metadata,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        if result.modified_count > 0:
            logger.info(f"Stored {provider} metadata for user {user_id}: {metadata}")
            return True
        else:
            logger.warning(f"No document updated for user {user_id}")
            return False

    except Exception as e:
        logger.error(f"Error storing {provider} metadata for user {user_id}: {e}")
        return False


@Cacheable(key_pattern="provider_metadata:{user_id}:{provider}", ttl=ONE_HOUR_TTL)
async def get_provider_metadata(
    user_id: str, provider: str
) -> Optional[Dict[str, str]]:
    """
    Retrieve provider metadata for a user.

    Args:
        user_id: The user ID
        provider: The provider name

    Returns:
        The metadata dictionary, or None if not found
    """
    try:
        user = await users_collection.find_one(
            {"_id": ObjectId(user_id)}, {"provider_metadata": 1}
        )

        if not user:
            return None

        provider_metadata = user.get("provider_metadata", {})
        return provider_metadata.get(provider)

    except Exception as e:
        logger.error(f"Error getting {provider} metadata for user {user_id}: {e}")
        return None


async def get_all_provider_metadata(user_id: str) -> Dict[str, Dict[str, str]]:
    """
    Retrieve all provider metadata for a user.

    Args:
        user_id: The user ID

    Returns:
        Dictionary of provider -> metadata mappings
    """
    try:
        user = await users_collection.find_one(
            {"_id": ObjectId(user_id)}, {"provider_metadata": 1}
        )

        if not user:
            return {}

        return user.get("provider_metadata", {})

    except Exception as e:
        logger.error(f"Error getting all provider metadata for user {user_id}: {e}")
        return {}


async def fetch_and_store_provider_metadata(user_id: str, integration_id: str) -> bool:
    """
    Fetch user info from provider and store metadata in database.

    This is the main entry point called after OAuth connection succeeds.
    Uses the new multi-tool configuration to fetch from multiple tools
    and extract configured variables.

    Args:
        user_id: The user ID
        integration_id: The integration ID (e.g., "github", "twitter", "gmail")

    Returns:
        True if metadata was successfully fetched and stored, False otherwise
    """
    integration = get_integration_by_id(integration_id)

    if not integration:
        logger.debug(f"Integration {integration_id} not found")
        return False

    if not integration.metadata_config:
        logger.debug(f"No metadata config for integration {integration_id}")
        return False

    # Fetch and extract metadata from all configured tools
    metadata = await fetch_provider_user_info(user_id, integration_id)

    if not metadata:
        logger.warning(f"Failed to fetch/extract metadata for {integration_id}")
        return False

    # Store metadata in database
    # Use provider name for storage (matches handoff tool lookup)
    return await store_provider_metadata(user_id, integration.provider, metadata)
