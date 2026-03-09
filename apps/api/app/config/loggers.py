"""
Loguru configuration and the request_logger used by LoggingMiddleware.

All application code should use `from shared.py.wide_events import log`
instead of importing domain-specific loggers from here.

The request_logger is kept here because LoggingMiddleware uses it to emit
the final wide event as a structured JSON log line with the logger_name "REQUEST".
"""

from shared.py.logging import (
    configure_file_logging,
    configure_loguru,
    get_contextual_logger,
    logger,
)

# Enable file logging for the API
configure_file_logging("./logs")

# Used exclusively by LoggingMiddleware to emit the final wide event
request_logger = get_contextual_logger("requests")

__all__ = [
    "logger",
    "configure_loguru",
    "configure_file_logging",
    "get_contextual_logger",
    "request_logger",
]
