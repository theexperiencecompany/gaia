"""
Advanced logging configuration for GAIA backend application.

This module provides a comprehensive, production-ready logging system featuring:
- Beautiful console output with color coding and structured formatting
- Multiple log file outputs with automatic rotation and compression
- Structured JSON logging for production analysis and monitoring
- Performance tracking and audit trail capabilities
- Custom log levels for different operational concerns
- Thread-safe logging with message queuing
- Standard library logging interception for unified output
- Contextual logging with rich metadata support

The logging system automatically creates separate log files for:
- General application logs (daily rotation)
- Error logs (size-based rotation, longer retention)
- Structured JSON logs for machine analysis
- Critical issues (retained for one year)
- Performance metrics (short-term retention)

Features include automatic log compression, configurable retention policies,
and seamless integration with existing standard library logging infrastructure.
"""

import os
import sys
from pathlib import Path
import logging
from loguru import logger

# Create logs directory if it doesn't exist
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


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
        "file": (
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <4} | "
            "{extra[logger_name]: <7} | "
            "{message} | "
            "{file.name}:{function}:{line}"
        ),
        "json": "{time} {level} {extra[logger_name]} {message} {file.name} {function} {line}{extra}",
    },
}


def configure_loguru():
    """
    Configure production-ready logging with multiple outputs and rotation.

    Sets up:
    - Console: Colored output for development
    - Files: General (daily), errors (10MB), JSON (50MB), critical (1MB), performance (20MB)
    - Custom levels: PERFORMANCE, AUDIT, SECURITY
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

    # General application logs with rotation
    logger.add(
        LOGS_DIR / "gaia-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="DEBUG",
        rotation="00:00",  # Rotate at midnight
        retention="30 days",  # Keep logs for 30 days
        compression="zip",  # Compress old logs
        backtrace=True,
        diagnose=LOG_CONFIG["diagnose"],
        enqueue=True,
        catch=True,
    )

    # Error logs (separate file for errors and above)
    logger.add(
        LOGS_DIR / "errors-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="ERROR",
        rotation="10 MB",  # Rotate when file reaches 10MB
        retention="90 days",  # Keep error logs longer
        compression="zip",
        backtrace=True,
        diagnose=True,  # Always diagnose for errors
        enqueue=True,
        catch=True,
    )

    # Structured JSON logs for production analysis
    logger.add(
        LOGS_DIR / "structured-{time:YYYY-MM-DD}.json",
        format=LOG_CONFIG["format"]["json"],
        level="INFO",
        rotation="50 MB",
        retention="60 days",
        compression="zip",
        serialize=True,  # JSON serialization
        backtrace=False,  # Skip backtrace for structured logs
        diagnose=False,
        enqueue=True,
        catch=True,
    )

    # Critical logs (CRITICAL level only)
    logger.add(
        LOGS_DIR / "critical-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="CRITICAL",
        rotation="1 MB",
        retention="1 year",  # Keep critical logs for a year
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=True,
        catch=True,
    )

    # Performance logs (for profiling and monitoring)
    logger.add(
        LOGS_DIR / "performance-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="TRACE",
        rotation="20 MB",
        retention="7 days",  # Short retention for performance logs
        compression="zip",
        filter=lambda record: "performance" in record["extra"],
        backtrace=False,
        diagnose=False,
        enqueue=True,
        catch=True,
    )

    # Add custom levels
    logger.level("PERFORMANCE", no=5, color="<magenta>", icon="⚡")
    logger.level("AUDIT", no=25, color="<blue>", icon="📊")
    logger.level("SECURITY", no=35, color="<red>", icon="🔒")

    # Intercept standard library logging to route through Loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Only intercept loggers from our app namespace or specific important ones
            app_namespaces = [
                "app.",  # Our main app
                "uvicorn",  # Web server
                "fastapi",  # Framework
                "gunicorn",  # Alternative WSGI server
            ]

            # Check if this logger should be intercepted
            should_intercept = any(
                record.name.startswith(namespace)
                or record.name == namespace.rstrip(".")
                for namespace in app_namespaces
            )

            if not should_intercept:
                return  # Let other loggers use their default handlers

            # Get corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where originated the logged message
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            # Map common logger names to our context names
            logger_name_map = {
                "uvicorn.access": "UVICORN",
                "uvicorn.error": "UVICORN",
                "uvicorn": "UVICORN",
                "fastapi": "FASTAPI",
                "gunicorn": "GUNICORN",
            }

            # Get the appropriate logger name
            if record.name.startswith("app."):
                # For app loggers, use the module name
                context_name = record.name.split(".")[-1].upper()
            else:
                context_name = logger_name_map.get(record.name, record.name.upper())

            logger.bind(logger_name=context_name).opt(
                depth=depth, exception=record.exc_info
            ).log(level, record.getMessage())

    # Only intercept specific loggers we care about
    intercept_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "gunicorn",
        "app",  # Root app logger
    ]

    for logger_name in intercept_loggers:
        specific_logger = logging.getLogger(logger_name)
        specific_logger.handlers = [InterceptHandler()]
        specific_logger.propagate = False

    # Set the root app logger to use our handler
    logging.getLogger("app").setLevel(logging.DEBUG)

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

        >>> db_logger = get_contextual_logger("database", connection="primary")
        >>> db_logger.error("Connection failed")  # Includes connection info
    """
    # Ensure logger_name is always present for formatting
    context["logger_name"] = name.upper()
    return logger.bind(**context)


# Initialize Loguru configuration
configure_loguru()

# Export the configured logger
__all__ = [
    "logger",
    "get_contextual_logger",
]
