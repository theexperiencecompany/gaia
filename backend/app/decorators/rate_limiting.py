"""
Rate limiting decorators for API endpoints and LangChain tools.

This module provides decorators for rate limiting based on user subscription plans.
"""

import inspect
import json
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException

from app.config.loggers import app_logger
from app.config.rate_limits import get_limits_for_plan
from app.db.redis import redis_cache
from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    tiered_limiter,
)
from app.models.payment_models import PlanType
from app.services.payments.payment_service import payment_service

# Context variables to avoid parameter pollution
user_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "user_context", default=None
)
rate_limit_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "rate_limit_context", default=None
)


def with_rate_limiting(
    feature_key: Optional[str] = None,
    count_tokens: bool = False,
    bypass_for_system: bool = False,
):
    """
    Rate limiting decorator that can be stacked with LangChain's @tool decorator.

    Args:
        feature_key: Feature key for rate limiting. If None, auto-derives from tool name
        count_tokens: Whether to validate token usage after execution
        bypass_for_system: Skip rate limiting for system/background operations

    Usage:
        @tool
        @with_rate_limiting()  # Auto-derives feature key
        async def tool_function(prompt: str) -> str:
            ...
    Raises:
        LangChainRateLimitException: When rate limits are exceeded (agent-friendly)
    """

    def rate_limit_decorator(func):
        # 🚨 VALIDATE AT DECORATION TIME - Error happens when decorator is applied!
        sig = inspect.signature(func)
        if "config" not in sig.parameters:
            raise RuntimeError(
                f"DECORATOR ERROR: @with_rate_limiting() applied to '{func.__name__}' "
                f"but function is missing 'config: RunnableConfig' parameter!\n\n"
            )

        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Auto-derive feature key from function name if not provided
            actual_feature_key = feature_key or func.__name__

            # Get user context from context variable (avoid parameter pollution)
            context = user_context.get()
            config = kwargs.get("config")

            if not context and config:
                # Extract from RunnableConfig
                context = {
                    "user_id": config.get("metadata", {}).get("user_id"),
                    "initiator": config.get("configurable", {}).get(
                        "initiator", "frontend"
                    ),
                }

            if context and context.get("user_id"):
                user_id = context["user_id"]
                initiator = context.get("initiator", "frontend")

                # Skip rate limiting for system operations if configured
                if bypass_for_system and initiator == "backend":
                    app_logger.debug(
                        f"Bypassing rate limiting for system operation: {actual_feature_key}"
                    )
                else:
                    try:
                        # Get cached subscription or fetch new one
                        subscription = await _get_cached_subscription(user_id)
                        user_plan = subscription.plan_type or PlanType.FREE

                        # Apply rate limiting with atomic operations
                        usage_info = await tiered_limiter.check_and_increment(
                            user_id=user_id,
                            feature_key=actual_feature_key,
                            user_plan=user_plan,
                        )

                        # Store rate limit context for response metadata
                        rate_limit_context.set(
                            {
                                "feature_key": actual_feature_key,
                                "usage_info": usage_info,
                                "user_plan": (
                                    user_plan.value
                                    if hasattr(user_plan, "value")
                                    else str(user_plan)
                                ),
                            }
                        )

                        app_logger.debug(
                            f"Rate limit check passed for user {user_id}, feature {actual_feature_key}"
                        )

                    except RateLimitExceededException as e:
                        # Convert to agent-friendly exception
                        app_logger.warning(
                            f"Rate limit exceeded for user {user_id}, feature {actual_feature_key}"
                        )
                        detail_dict = {}
                        reset_time = None

                        if hasattr(e, "detail"):
                            if isinstance(e.detail, dict):
                                detail_dict = e.detail
                                reset_time = e.detail.get("reset_time")
                            elif isinstance(e.detail, str):
                                detail_dict = {"message": e.detail}

                        raise LangChainRateLimitException(
                            feature=actual_feature_key,
                            detail=detail_dict,
                            reset_time=reset_time,
                        )
                    except Exception as e:
                        app_logger.error(
                            f"Rate limiting failed for user {user_id}, feature {actual_feature_key}: {str(e)}"
                        )
                        raise
            else:
                app_logger.warning(
                    f"No user context for {actual_feature_key}, skipping rate limiting"
                )

            # Execute the original function
            result = await func(*args, **kwargs)

            # Add rate limit metadata to response if it's a dict
            if isinstance(result, dict):
                rl_context = rate_limit_context.get()
                if rl_context:
                    result.setdefault(
                        "_rate_limit_info",
                        {
                            "feature": rl_context["feature_key"],
                            "plan": rl_context["user_plan"],
                            "usage": rl_context["usage_info"],
                        },
                    )

            # Handle token counting post-execution
            if count_tokens and isinstance(result, dict):
                tokens_used = result.get("tokens_used", 0)
                if tokens_used > 0:
                    app_logger.debug(
                        f"Token usage recorded: {tokens_used} tokens for feature {actual_feature_key}"
                    )

            return result

        return wrapper

    return rate_limit_decorator


