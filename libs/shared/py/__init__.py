"""GAIA Shared Library.

Provides common utilities for GAIA applications including:
- Logging configuration (Loguru-based)
- Wide event logging for comprehensive request tracing
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

__all__ = [
    "configure_loguru",
    "get_contextual_logger",
    # Wide event exports
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
