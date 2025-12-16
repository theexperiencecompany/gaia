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
from app.db.mongodb.collections import users_collection
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


async def fetch_provider_user_info(
    user_id: str, integration_id: str
) -> Optional[Dict[str, Any]]:
    """
    Fetch user info from a provider using the configured tool.

    Args:
        user_id: The user ID to fetch info for
        integration_id: The integration ID (e.g., "github", "twitter")

    Returns:
        The raw response from the tool, or None if failed
    """
    integration = get_integration_by_id(integration_id)

    if not integration or not integration.metadata_config:
        logger.debug(f"No metadata config for integration {integration_id}")
        return None

    tool_name = integration.metadata_config.user_info_tool

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
        data = result.data

        logger.info(f"Fetched user info for {integration_id}: {type(data)}")

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
        logger.error(f"Error fetching user info for {integration_id}: {e}")
        return None


def extract_metadata_from_response(
    response: Dict[str, Any], integration_id: str
) -> Optional[Dict[str, str]]:
    """
    Extract metadata fields from tool response using integration config.

    Args:
        response: The raw response from the user info tool
        integration_id: The integration ID

    Returns:
        Dictionary of extracted metadata, or None if failed
    """
    integration = get_integration_by_id(integration_id)

    if not integration or not integration.metadata_config:
        return None

    config = integration.metadata_config
    metadata: Dict[str, str] = {}

    # Extract username (required)
    username = _extract_nested_field(response, config.username_field)
    if username:
        metadata["username"] = username
    else:
        logger.warning(
            f"Could not extract username from {config.username_field} for {integration_id}"
        )

    if config.extract_fields:
        for field_name, field_path in config.extract_fields.items():
            value = _extract_nested_field(response, field_path)
            if value:
                metadata[field_name] = value

    return metadata if metadata else None


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

    Args:
        user_id: The user ID
        integration_id: The integration ID (e.g., "github", "twitter")

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

    # Fetch user info from provider
    response = await fetch_provider_user_info(user_id, integration_id)

    if not response:
        logger.warning(f"Failed to fetch user info for {integration_id}")
        return False

    # Extract metadata from response
    metadata = extract_metadata_from_response(response, integration_id)

    if not metadata:
        logger.warning(f"Failed to extract metadata for {integration_id}")
        return False

    # Store metadata in database
    # Use provider name for storage (matches handoff tool lookup)
    return await store_provider_metadata(user_id, integration.provider, metadata)
