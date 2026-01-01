"""
Wide Event Logging System for GAIA Applications.

This module implements the Wide Event / Canonical Log Line pattern for comprehensive,
high-cardinality, high-dimensionality structured logging. Instead of multiple scattered
log lines per request, this system emits one comprehensive event per request with all
relevant business and technical context.

Key Features:
- One wide event per request/operation with 50+ contextual fields
- Tail-based sampling: always keep errors, slow requests, and VIP users
- High-cardinality fields (user_id, trace_id, request_id) for precise debugging
- Business context (subscription tier, feature flags, operation details)
- Performance metrics (duration, db queries, external calls)

Usage:
    from shared.py.wide_events import WideEvent, WideEventLogger, should_sample

    # Create a wide event
    event = WideEvent(service="checkout-service")
    event.set_request_context(method="POST", path="/api/checkout")
    event.set_user_context(user_id="user_123", subscription="premium")
    event.set_business_context(cart_items=3, total_cents=15999)

    # Emit the event
    wide_logger.emit(event)

Sampling Strategy:
    - 100% of errors (status >= 500, exceptions)
    - 100% of slow requests (above p99 threshold)
    - 100% of VIP/premium users
    - 100% of flagged feature experiments
    - Configurable % of successful requests (default 5%)
"""

import os
import random
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from loguru import logger


class SamplingDecision(Enum):
    """Reason for keeping or dropping an event."""

    ALWAYS_KEEP_ERROR = "error"
    ALWAYS_KEEP_SLOW = "slow_request"
    ALWAYS_KEEP_VIP = "vip_user"
    ALWAYS_KEEP_FEATURE_FLAG = "feature_flag"
    ALWAYS_KEEP_DEBUG = "debug_mode"
    FORCED = "forced"  # Explicitly forced by caller
    RANDOM_SAMPLE = "random_sample"
    DROPPED = "dropped"


@dataclass
class SamplingConfig:
    """Configuration for tail-based sampling."""

    # Sample rates (0.0 to 1.0)
    success_sample_rate: float = float(
        os.getenv("LOG_SUCCESS_SAMPLE_RATE", "0.05")
    )  # 5% of successful requests

    # Thresholds for always-keep decisions
    slow_request_threshold_ms: int = int(
        os.getenv("LOG_SLOW_REQUEST_THRESHOLD_MS", "2000")
    )  # 2 seconds
    error_status_threshold: int = 500

    # VIP tiers that always get logged
    vip_subscription_tiers: tuple[str, ...] = ("pro", "premium", "enterprise", "team")

    # Feature flags that always get logged (for experiment tracking)
    tracked_feature_flags: tuple[str, ...] = (
        "new_checkout_flow",
        "experimental_agent",
        "beta_features",
    )

    # Debug mode - log everything
    debug_mode: bool = os.getenv("LOG_DEBUG_MODE", "false").lower() == "true"


# Global sampling config
_sampling_config = SamplingConfig()


def get_sampling_config() -> SamplingConfig:
    """Get the global sampling configuration."""
    return _sampling_config


def configure_sampling(config: SamplingConfig) -> None:
    """Configure global sampling settings."""
    global _sampling_config
    _sampling_config = config


