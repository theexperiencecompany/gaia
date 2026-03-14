"""GAIA Shared Library.

Provides common utilities for GAIA applications including:
- Logging configuration (Loguru-based)
- Wide event logging (one structured event per request)
- Secrets management (Infisical)
- Base settings classes (Pydantic)
"""

from shared.py.logging import (
    configure_file_logging,
    configure_loguru,
    get_contextual_logger,
)
from shared.py.utils.slugify import slugify
from shared.py.wide_events import log, wide_task

__all__ = [
    "configure_loguru",
    "configure_file_logging",
    "get_contextual_logger",
    "log",
    "slugify",
    "wide_task",
]

__version__ = "0.1.0"
