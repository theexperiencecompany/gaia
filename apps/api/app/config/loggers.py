"""
Provides request_logger used by LoggingMiddleware to emit the final wide event.

All application code should use `from shared.py.wide_events import log` instead.
"""

from shared.py.logging import configure_file_logging, get_contextual_logger

# Rotating log files for local development; a no-op under LOG_FORMAT=json,
# where stdout NDJSON is shipped to Loki instead (see configure_file_logging).
configure_file_logging("./logs")

# Used exclusively by LoggingMiddleware to emit the final wide event as a
# structured JSON log line with logger_name=REQUEST_LOGGER_NAME.
REQUEST_LOGGER_NAME = "REQUEST"
request_logger = get_contextual_logger(REQUEST_LOGGER_NAME)

__all__ = ["REQUEST_LOGGER_NAME", "request_logger"]
