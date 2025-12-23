"""
Advanced logging configuration for GAIA applications.

This module provides a comprehensive, production-ready logging system featuring:
- Beautiful console output with color coding and structured formatting
- Thread-safe logging with message queuing
- Standard library logging interception for unified output
- Contextual logging with rich metadata support

Usage:
    from shared.py.logging import get_contextual_logger
    logger = get_contextual_logger("myapp")
    logger.info("Hello world")
"""

import os
import sys
import logging
from loguru import logger


# Application-wide logging configuration
LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    "diagnose": os.getenv("LOG_DIAGNOSE", "false").lower() == "true",
    "backtrace": os.getenv("LOG_BACKTRACE", "true").lower() == "true",
    "colorize": os.getenv("LOG_COLORIZE", "true").lower() == "true",
    "format": {
        "console": (
            "<green>{time:MM-DD HH:mm:ss}</green> | "
            "<level>{level: <4}</level> | "
            "<blue>{extra[logger_name]: <7}</blue> | "
            "<level>{message}</level> "
            "<dim><cyan>({file.name}:{line})</cyan></dim>"
        ),
    },
}


def configure_loguru():
    """
    Configure production-ready logging with console output.

    Sets up:
    - Console: Colored output for development and containers
    - Standard library interception for unified logging

    Environment variables:
    - LOG_LEVEL: Minimum level (default: INFO)
    - LOG_DIAGNOSE: Error diagnosis (default: false)
    - LOG_BACKTRACE: Stack traces (default: true)
    - LOG_COLORIZE: Colored output (default: true)

    Returns:
        Configured logger instance
    """
    # Remove default handler
    logger.remove()

    # Console handler with beautiful formatting
    logger.add(
        sys.stderr,
        format=LOG_CONFIG["format"]["console"],
        level=LOG_CONFIG["level"],
        colorize=LOG_CONFIG["colorize"],
        backtrace=LOG_CONFIG["backtrace"],
        diagnose=LOG_CONFIG["diagnose"],
        enqueue=True,  # Thread-safe logging
        catch=True,  # Catch exceptions in threads
    )

    # Intercept standard library logging to route through Loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Only intercept loggers from specific namespaces
            app_namespaces = [
                "gaia_shared",
                "uvicorn",
                "fastapi",
                "livekit",
            ]

            should_intercept = any(
                record.name.startswith(namespace)
                or record.name == namespace.rstrip(".")
                for namespace in app_namespaces
            )

            if not should_intercept:
                return

            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger_name_map = {
                "uvicorn.access": "UVICORN",
                "uvicorn.error": "UVICORN",
                "uvicorn": "UVICORN",
                "fastapi": "FASTAPI",
                "livekit": "LIVEKIT",
            }

            context_name = logger_name_map.get(record.name, record.name.upper()[:7])

            logger.bind(logger_name=context_name).opt(
                depth=depth, exception=record.exc_info
            ).log(level, record.getMessage())

    # Only intercept specific loggers
    intercept_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "livekit",
    ]

    for logger_name in intercept_loggers:
        specific_logger = logging.getLogger(logger_name)
        specific_logger.handlers = [InterceptHandler()]
        specific_logger.propagate = False

    return logger


def get_contextual_logger(name: str, **context):
    """
    Create a contextual logger with automatic context injection.

    Args:
        name: Logger name (e.g., "auth", "database", "api")
        **context: Additional context (user_id, request_id, etc.)

    Returns:
        Bound logger with context included in all messages

    Examples:
        >>> auth_logger = get_contextual_logger("auth", user_id=123)
        >>> auth_logger.info("User login")  # Includes user_id=123
    """
    context["logger_name"] = name.upper()[:7]
    return logger.bind(**context)


# Initialize Loguru configuration on import
configure_loguru()

__all__ = [
    "logger",
    "configure_loguru",
    "get_contextual_logger",
]
