"""
Provides request_logger used by LoggingMiddleware to emit the final wide event.

All application code should use `from shared.py.wide_events import log` instead.
"""

import os

from shared.py.logging import configure_file_logging, get_contextual_logger

# Write rotating log files only when not running in Docker (LOG_FORMAT=json).
# In Docker, stdout JSON is captured by the daemon and shipped to Loki via
# Promtail — writing to the container filesystem wastes disk space.
if os.getenv("LOG_FORMAT", "console") != "json":
    configure_file_logging("./logs")

# Used exclusively by LoggingMiddleware to emit the final wide event as a
# structured JSON log line with logger_name="REQUEST".
request_logger = get_contextual_logger("REQUEST")

__all__ = ["request_logger"]
