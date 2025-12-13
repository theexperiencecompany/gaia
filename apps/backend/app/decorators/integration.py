"""
Integration Connection Decorator

This module provides a decorator to check integration requirements before tool execution.
"""

from functools import wraps
from typing import Any, Callable, Optional

from app.config.loggers import auth_logger as logger
from app.utils.integration_checker import check_and_prompt_integration
from app.utils.oauth_utils import get_tokens_by_user_id


def require_integration(tool_category: str, tool_name: Optional[str] = None):
    """
    Decorator to check if user has required integration before executing a tool.

    Args:
        tool_category: The tool category (e.g., 'gmail', 'calendar', 'google_docs')
        tool_name: Optional tool name for better error messaging

    Usage:
        @tool # ENSURE TOOL IS BEFORE REQUIRE_INTEGRATION OTHERWISE IT WON'T PARSE!!
        @require_integration("gmail", "send_email_tool")
        async def send_email_tool(config: RunnableConfig, ...):
            # Tool implementation
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            # Extract config from args or kwargs
            config = None

            # Look for RunnableConfig in args
            for arg in args:
                if hasattr(arg, "get") and hasattr(arg, "keys"):
                    config = arg
                    break

            # Look for RunnableConfig in kwargs
            if not config:
                config = kwargs.get("config")

            if not config:
                logger.warning(
                    f"No RunnableConfig found for tool: {tool_name or func.__name__}"
                )
                return "Configuration error: Unable to verify integration permissions."

            # Extract access token from config
            configurable = config.get("configurable", {})
            access_token, refresh_token, _ = await get_tokens_by_user_id(
                configurable.get("user_id")
            )

            if not access_token:
                logger.warning(
                    f"No access token found for tool: {tool_name or func.__name__}"
                )
                return "Authentication required: Please ensure you're logged in."

            # Check if user has required integration
            has_permission = await check_and_prompt_integration(
                access_token=access_token,
                tool_category=tool_category,
                tool_name=tool_name or func.__name__,
            )

            if not has_permission:
                # Integration connection prompt was sent to frontend
                return "Please connect your account to use this feature."

            # User has required permissions, execute the tool
            return await func(*args, **kwargs)

        return wrapper

    return decorator
