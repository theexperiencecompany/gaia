"""
Structured Logging System for GAIA Applications.

Provides automatic request context capture and structured logging with minimal boilerplate.
The middleware automatically captures HTTP request/response details, and services can
add business context using the simple `log` helper.

Usage:
    # In routes/services - context is auto-captured by middleware
    from shared.py.wide_events import log, get_request_context

    # Simple structured logging (auto-includes request context)
    log.info("user_login", user_id="123", method="oauth")

    # Get current request context
    ctx = get_request_context()
    log.info("processing", user_id=ctx.user_id, path=ctx.path)

Sampling:
    - 100% of errors (status >= 500)
    - 100% of slow requests (>2s)
    - 100% of VIP users
    - 5% of successful requests (configurable via LOG_SUCCESS_SAMPLE_RATE)
"""

import os
import random
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from loguru import logger


# =============================================================================
# Request Context - Auto-captured by middleware
# =============================================================================

@dataclass
class RequestContext:
    """Request context auto-captured by middleware. Access via get_request_context()."""

    # Identifiers
    request_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: Optional[str] = None

    # Request info (auto-captured)
    method: Optional[str] = None
    path: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # User info (auto-captured from auth)
    user_id: Optional[str] = None
    subscription_tier: Optional[str] = None

    # Timing
    start_time: float = field(default_factory=time.time)

    # Response (set after request completes)
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None

    @property
    def is_vip(self) -> bool:
        """Check if user is VIP tier."""
        vip_tiers = ("pro", "premium", "enterprise", "team")
        return self.subscription_tier and self.subscription_tier.lower() in vip_tiers

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for logging, excluding None values and internals."""
        return {
            k: v for k, v in {
                "request_id": self.request_id,
                "trace_id": self.trace_id,
                "method": self.method,
                "path": self.path,
                "client_ip": self.client_ip,
                "user_id": self.user_id,
                "subscription_tier": self.subscription_tier,
                "status_code": self.status_code,
                "duration_ms": self.duration_ms,
            }.items() if v is not None
        }


# Context variable for current request
_request_context: ContextVar[Optional[RequestContext]] = ContextVar(
    "request_context", default=None
)


def get_request_context() -> Optional[RequestContext]:
    """Get current request context (auto-captured by middleware)."""
    return _request_context.get()


def set_request_context(ctx: RequestContext) -> None:
    """Set request context (called by middleware)."""
    _request_context.set(ctx)


def clear_request_context() -> None:
    """Clear request context (called by middleware)."""
    _request_context.set(None)


# =============================================================================
# Sampling Configuration
# =============================================================================

@dataclass
class SamplingConfig:
    """Sampling configuration for tail-based sampling."""

    success_sample_rate: float = float(os.getenv("LOG_SUCCESS_SAMPLE_RATE", "0.05"))
    slow_request_threshold_ms: int = int(os.getenv("LOG_SLOW_REQUEST_THRESHOLD_MS", "2000"))
    debug_mode: bool = os.getenv("LOG_DEBUG_MODE", "false").lower() == "true"


_sampling_config = SamplingConfig()


def should_sample(
    status_code: Optional[int] = None,
    duration_ms: Optional[float] = None,
    is_error: bool = False,
    is_vip: bool = False,
) -> bool:
    """Determine if event should be logged based on tail sampling."""
    config = _sampling_config

    # Debug mode - log everything
    if config.debug_mode:
        return True

    # Always log errors
    if is_error or (status_code and status_code >= 500):
        return True

    # Always log slow requests
    if duration_ms and duration_ms > config.slow_request_threshold_ms:
        return True

    # Always log VIP users
    if is_vip:
        return True

    # Random sample the rest
    return random.random() < config.success_sample_rate


# =============================================================================
# Structured Logger - Simple API with auto context
# =============================================================================

class StructuredLogger:
    """
    Simple structured logger that auto-includes request context.

    Usage:
        from shared.py.wide_events import log
        log.info("user_action", action="login", user_id="123")
        log.error("payment_failed", error="card_declined", amount=100)
    """

    def __init__(self, name: str = "GAIA"):
        self._logger = logger.bind(logger_name=name)

    def _log(self, level: str, event: str, **kwargs: Any) -> None:
        """Internal log method that adds request context."""
        # Get request context if available
        ctx = get_request_context()
        if ctx:
            # Add request context fields (don't override explicit kwargs)
            ctx_dict = ctx.to_dict()
            for k, v in ctx_dict.items():
                if k not in kwargs:
                    kwargs[k] = v

        # Add timestamp
        kwargs["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Log using loguru
        getattr(self._logger, level)(event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        """Log info event with auto request context."""
        self._log("info", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Log warning event with auto request context."""
        self._log("warning", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Log error event with auto request context."""
        self._log("error", event, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        """Log debug event with auto request context."""
        self._log("debug", event, **kwargs)

    def exception(self, event: str, exc: Exception, **kwargs: Any) -> None:
        """Log exception with error details."""
        kwargs["error_type"] = type(exc).__name__
        kwargs["error_message"] = str(exc)
        self._log("error", event, **kwargs)


# Global logger instance
log = StructuredLogger()


# =============================================================================
# Legacy WideEvent Support (for backward compatibility)
# =============================================================================

@dataclass
class WideEvent:
    """Wide event for comprehensive request logging. Used by middleware."""

    request_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    start_time: float = field(default_factory=time.time)

    # Service context
    service: str = "gaia-api"
    environment: str = os.getenv("ENV", "production")

    # Request context
    method: Optional[str] = None
    path: Optional[str] = None
    query_params: Optional[dict[str, Any]] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # Response context
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None

    # User context
    user_id: Optional[str] = None
    subscription_tier: Optional[str] = None

    # Operation context
    operation: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    # Performance metrics
    db_query_count: int = 0
    db_query_duration_ms: float = 0.0
    external_call_count: int = 0
    external_call_duration_ms: float = 0.0
    cache_hit: Optional[bool] = None

    # LLM context
    model_name: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0

    # Error context
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Outcome
    outcome: str = "unknown"

    # Custom fields
    custom: dict[str, Any] = field(default_factory=dict)

    @property
    def is_vip(self) -> bool:
        vip_tiers = ("pro", "premium", "enterprise", "team")
        return self.subscription_tier and self.subscription_tier.lower() in vip_tiers

    def set_request_context(self, **kwargs: Any) -> "WideEvent":
        """Set request context fields."""
        for key in ("method", "path", "query_params", "client_ip", "user_agent", "trace_id"):
            if key in kwargs and kwargs[key] is not None:
                setattr(self, key, kwargs[key])
        return self

    def set_response_context(self, status_code: Optional[int] = None, **kwargs: Any) -> "WideEvent":
        """Set response context and calculate duration."""
        if status_code:
            self.status_code = status_code
        self.duration_ms = (time.time() - self.start_time) * 1000
        return self

    def set_user_context(self, user: Optional[dict] = None, **kwargs: Any) -> "WideEvent":
        """Set user context from user dict or kwargs."""
        if user:
            self.user_id = str(user.get("user_id") or user.get("_id") or "")
            self.subscription_tier = user.get("subscription_tier") or user.get("plan_type", "free")
        for key in ("user_id", "subscription_tier"):
            if key in kwargs and kwargs[key] is not None:
                setattr(self, key, kwargs[key])
        return self

    def set_operation(self, operation: str, resource_type: Optional[str] = None, resource_id: Optional[str] = None) -> "WideEvent":
        """Set operation context."""
        self.operation = operation
        if resource_type:
            self.resource_type = resource_type
        if resource_id:
            self.resource_id = resource_id
        return self

    def set_business_context(self, **kwargs: Any) -> "WideEvent":
        """Set custom business context."""
        self.custom.update(kwargs)
        return self

    def add_db_query(self, duration_ms: float) -> "WideEvent":
        """Record database query."""
        self.db_query_count += 1
        self.db_query_duration_ms += duration_ms
        return self

    def add_external_call(self, duration_ms: float) -> "WideEvent":
        """Record external API call."""
        self.external_call_count += 1
        self.external_call_duration_ms += duration_ms
        return self

    def set_cache_result(self, hit: bool, key: Optional[str] = None) -> "WideEvent":
        """Record cache result."""
        self.cache_hit = hit
        return self

    def set_llm_context(self, model_name: Optional[str] = None, input_tokens: int = 0, output_tokens: int = 0, **kwargs: Any) -> "WideEvent":
        """Set LLM context (accumulates tokens)."""
        if model_name:
            self.model_name = model_name
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        return self

    def set_error(self, exception: Optional[Exception] = None, **kwargs: Any) -> "WideEvent":
        """Set error context."""
        if exception:
            self.error_type = type(exception).__name__
            self.error_message = str(exception)
        for key in ("error_type", "error_message"):
            if key in kwargs:
                setattr(self, key, kwargs[key])
        self.outcome = "error"
        return self

    def complete(self, status_code: Optional[int] = None, outcome: str = "success") -> "WideEvent":
        """Complete the event."""
        self.duration_ms = (time.time() - self.start_time) * 1000
        if status_code:
            self.status_code = status_code
        self.outcome = outcome
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for logging."""
        result = {}
        for key, value in self.__dict__.items():
            if value is None or key == "start_time":
                continue
            if isinstance(value, dict) and not value:
                continue
            result[key] = value
        return result


# Context for WideEvent (legacy)
_current_wide_event: ContextVar[Optional[WideEvent]] = ContextVar("current_wide_event", default=None)


def get_current_event() -> Optional[WideEvent]:
    """Get current wide event (legacy)."""
    return _current_wide_event.get()


def set_current_event(event: WideEvent) -> None:
    """Set current wide event (legacy)."""
    _current_wide_event.set(event)


def clear_current_event() -> None:
    """Clear current wide event (legacy)."""
    _current_wide_event.set(None)


class WideEventLogger:
    """Logger for wide events with sampling."""

    def __init__(self, name: str = "WIDE"):
        self._logger = logger.bind(logger_name=name)

    def emit(self, event: WideEvent, force: bool = False) -> bool:
        """Emit wide event if it passes sampling."""
        if not force and not should_sample(
            status_code=event.status_code,
            duration_ms=event.duration_ms,
            is_error=event.outcome == "error",
            is_vip=event.is_vip,
        ):
            return False

        event_dict = event.to_dict()

        if event.outcome == "error" or (event.status_code and event.status_code >= 500):
            self._logger.error("wide_event", **event_dict)
        elif event.status_code and event.status_code >= 400:
            self._logger.warning("wide_event", **event_dict)
        else:
            self._logger.info("wide_event", **event_dict)

        return True

    def info(self, message: str, **context: Any) -> None:
        self._logger.info(message, **context)

    def warning(self, message: str, **context: Any) -> None:
        self._logger.warning(message, **context)

    def error(self, message: str, **context: Any) -> None:
        self._logger.error(message, **context)

    def debug(self, message: str, **context: Any) -> None:
        self._logger.debug(message, **context)


wide_logger = WideEventLogger()


def create_wide_event(service: str = "gaia-api", operation: Optional[str] = None) -> WideEvent:
    """Create a new wide event."""
    event = WideEvent(service=service)
    if operation:
        event.operation = operation
    return event


# Legacy exports for backward compatibility
SamplingDecision = type("SamplingDecision", (), {})  # Dummy for compatibility
get_sampling_config = lambda: _sampling_config
configure_sampling = lambda cfg: None


__all__ = [
    # New simple API
    "log",
    "get_request_context",
    "set_request_context",
    "clear_request_context",
    "RequestContext",
    "StructuredLogger",
    "should_sample",
    # Legacy WideEvent support
    "WideEvent",
    "WideEventLogger",
    "wide_logger",
    "get_current_event",
    "set_current_event",
    "clear_current_event",
    "create_wide_event",
    "SamplingConfig",
    "SamplingDecision",
    "get_sampling_config",
    "configure_sampling",
]
