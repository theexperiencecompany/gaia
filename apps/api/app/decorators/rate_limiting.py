"""Rate limiting decorators for API endpoints and LangChain tools, keyed on user plan."""

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
import inspect
from typing import NotRequired, ParamSpec, TypedDict, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

from fastapi import HTTPException
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.api.v1.middleware.tiered_rate_limiter import (
    CostBudgetExceededException,
    RateLimitExceededException,
    tiered_limiter,
)
from app.config.rate_limits import (
    RateLimitPeriod,
    get_reset_time,
)
from app.constants.log_tags import LogTag
from app.core.request_context import resolve_caller
from app.models.chat_models import ToolDataEntry
from app.models.payment_models import PlanType
from app.models.usage_models import UsageInfo
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.cost_budget import get_cost, is_daily_budget_exhausted
from app.services.limit_upsell import LimitHitOrigin, current_limit_origin, schedule_limit_upsell
from app.services.payments.payment_service import payment_service
from shared.py.wide_events import log

# The LangChain-injected parameter every @with_rate_limiting tool must declare:
# checked at decoration time, read back on every call.
_CONFIG_PARAM = "config"


class UserRateLimitContext(TypedDict):
    """Who a tool call is metered against, and whether a user or the backend started it."""

    user_id: str | None
    initiator: str


class RateLimitUsage(TypedDict):
    """The limiter's verdict on the call that just passed, kept for its response metadata."""

    feature_key: str
    usage_info: dict[str, UsageInfo]
    user_plan: str


class RateLimitCardData(TypedDict):
    """The data the frontend's RateLimitCard renders."""

    feature: str
    plan_required: str | None
    reset_time: str | None
    current_plan: str
    message: NotRequired[str]


class RateLimitCard(TypedDict):
    """The stream-writer payload carrying one rate_limit_data card."""

    tool_data: ToolDataEntry


class RateLimitDetail(TypedDict, total=False):
    """The detail of a RateLimitExceededException; every key is conditional."""

    code: str
    feature: str
    message: str
    plan_required: str
    reset_time: str
    current_plan: str


_RATE_LIMIT_DETAIL: TypeAdapter[RateLimitDetail] = TypeAdapter(RateLimitDetail)


class _RunMetadata(BaseModel):
    """The ``metadata`` of a run's ``RunnableConfig``, read only for its user."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None


class _RunConfig(BaseModel):
    """A run's ``RunnableConfig``, read only for its metadata."""

    model_config = ConfigDict(extra="ignore")

    metadata: _RunMetadata = Field(default_factory=_RunMetadata)


class _TokenUsage(BaseModel):
    """A tool's dict result, read only for the tokens it reports using."""

    model_config = ConfigDict(extra="ignore")

    tokens_used: int = 0


# Context variables to avoid parameter pollution
user_context: ContextVar[UserRateLimitContext | None] = ContextVar("user_context", default=None)
rate_limit_context: ContextVar[RateLimitUsage | None] = ContextVar(
    "rate_limit_context", default=None
)


def plan_label(user_plan: object) -> str:
    """Return the plan's wire value — PlanType members carry one, anything else stringifies."""
    return user_plan.value if hasattr(user_plan, "value") else str(user_plan)


