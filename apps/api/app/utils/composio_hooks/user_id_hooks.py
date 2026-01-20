"""
User ID extraction hooks using the enhanced decorator system.

This module handles user ID extraction from RunnableConfig metadata
for all Composio tools.
"""

from composio.types import ToolExecuteParams

from app.config.loggers import app_logger as logger
from .registry import register_before_hook


@register_before_hook()  # Runs for ALL tools/toolkits
def extract_user_id_from_params(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """
    Extract user_id from RunnableConfig metadata and add it to tool execution params.

    This function is used as a before_execute modifier for Composio tools to ensure
    user context is properly passed through during tool execution.

    Sets both 'user_id' (new SDK) and 'entity_id' (legacy) for compatibility
    with Composio's connected account authentication.

    Migrated from the old standalone function to use the new hook system.
    """
    arguments = params.get("arguments", {})
    if not arguments:
        return params

    config = arguments.pop("__runnable_config__", None)
    if config is None:
        return params

    metadata = config.get("metadata", {}) if isinstance(config, dict) else {}
    if not metadata:
        return params

    user_id = metadata.get("user_id")
    if user_id is None:
        return params

    # Set both user_id (new) and entity_id (legacy) for compatibility
    # The Composio API requires entity_id for connected account authentication
    params["user_id"] = user_id
    params["entity_id"] = user_id
    logger.debug(f"Extracted user_id/entity_id '{user_id}' for {toolkit}:{tool}")
    return params


# For easy registration in __init__.py
all_hooks = [extract_user_id_from_params]