def tiered_rate_limit(feature_key: str, count_tokens: bool = False):
    """Rate limiting decorator for API endpoints."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request and user from dependencies
            user = None

            for arg in args:
                if isinstance(arg, dict) and "user_id" in arg:
                    user = arg

            if not user:
                user = kwargs.get("user")
                if not user:
                    # If no user found, skip rate limiting (for public endpoints)
                    return await func(*args, **kwargs)

            user_id = user.get("user_id")
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")

            # Get user subscription
            subscription = await payment_service.get_user_subscription_status(user_id)
            user_plan = subscription.plan_type or PlanType.FREE

            # Check rate limits before executing function
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key=feature_key,
                user_plan=user_plan,
            )

            # Execute the original function
            result = await func(*args, **kwargs)

            # Handle token counting post-execution
            if count_tokens and isinstance(result, dict):
                tokens_used = result.get("tokens_used", 0)
                if tokens_used > 0:
                    # Validate token limits
                    current_limits = get_limits_for_plan(feature_key, user_plan)
                    if (
                        current_limits.tokens_per_request > 0
                        and tokens_used > current_limits.tokens_per_request
                    ):
                        plan_required = "pro" if user_plan == PlanType.FREE else None
                        raise RateLimitExceededException(
                            f"{feature_key} (token limit)", plan_required
                        )

            return result

        # Store metadata for usage tracking
        setattr(wrapper, "_rate_limit_metadata", {"feature_key": feature_key})

        return wrapper

    return decorator


class LangChainRateLimitException(Exception):
    """Agent-friendly rate limit exception with structured data."""

    def __init__(
        self,
        feature: str,
        detail: Optional[Dict[Any, Any]] = None,
        reset_time: Optional[str] = None,
    ):
        self.feature = feature
        self.detail = detail or {}
        self.reset_time = reset_time

        message = f"Rate limit exceeded for {feature}."
        if reset_time:
            message += f" Resets at {reset_time}."
        if detail and detail.get("plan_required"):
            message += (
                f" Upgrade to {detail['plan_required'].upper()} for higher limits."
            )

        super().__init__(message)

    def to_agent_message(self) -> str:
        """Convert to user-friendly message for agent responses."""
        return f"I've reached the usage limit for {self.feature.replace('_', ' ')}. Please try again later or upgrade your plan for higher limits."


async def _get_cached_subscription(user_id: str):
    """Get subscription with Redis caching to reduce duplicate lookups."""
    cache_key = f"subscription:{user_id}"

    # Try cache first
    try:
        cached = await redis_cache.get(cache_key)
        if cached:
            app_logger.debug(f"Using cached subscription for user {user_id}")
            # Parse cached subscription data
            data = json.loads(cached)
            from types import SimpleNamespace

            cached_subscription = SimpleNamespace(**data)
            cached_subscription.plan_type = PlanType(data.get("plan_type", "free"))
            return cached_subscription
    except Exception as e:
        app_logger.debug(f"Cache lookup failed for user {user_id}: {str(e)}")

    # Fetch and cache
    subscription = await payment_service.get_user_subscription_status(user_id)

    # Cache for 5 minutes
    try:
        cache_data = {
            "plan_type": (
                subscription.plan_type.value
                if subscription.plan_type and hasattr(subscription.plan_type, "value")
                else str(subscription.plan_type)
                if subscription.plan_type
                else None
            ),
            "expires_at": None,  # This field is not available in UserSubscriptionStatus
        }
        await redis_cache.set(cache_key, cache_data, 300)
        app_logger.debug(f"Cached subscription for user {user_id}")
    except Exception as e:
        app_logger.debug(f"Cache write failed for user {user_id}: {str(e)}")

    return subscription


def set_user_context(user_id: str, initiator: str = "frontend", **kwargs):
    """Set user context to avoid parameter pollution."""
    context = {"user_id": user_id, "initiator": initiator, **kwargs}
    user_context.set(context)
    app_logger.debug(f"Set user context for {user_id} (initiator: {initiator})")
    return context


def clear_user_context():
    """Clear user context."""
    user_context.set(None)
    rate_limit_context.set(None)
    app_logger.debug("Cleared user context")


def get_current_rate_limit_info() -> Optional[Dict[str, Any]]:
    """Get current rate limit information for the request."""
    return rate_limit_context.get()