def build_rate_limit_card(
    *,
    feature: str,
    plan_required: str | None,
    reset_time: str | None,
    current_plan: str,
    message: str | None = None,
) -> RateLimitCard:
    """Build the rate_limit_data stream-card payload the frontend's RateLimitCard renders.

    Shared by every caller that surfaces a rate/budget/cap limit inline in
    chat. message is omitted from the payload when not given.
    """
    data: RateLimitCardData = {
        "feature": feature,
        "plan_required": plan_required,
        "reset_time": reset_time,
        "current_plan": current_plan,
    }
    if message is not None:
        data["message"] = message
    return {
        "tool_data": {
            "tool_name": "rate_limit_data",
            "tool_category": "system",
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    }


def _resolve_context(kwargs: dict[str, object]) -> UserRateLimitContext | None:
    """User context from the context var, falling back to the run's config."""
    context = user_context.get()
    # Decoration-time validation in with_rate_limiting guarantees a `config`
    # parameter; it carries LangGraph's RunnableConfig mapping.
    config = kwargs.get(_CONFIG_PARAM)
    if not context and config:
        # Extract from RunnableConfig
        context = {
            "user_id": _RunConfig.model_validate(config).metadata.user_id,
            # Always user-initiated: no producer writes an "initiator" into a
            # run's configurable, so this is the only value it could be.
            # Backend callers announce via user_context (the branch above).
            "initiator": "frontend",
        }
    return context


def _limit_hit_exception(
    user_id: str,
    actual_feature_key: str,
    user_plan: PlanType,
    e: RateLimitExceededException,
) -> "LangChainRateLimitError":
    """Convert a limiter exception into the agent-friendly one, with side effects."""
    log.warning(
        f"{LogTag.API} Rate limit exceeded",
        user_id=user_id,
        actual_feature_key=actual_feature_key,
        error=str(e),
        error_type=type(e).__name__,
    )
    if user_plan != PlanType.FREE:
        # FREE hits are already captured by the limit-upsell seam
        # (schedule_limit_upsell fires on every exceed for free users); paid
        # plans have no such side effect, so their hits are captured here.
        capture_event(
            user_id,
            AnalyticsEvents.RATE_LIMIT_HIT,
            {"feature": actual_feature_key, "plan": plan_label(user_plan)},
        )
    detail: RateLimitDetail = {}
    # HTTPException.detail is typed `str` by Starlette, but
    # RateLimitExceededException always sets it to a dict at runtime — held as
    # object so the isinstance checks below narrow a genuinely open value.
    raw_detail: object = e.detail
    if isinstance(raw_detail, dict):
        detail = _RATE_LIMIT_DETAIL.validate_python(raw_detail)
    elif isinstance(raw_detail, str):
        detail = {"message": raw_detail}
    # Falls back to the exception's own plan gate / reset time; the streamed
    # card gets an ISO string so every caller produces the same shape.
    reset_time = detail.get("reset_time") or getattr(e, "reset_time", None)
    plan_required = detail.get("plan_required") or getattr(e, "plan_required", None)

    # Emit inline rate limit card via LangGraph stream writer (only available
    # when executing inside a LangGraph graph).
    try:
        writer = get_stream_writer()
    except RuntimeError as stream_error:
        # "not in a runnable context" (workflows, background tasks) — the card
        # is decoration. Only the missing context is swallowed; card
        # construction/delivery failures propagate.
        log.debug(
            f"{LogTag.API} Rate limit card not streamed",
            actual_feature_key=actual_feature_key,
            error=str(stream_error),
            error_type=type(stream_error).__name__,
        )
    else:
        card_reset_time = reset_time.isoformat() if isinstance(reset_time, datetime) else reset_time
        writer(
            build_rate_limit_card(
                feature=actual_feature_key,
                plan_required=plan_required,
                reset_time=card_reset_time,
                current_plan=plan_label(user_plan),
            )
        )

    return LangChainRateLimitError(
        feature=actual_feature_key,
        detail=detail,
        reset_time=reset_time,
    )


async def _enforce_feature_limit(user_id: str, actual_feature_key: str) -> None:
    """Run one rate-limit check for user_id on actual_feature_key."""
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
                "user_plan": plan_label(user_plan),
            }
        )

        log.debug(
            f"{LogTag.API} Rate limit check passed",
            user_id=user_id,
            actual_feature_key=actual_feature_key,
        )
    except RateLimitExceededException as e:
        # Convert to agent-friendly exception
        raise _limit_hit_exception(user_id, actual_feature_key, user_plan, e) from e
    except Exception as e:
        log.error(
            f"{LogTag.API} Rate limiting failed",
            user_id=user_id,
            actual_feature_key=actual_feature_key,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


def _attach_usage_metadata(result: dict[str, object]) -> None:
    """Attach this call's rate-limit usage to a dict result for the caller."""
    rl_context: RateLimitUsage | None = rate_limit_context.get()
    if not rl_context:
        return
    # Convert UsageInfo objects to dicts for JSON serialization
    usage_info_dict: dict[str, dict[str, object]] = {}
    for period, usage_info in rl_context["usage_info"].items():
        usage_info_dict[period] = {
            "used": usage_info.used,
            "limit": usage_info.limit,
            "reset_time": usage_info.reset_time.isoformat() if usage_info.reset_time else None,
        }

    result.setdefault(
        "_rate_limit_info",
        {
            "feature": rl_context["feature_key"],
            "plan": rl_context["user_plan"],
            "usage": usage_info_dict,
        },
    )


def with_rate_limiting(
    feature_key: str | None = None,
    count_tokens: bool = False,
    bypass_for_system: bool = False,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Rate limiting decorator stackable with LangChain's @tool.

    feature_key auto-derives from the function name when None. Raises
    LangChainRateLimitError (agent-friendly) when limits are exceeded.
    """

    def rate_limit_decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        # 🚨 VALIDATE AT DECORATION TIME - Error happens when decorator is applied!
        sig = inspect.signature(func)
        if _CONFIG_PARAM not in sig.parameters:
            raise RuntimeError(
                f"DECORATOR ERROR: @with_rate_limiting() applied to '{func.__name__}' "
                f"but function is missing 'config: RunnableConfig' parameter!\n\n"
            )

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Enforce the feature's rate limit before running the wrapped call."""
            # Auto-derive feature key from function name if not provided
            actual_feature_key = feature_key or func.__name__

            context: UserRateLimitContext | None = _resolve_context(kwargs)
            user_id = context["user_id"] if context else None

            if context and user_id:
                # Skip rate limiting for system operations if configured
                if not (bypass_for_system and context["initiator"] == "backend"):
                    await _enforce_feature_limit(user_id, actual_feature_key)
            else:
                log.warning(
                    f"{LogTag.API} No user context, skipping rate limiting",
                    actual_feature_key=actual_feature_key,
                )

            # Execute the original function
            result = await func(*args, **kwargs)

            # Add rate limit metadata to response if it's a dict
            if isinstance(result, dict):
                _attach_usage_metadata(result)

                # Handle token counting post-execution
                if count_tokens:
                    tokens_used = _TokenUsage.model_validate(result).tokens_used
                    if tokens_used > 0:
                        log.debug(
                            f"{LogTag.API} Token usage recorded",
                            tokens_used=tokens_used,
                            feature_key=actual_feature_key,
                        )

            return result

        return wrapper

    return rate_limit_decorator


async def enforce_tiered_limit(
    user_id: str, feature_key: str, *, origin: LimitHitOrigin | None = None
) -> None:
    """Charge feature_key against user_id's plan quota.

    The imperative half of tiered_rate_limit, extracted for callers (the bot
    chat stream) that resolve their user in the body rather than from the
    auth middleware, and so can't use the decorator form.
    """
    origin = origin or current_limit_origin()
    subscription = await payment_service.get_user_subscription_status(user_id)
    user_plan = subscription.plan_type or PlanType.FREE
    try:
        await tiered_limiter.check_and_increment(
            user_id=user_id,
            feature_key=feature_key,
            user_plan=user_plan,
            origin=origin,
        )
    except RateLimitExceededException:
        # FREE hits are captured by the limit-upsell seam; capture the
        # paid-plan hits here so every wall produces one event.
        if user_plan != PlanType.FREE:
            capture_event(
                user_id,
                AnalyticsEvents.RATE_LIMIT_HIT,
                {"feature": feature_key, "plan": user_plan.value},
            )
        raise


def tiered_rate_limit(
    feature_key: str,
    *,
    origin: LimitHitOrigin | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Rate limiting decorator for API endpoints."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Enforce the tiered rate limit before running the wrapped endpoint."""
            # The authenticated user comes from `request.state.user`, not a
            # handler kwarg named `user` — matching on that kwarg used to
            # silently skip rate limiting for any differently-named parameter.
            user = resolve_caller(args, kwargs)
            if not user:
                # Genuinely unauthenticated — a public route has nobody to bill.
                return await func(*args, **kwargs)

            user_id = user.user_id
            if not user_id:
                raise HTTPException(status_code=401, detail="User ID not found")

            # Check rate limits before executing function
            await enforce_tiered_limit(user_id, feature_key, origin=origin)

            # Execute the original function
            result = await func(*args, **kwargs)
            return result

        return wrapper

    return decorator


class LangChainRateLimitError(Exception):
    """Agent-friendly rate limit exception with structured data."""

    def __init__(
        self,
        feature: str,
        detail: RateLimitDetail | None = None,
        reset_time: str | datetime | None = None,
    ):
        resolved_detail: RateLimitDetail = detail or {}
        self.feature = feature
        self.detail = resolved_detail
        self.reset_time = reset_time

        message = f"Rate limit exceeded for {feature}."
        if reset_time:
            message += f" Resets at {reset_time}."
        plan_required = resolved_detail.get("plan_required")
        if plan_required:
            message += f" Upgrade to {plan_required.upper()} for higher limits."
        # A wall with no way past it reads as a dead end, so a free user's limit
        # message names the tool that mints their checkout link. The agent decides
        # whether an upsell fits the moment — no link is created unless it does.
        if resolved_detail.get("current_plan") == PlanType.FREE.value:
            message += (
                " This user is on the free plan: offer to upgrade them and call "
                "`create_upgrade_link` for a checkout link if they want it."
            )

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


async def enforce_daily_cost_budget(
    user_id: str, feature_key: str, *, origin: LimitHitOrigin | None = None
) -> None:
    """Block when the user's rolling daily USD cost budget is exhausted.

    Caps HOW EXPENSIVE a user's requests were (vs. the count limiter's HOW
    MANY). Raises the same RateLimitExceededException (429) as the count
    limiter so the frontend toast/upgrade-modal path renders identically.
    """
    origin = origin or current_limit_origin()
    plan_type = await payment_service.get_cached_plan_type(user_id)
    # The tier this request was priced against, on the wide event — this gate is
    # the one place on the chat path that resolves the plan before any work runs.
    log.set(user_plan=plan_type.value)
    spent = await get_cost(user_id, RateLimitPeriod.DAY)
    if is_daily_budget_exhausted(spent, plan_type):
        log.warning(
            f"{LogTag.API} Daily cost budget exhausted",
            user={"id": user_id},
            user_plan=plan_type.value,
            spent_usd=round(spent, 6),
            feature_key=feature_key,
        )
        schedule_limit_upsell(user_id, feature_key, plan_type, origin)
        raise CostBudgetExceededException(
            feature=feature_key,
            plan_required=PlanType.PRO.value if plan_type == PlanType.FREE else None,
            reset_time=get_reset_time(RateLimitPeriod.DAY),
            current_plan=plan_type.value,
        )


def set_user_context(user_id: str, initiator: str = "frontend") -> UserRateLimitContext:
    """Set user context to avoid parameter pollution."""
    context: UserRateLimitContext = {"user_id": user_id, "initiator": initiator}
    user_context.set(context)
    log.debug(
        f"{LogTag.API} Set user context for (initiator: )", user_id=user_id, initiator=initiator
    )
    return context


def clear_user_context() -> None:
    user_context.set(None)
    rate_limit_context.set(None)
    log.debug(f"{LogTag.API} Cleared user context")


def get_current_rate_limit_info() -> RateLimitUsage | None:
    """Get current rate limit information for the request."""
    return rate_limit_context.get()
