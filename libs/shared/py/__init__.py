"""GAIA Shared Library.

Provides common utilities for GAIA applications including:
- Logging configuration (Loguru-based)
- Secrets management (Infisical)
- Base settings classes (Pydantic)
"""

from shared.py.logging import configure_file_logging, configure_loguru, get_contextual_logger

__all__ = [
    "configure_loguru",
    "configure_file_logging",
    "get_contextual_logger",
]

__version__ = "0.1.0"
