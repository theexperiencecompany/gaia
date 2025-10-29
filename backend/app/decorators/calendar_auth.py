from functools import wraps
from typing import Any, Callable

from app.config.loggers import chat_logger as logger
from app.utils.oauth_utils import get_tokens_by_user_id
from langchain_core.runnables.config import RunnableConfig


def with_calendar_auth(func: Callable) -> Callable:
    """
    Decorator to handle calendar authentication and token retrieval.
    Extracts user_id and access_token from config automatically.

    Usage:
        @tool
        @with_calendar_auth
        async def my_calendar_tool(
            config: RunnableConfig,
            user_id: str,  # Injected by decorator
            access_token: str,  # Injected by decorator
            ...
        ) -> str:
            # Implementation
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        config: RunnableConfig = kwargs.get("config")

        if not config:
            logger.error("Missing configuration data")
            return "Unable to access calendar configuration. Please try again."

        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            logger.error("Missing user_id in config")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        access_token, _, token_success = await get_tokens_by_user_id(user_id)
        if not token_success or not access_token:
            logger.error(f"Failed to get valid tokens for user: {user_id}")
            return "Unable to access your calendar. Please ensure you're logged in with calendar permissions."

        kwargs["user_id"] = user_id
        kwargs["access_token"] = access_token

        return await func(*args, **kwargs)

    return wrapper