@dataclass
class WideEvent:
    """
    A comprehensive wide event for structured logging.

    This represents a single, context-rich log event that captures everything
    needed to debug a request/operation without requiring additional log searches.
    """

    # Core identifiers (high cardinality - essential for debugging)
    request_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None

    # Timestamps
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    start_time: float = field(default_factory=time.time)

    # Service context
    service: str = "gaia-api"
    version: str = os.getenv("SERVICE_VERSION", "unknown")
    deployment_id: str = os.getenv("DEPLOYMENT_ID", "unknown")
    region: str = os.getenv("REGION", "unknown")
    environment: str = os.getenv("ENV", "production")
    worker_type: str = os.getenv("WORKER_TYPE", "unknown")

    # Request context
    method: Optional[str] = None
    path: Optional[str] = None
    query_params: Optional[dict[str, Any]] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None

    # Response context
    status_code: Optional[int] = None
    duration_ms: Optional[float] = None
    bytes_sent: Optional[int] = None

    # User context (high cardinality - essential for user-specific debugging)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    subscription_tier: Optional[str] = None
    account_age_days: Optional[int] = None
    is_vip: bool = False

    # Business context
    operation: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None

    # Feature flags
    feature_flags: dict[str, bool] = field(default_factory=dict)

    # Performance metrics
    db_query_count: int = 0
    db_query_duration_ms: float = 0.0
    cache_hit: Optional[bool] = None
    cache_key: Optional[str] = None
    external_call_count: int = 0
    external_call_duration_ms: float = 0.0

    # LLM/AI specific context
    model_name: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_latency_ms: float = 0.0
    conversation_id: Optional[str] = None
    message_count: int = 0

    # Error context
    error_type: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_retriable: bool = False
    stack_trace: Optional[str] = None

    # Outcome
    outcome: str = "unknown"  # success, error, timeout, cancelled

    # Custom business fields (flexible dict for domain-specific data)
    custom: dict[str, Any] = field(default_factory=dict)

    # Sampling metadata
    sampling_decision: Optional[str] = None

    def set_request_context(
        self,
        method: Optional[str] = None,
        path: Optional[str] = None,
        query_params: Optional[dict[str, Any]] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> "WideEvent":
        """Set HTTP request context."""
        if method:
            self.method = method
        if path:
            self.path = path
        if query_params:
            self.query_params = query_params
        if client_ip:
            self.client_ip = client_ip
        if user_agent:
            self.user_agent = user_agent
        if trace_id:
            self.trace_id = trace_id
        return self

    def set_response_context(
        self,
        status_code: Optional[int] = None,
        bytes_sent: Optional[int] = None,
    ) -> "WideEvent":
        """Set HTTP response context and calculate duration."""
        if status_code:
            self.status_code = status_code
        if bytes_sent:
            self.bytes_sent = bytes_sent
        self.duration_ms = (time.time() - self.start_time) * 1000
        return self

    def set_user_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        subscription_tier: Optional[str] = None,
        account_age_days: Optional[int] = None,
        user: Optional[dict[str, Any]] = None,
    ) -> "WideEvent":
        """Set user context from user dict or individual fields."""
        if user:
            raw_user_id = user.get("user_id") or user.get("_id")
            # Handle ObjectId or other complex types by extracting string representation
            if raw_user_id is not None:
                if isinstance(raw_user_id, dict) and "$oid" in raw_user_id:
                    self.user_id = raw_user_id["$oid"]
                else:
                    self.user_id = str(raw_user_id) if raw_user_id else None
            self.subscription_tier = user.get("subscription_tier") or user.get(
                "plan_type", "free"
            )
            created_at = user.get("created_at")
            if created_at and isinstance(created_at, datetime):
                # Handle both timezone-aware and naive datetime objects
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                self.account_age_days = (datetime.now(timezone.utc) - created_at).days
        if user_id:
            self.user_id = user_id
        if session_id:
            self.session_id = session_id
        if subscription_tier:
            self.subscription_tier = subscription_tier
        if account_age_days:
            self.account_age_days = account_age_days

        # Mark VIP status
        config = get_sampling_config()
        if self.subscription_tier and self.subscription_tier.lower() in [
            t.lower() for t in config.vip_subscription_tiers
        ]:
            self.is_vip = True

        return self

    def set_business_context(self, **kwargs: Any) -> "WideEvent":
        """Set arbitrary business context fields."""
        self.custom.update(kwargs)
        return self

    def set_operation(
        self,
        operation: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
    ) -> "WideEvent":
        """Set the operation being performed."""
        self.operation = operation
        if resource_type:
            self.resource_type = resource_type
        if resource_id:
            self.resource_id = resource_id
        return self

    def set_feature_flags(self, flags: dict[str, bool]) -> "WideEvent":
        """Set active feature flags for this request."""
        self.feature_flags = flags
        return self

    def add_db_query(self, duration_ms: float) -> "WideEvent":
        """Record a database query."""
        self.db_query_count += 1
        self.db_query_duration_ms += duration_ms
        return self

    def add_external_call(self, duration_ms: float) -> "WideEvent":
        """Record an external API call."""
        self.external_call_count += 1
        self.external_call_duration_ms += duration_ms
        return self

    def set_cache_result(self, hit: bool, key: Optional[str] = None) -> "WideEvent":
        """Record cache lookup result."""
        self.cache_hit = hit
        if key:
            self.cache_key = key
        return self

    def set_llm_context(
        self,
        model_name: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        conversation_id: Optional[str] = None,
        message_count: int = 0,
    ) -> "WideEvent":
        """
        Set LLM/AI operation context.

        Note: Token counts and latency are accumulated when called multiple times
        within a single request. This is intentional to support scenarios where
        multiple LLM calls are made (e.g., agent with multiple tool calls).
        The model_name will be overwritten with the most recent value.
        """
        if model_name:
            self.model_name = model_name
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.model_latency_ms += latency_ms
        if conversation_id:
            self.conversation_id = conversation_id
        if message_count:
            self.message_count = message_count
        return self

    def set_error(
        self,
        error_type: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        error_retriable: bool = False,
        exception: Optional[Exception] = None,
    ) -> "WideEvent":
        """Set error context."""
        if exception:
            self.error_type = type(exception).__name__
            self.error_message = str(exception)
        if error_type:
            self.error_type = error_type
        if error_code:
            self.error_code = error_code
        if error_message:
            self.error_message = error_message
        self.error_retriable = error_retriable
        self.outcome = "error"
        return self

    def complete(
        self, status_code: Optional[int] = None, outcome: str = "success"
    ) -> "WideEvent":
        """Mark the event as complete and calculate final metrics."""
        self.duration_ms = (time.time() - self.start_time) * 1000
        if status_code:
            self.status_code = status_code
        self.outcome = outcome
        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging, excluding None values."""
        result = {}
        for key, value in self.__dict__.items():
            if value is None:
                continue
            if isinstance(value, dict) and not value:
                continue
            if key == "start_time":
                continue  # Internal use only
            result[key] = value
        return result


# Context variable for the current request's wide event
_current_wide_event: ContextVar[Optional[WideEvent]] = ContextVar(
    "current_wide_event", default=None
)


def get_current_event() -> Optional[WideEvent]:
    """Get the wide event for the current request context."""
    return _current_wide_event.get()


def set_current_event(event: WideEvent) -> None:
    """Set the wide event for the current request context."""
    _current_wide_event.set(event)


def clear_current_event() -> None:
    """Clear the wide event for the current request context."""
    _current_wide_event.set(None)


def should_sample(event: WideEvent) -> SamplingDecision:
    """
    Determine if an event should be sampled (kept) using tail-based sampling.

    Tail sampling makes the decision AFTER the request completes, based on outcome.
    This ensures we never lose important events while managing costs.

    Rules:
    1. Always keep errors (status >= 500, exceptions)
    2. Always keep slow requests (above p99 threshold)
    3. Always keep VIP users (premium, enterprise tiers)
    4. Always keep requests with tracked feature flags
    5. Random sample the rest at configured rate

    Returns:
        SamplingDecision indicating why event was kept or dropped
    """
    config = get_sampling_config()

    # Debug mode - keep everything
    if config.debug_mode:
        return SamplingDecision.ALWAYS_KEEP_DEBUG

    # Always keep errors
    if event.status_code and event.status_code >= config.error_status_threshold:
        return SamplingDecision.ALWAYS_KEEP_ERROR
    if event.error_type or event.outcome == "error":
        return SamplingDecision.ALWAYS_KEEP_ERROR

    # Always keep slow requests
    if (
        event.duration_ms
        and event.duration_ms > config.slow_request_threshold_ms
    ):
        return SamplingDecision.ALWAYS_KEEP_SLOW

    # Always keep VIP users
    if event.is_vip:
        return SamplingDecision.ALWAYS_KEEP_VIP

    # Always keep requests with tracked feature flags
    for flag in config.tracked_feature_flags:
        if event.feature_flags.get(flag):
            return SamplingDecision.ALWAYS_KEEP_FEATURE_FLAG

    # Random sample the rest
    if random.random() < config.success_sample_rate:
        return SamplingDecision.RANDOM_SAMPLE

    return SamplingDecision.DROPPED


class WideEventLogger:
    """
    Logger for wide events with tail-based sampling.

    Usage:
        wide_logger = WideEventLogger()
        event = WideEvent(service="api")
        # ... populate event ...
        wide_logger.emit(event)
    """

    def __init__(self, name: str = "WIDE"):
        self._logger = logger.bind(logger_name=name)
        self._name = name

    def emit(self, event: WideEvent, force: bool = False) -> bool:
        """
        Emit a wide event if it passes sampling.

        Args:
            event: The wide event to emit
            force: If True, skip sampling and always emit

        Returns:
            True if event was emitted, False if dropped by sampling
        """
        # Determine sampling decision
        decision = SamplingDecision.FORCED if force else should_sample(event)
        event.sampling_decision = decision.value

        # Drop if not sampled
        if decision == SamplingDecision.DROPPED:
            return False

        # Convert to dict and emit
        event_dict = event.to_dict()

        # Log at appropriate level based on outcome
        if event.outcome == "error" or (
            event.status_code and event.status_code >= 500
        ):
            self._logger.error("wide_event", **event_dict)
        elif event.status_code and event.status_code >= 400:
            self._logger.warning("wide_event", **event_dict)
        else:
            self._logger.info("wide_event", **event_dict)

        return True

    def info(self, message: str, **context: Any) -> None:
        """Emit an info-level structured log with context."""
        self._logger.info(message, **context)

    def warning(self, message: str, **context: Any) -> None:
        """Emit a warning-level structured log with context."""
        self._logger.warning(message, **context)

    def error(self, message: str, **context: Any) -> None:
        """Emit an error-level structured log with context."""
        self._logger.error(message, **context)

    def debug(self, message: str, **context: Any) -> None:
        """Emit a debug-level structured log with context."""
        self._logger.debug(message, **context)


# Global wide event logger instance
wide_logger = WideEventLogger()


def create_wide_event(
    service: str = "gaia-api",
    operation: Optional[str] = None,
) -> WideEvent:
    """
    Create a new wide event and optionally set it as current.

    Args:
        service: Service name
        operation: Operation being performed

    Returns:
        New WideEvent instance
    """
    event = WideEvent(service=service)
    if operation:
        event.operation = operation
    return event


__all__ = [
    "WideEvent",
    "WideEventLogger",
    "wide_logger",
    "SamplingConfig",
    "SamplingDecision",
    "should_sample",
    "get_sampling_config",
    "configure_sampling",
    "get_current_event",
    "set_current_event",
    "clear_current_event",
    "create_wide_event",
]
