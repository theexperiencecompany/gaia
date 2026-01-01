"""GAIA Shared Library.

Provides common utilities for GAIA applications including:
- Logging configuration (Loguru-based)
- Structured logging with auto request context capture
- Secrets management (Infisical)
- Base settings classes (Pydantic)
"""

from shared.py.logging import (
    configure_loguru,
    get_contextual_logger,
    WideEvent,
    WideEventLogger,
    wide_logger,
    SamplingConfig,
    SamplingDecision,
    should_sample,
    get_sampling_config,
    configure_sampling,
    get_current_event,
    set_current_event,
    clear_current_event,
    create_wide_event,
)

# New simplified logging API
from shared.py.wide_events import (
    log,
    get_request_context,
    set_request_context,
    clear_request_context,
    RequestContext,
    StructuredLogger,
)

__all__ = [
    "configure_loguru",
    "get_contextual_logger",
    # New simple API
    "log",
    "get_request_context",
    "set_request_context",
    "clear_request_context",
    "RequestContext",
    "StructuredLogger",
    # Legacy wide event exports
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

__version__ = "0.1.0"
