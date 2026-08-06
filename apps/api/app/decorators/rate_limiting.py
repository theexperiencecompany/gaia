"""Rate limiting decorators for API endpoints and LangChain tools, keyed on user plan."""

from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import inspect
from typing import Any, ParamSpec, TypeVar, cast

P = ParamSpec("P")
R = TypeVar("R")

from fastapi import HTTPException
from langgraph.config import get_stream_writer

from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    tiered_limiter,
)
from app.constants.log_tags import LogTag
from app.core.request_context import get_authenticated_user
from app.models.payment_models import PlanType
from app.models.usage_models import UsageInfo
from app.models.user_models import AuthenticatedUser
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

# Context variables to avoid parameter pollution
user_context: ContextVar[dict[str, Any] | None] = ContextVar("user_context", default=None)
rate_limit_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "rate_limit_context", default=None
)


def with_rate_limiting(
    feature_key: str | None = None,
    count_tokens: bool = False,
    bypass_for_system: bool = False,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Rate limiting decorator stackable with LangChain's @tool.

    Args:
        feature_key: Rate-limit key. If None, auto-derives from the tool name.
        count_tokens: Whether to validate token usage after execution.
        bypass_for_system: Skip rate limiting for system/background operations.

    Raises LangChainRateLimitException (agent-friendly) when limits are exceeded.
    """

    def rate_limit_decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        # 🚨 VALIDATE AT DECORATION TIME - Error happens when decorator is applied!
        sig = inspect.signature(func)
        if "config" not in sig.parameters:
            raise RuntimeError(
                f"DECORATOR ERROR: @with_rate_limiting() applied to '{func.__name__}' "
                f"but function is missing 'config: RunnableConfig' parameter!\n\n"
            )

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Enforce the feature's rate limit before running the wrapped call."""
            # Auto-derive feature key from function name if not provided
            actual_feature_key = feature_key or func.__name__

            # Get user context from context variable (avoid parameter pollution)
            context = user_context.get()
            # Decoration-time validation above guarantees a `config` parameter; it
            # carries LangGraph's RunnableConfig mapping.
            config = cast(Mapping[str, Any] | None, kwargs.get("config"))

            if not context and config:
                # Extract from RunnableConfig
                context = {
                    "user_id": config.get("metadata", {}).get("user_id"),
                    # Always user-initiated: no producer writes an "initiator" into
                    # a run's configurable (see AgentConfigurable), so the lookup
                    # this replaces could only ever return this default. Backend
                    # callers announce themselves through user_context instead,
                    # which is the branch above.
                    "initiator": "frontend",
                }

            if context and context.get("user_id"):
                user_id = context["user_id"]
                initiator = context.get("initiator", "frontend")

                # Skip rate limiting for system operations if configured
                if bypass_for_system and initiator == "backend":
                    log.debug(
                        f"{LogTag.API} Bypassing rate limiting for system operation: {actual_feature_key}"
                    )
                else:
                    try:
                        user_plan = await payment_service.get_cached_plan_type(user_id)

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

                        log.debug(
                            f"{LogTag.API} Rate limit check passed for user {user_id}, feature {actual_feature_key}"
                        )

                    except RateLimitExceededException as e:
                        # Convert to agent-friendly exception
                        log.warning(
                            f"{LogTag.API} Rate limit exceeded for user {user_id}, feature {actual_feature_key}"
                        )
                        detail_dict = {}
                        reset_time = None

                        # HTTPException.detail is typed `str` by Starlette, but
                        # RateLimitExceededException always sets it to a dict at
                        # runtime — cast to Any so the isinstance checks below
                        # aren't (incorrectly) treated as statically unreachable.
                        detail_value = cast(Any, e.detail) if hasattr(e, "detail") else None
                        if detail_value is not None:
                            if isinstance(detail_value, dict):
                                detail_dict = detail_value
                                reset_time = detail_value.get("reset_time")
                            elif isinstance(detail_value, str):
                                detail_dict = {"message": detail_value}

                        # Emit inline rate limit card via LangGraph stream writer
                        # (only available when executing inside a LangGraph graph)
                        try:
                            writer = get_stream_writer()
                            writer(
                                {
                                    "tool_data": {
                                        "tool_name": "rate_limit_data",
                                        "tool_category": "system",
                                        "data": {
                                            "feature": actual_feature_key,
                                            "plan_required": detail_dict.get("plan_required"),
                                            "reset_time": reset_time,
                                            "current_plan": (
                                                user_plan.value
                                                if hasattr(user_plan, "value")
                                                else str(user_plan)
                                            ),
                                        },
                                        "timestamp": datetime.now(UTC).isoformat(),
                                    }
                                }
                            )
                        except Exception as stream_error:
                            # Usually just "not in a streaming context" (workflows,
                            # background tasks); the card is decoration, the
                            # LangChainRateLimitException below is the real outcome.
                            log.debug(
                                f"{LogTag.API} Rate limit card not streamed for {actual_feature_key}: {stream_error}"
                            )

                        raise LangChainRateLimitException(
                            feature=actual_feature_key,
                            detail=detail_dict,
                            reset_time=reset_time,
                        )
                    except Exception as e:
                        log.error(
                            f"{LogTag.API} Rate limiting failed for user {user_id}, feature {actual_feature_key}: {e!s}"
                        )
                        raise
            else:
                log.warning(
                    f"{LogTag.API} No user context for {actual_feature_key}, skipping rate limiting"
                )

            # Execute the original function
            result = await func(*args, **kwargs)

            # Add rate limit metadata to response if it's a dict
            if isinstance(result, dict):
                rl_context = rate_limit_context.get()
                if rl_context:
                    # Convert UsageInfo objects to dicts for JSON serialization
                    usage_info_dict = {}
                    for period, usage_info in rl_context["usage_info"].items():
                        usage_info_dict[period] = {
                            "used": usage_info.used,
                            "limit": usage_info.limit,
                            "reset_time": usage_info.reset_time.isoformat()
                            if usage_info.reset_time
                            else None,
                        }

                    result.setdefault(
                        "_rate_limit_info",
                        {
                            "feature": rl_context["feature_key"],
                            "plan": rl_context["user_plan"],
                            "usage": usage_info_dict,
                        },
                    )

            # Handle token counting post-execution
            if count_tokens and isinstance(result, dict):
                tokens_used = result.get("tokens_used", 0)
                if tokens_used > 0:
                    log.debug(
                        f"{LogTag.API} Token usage recorded: {tokens_used} tokens for feature {actual_feature_key}"
                    )

            return result

        return wrapper

    return rate_limit_decorator


def tiered_rate_limit(
    feature_key: str, count_tokens: bool = False
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Rate limiting decorator for API endpoints."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Enforce the tiered rate limit before running the wrapped endpoint."""
            # The authenticated user comes from `request.state.user` (mirrored into
            # a ContextVar by WorkOSAuthMiddleware), NOT from the handler's
            # parameters. Matching on a kwarg named `user` — as this used to do —
            # meant an endpoint that named it `current_user`/`user_id`/`_user`
            # silently skipped rate limiting entirely.
            user = get_authenticated_user()

            if not user:
                # Direct invocation outside the HTTP middleware stack (tests,
                # internal callers) can still pass the auth dict explicitly.
                user = cast(AuthenticatedUser | None, kwargs.get("user"))
                for arg in args:
                    if isinstance(arg, dict) and "user_id" in arg:
                        user = cast(AuthenticatedUser, arg)
                if not user:
                    # Genuinely unauthenticated — a public route has nobody to bill.
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
            # if count_tokens and isinstance(result, dict):
            #     tokens_used = result.get("tokens_used", 0)
            #     if tokens_used > 0:
            #         # Validate token limits
            #         current_limits = get_limits_for_plan(feature_key, user_plan)
            #         if (
            #             current_limits.tokens_per_request > 0
            #             and tokens_used > current_limits.tokens_per_request
            #         ):
            #             plan_required = "pro" if user_plan == PlanType.FREE else None
            #             raise RateLimitExceededException(
            #                 f"{feature_key} (token limit)", plan_required
            #             )

            return result

        # Store metadata for usage tracking
        wrapper._rate_limit_metadata = {"feature_key": feature_key}  # type: ignore[attr-defined]

        return wrapper

    return decorator


class LangChainRateLimitException(Exception):
    """Agent-friendly rate limit exception with structured data."""

    def __init__(
        self,
        feature: str,
        detail: dict[Any, Any] | None = None,
        reset_time: str | None = None,
    ):
        self.feature = feature
        self.detail = detail or {}
        self.reset_time = reset_time

        message = f"Rate limit exceeded for {feature}."
        if reset_time:
            message += f" Resets at {reset_time}."
        if detail and detail.get("plan_required"):
            message += f" Upgrade to {detail['plan_required'].upper()} for higher limits."

        super().__init__(message)


async def enforce_rate_limit(user_id: str, feature_key: str) -> dict[str, UsageInfo]:
    """Check-and-increment a feature's tiered rate limit from service-layer code.

    For call sites that are neither FastAPI endpoints nor LangChain tools
    (e.g. sandbox lifecycle), where the decorator forms don't apply.

    Raises RateLimitExceededException when the limit is exceeded.
    """
    user_plan = await payment_service.get_cached_plan_type(user_id)
    return await tiered_limiter.check_and_increment(
        user_id=user_id,
        feature_key=feature_key,
        user_plan=user_plan,
    )


def set_user_context(user_id: str, initiator: str = "frontend", **kwargs: object) -> dict[str, Any]:
    """Set user context to avoid parameter pollution."""
    context = {"user_id": user_id, "initiator": initiator, **kwargs}
    user_context.set(context)
    log.debug(f"{LogTag.API} Set user context for {user_id} (initiator: {initiator})")
    return context


def clear_user_context() -> None:
    """Clear user context."""
    user_context.set(None)
    rate_limit_context.set(None)
    log.debug(f"{LogTag.API} Cleared user context")


def get_current_rate_limit_info() -> dict[str, Any] | None:
    """Get current rate limit information for the request."""
    return rate_limit_context.get()
