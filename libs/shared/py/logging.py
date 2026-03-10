"""
Advanced logging configuration for GAIA applications.

This module provides a comprehensive, production-ready logging system featuring:
- Beautiful console output with color coding and structured formatting
- Optional file outputs with automatic rotation and compression
- Thread-safe logging with message queuing
- Standard library logging interception for unified output
- Contextual logging with rich metadata support
- Custom log levels for different operational concerns

File logging is opt-in — call configure_file_logging(log_dir) explicitly from
apps that need it (e.g. the API). Console logging is always enabled on import.

Environment variables:
- LOG_LEVEL: Minimum log level (default: INFO)
- LOG_FORMAT: Output format — "console" (default) or "json" for production/Loki
- LOG_DIAGNOSE: Show error diagnosis (default: false)
- LOG_BACKTRACE: Show stack traces (default: true)
- LOG_COLORIZE: Colored console output (default: true, ignored in json mode)
- LOG_DIR: Directory to write log files into (default: ./logs)

Usage:
    from shared.py.logging import get_contextual_logger
    logger = get_contextual_logger("myapp")
    logger.info("Hello world")
"""

import json as _json
import os
import sys
import logging
from collections.abc import Callable
from pathlib import Path

from loguru import logger

_LOGURU_CONFIGURED = False
_FILE_LOGGING_CONFIGURED = False

LOG_CONFIG = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    # Set LOG_FORMAT=json in production Docker to emit newline-delimited JSON to
    # stdout. Promtail picks this up and ships it to Loki with zero parsing issues.
    # Default is "console" which keeps the colourised format for local development.
    "format_mode": os.getenv("LOG_FORMAT", "console"),
    "diagnose": os.getenv("LOG_DIAGNOSE", "false").lower() == "true",
    "backtrace": os.getenv("LOG_BACKTRACE", "true").lower() == "true",
    "colorize": os.getenv("LOG_COLORIZE", "true").lower() == "true",
    "log_dir": os.getenv("LOG_DIR", "./logs"),
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


def _build_json_entry(record: dict) -> str:
    """Serialize a loguru record to a flat NDJSON line.

    Produces one JSON object per line. Fields from `.bind()` calls are merged
    into the top-level object so that LogQL `| json` can filter on them directly.

    NOTE: must NOT be used as loguru's `format=` parameter — loguru treats
    callable formats as template generators and calls str.format_map() on the
    returned string, which breaks on JSON's curly braces. Use as a callable
    sink instead (see _json_stdout_sink).

    Example output:
        {"time": "2024-01-01T12:00:00+00:00", "level": "INFO", "logger": "REQUEST",
         "message": "http_request", "method": "GET", "path": "/api/v1/chat",
         "status_code": 200, "duration_ms": 234.56, "client_ip": "1.2.3.4"}
    """
    entry: dict[str, object] = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": record["extra"].get("logger_name", "app"),
        "message": record["message"],
        "module": record["module"],
        "line": record["line"],
    }

    for key, value in record["extra"].items():
        if key != "logger_name":
            entry[key] = value

    if record["exception"] is not None:
        exc = record["exception"]
        entry["exception"] = {
            "type": exc.type.__name__ if exc.type else None,
            "value": str(exc.value) if exc.value else None,
        }

    return _json.dumps(entry, default=str) + "\n"


def _json_stdout_sink(message: object) -> None:
    """Callable sink that writes flat JSON to stdout.

    Using a callable sink (not format=callable) bypasses loguru's str.format_map()
    post-processing, which would otherwise choke on the curly braces in JSON output.
    """
    record = message.record  # type: ignore[union-attr]
    sys.stdout.write(_build_json_entry(record))
    sys.stdout.flush()


def _json_file_sink_factory(log_dir: Path) -> "Callable[..., None]":
    """Create a callable sink that writes flat NDJSON to daily rotating files.

    Produces the same flat JSON format as _json_stdout_sink so that Promtail
    and Grafana dashboards work identically for local dev and Docker.
    """
    _handles: dict[str, object] = {}

    def _sink(message: object) -> None:
        record = message.record  # type: ignore[union-attr]
        date_str = record["time"].strftime("%Y-%m-%d")
        resolved = log_dir / f"structured-{date_str}.json"
        key = str(resolved)

        fh = _handles.get(key)
        if fh is None or fh.closed:  # type: ignore[union-attr]
            # Close stale handles from previous days before opening a new one
            for old_key in list(_handles):
                if old_key != key:
                    try:
                        _handles.pop(old_key).close()  # type: ignore[union-attr]
                    except Exception:
                        pass
            fh = open(resolved, "a", encoding="utf-8")  # noqa: SIM115
            _handles[key] = fh

        fh.write(_build_json_entry(record))  # type: ignore[union-attr]
        fh.flush()  # type: ignore[union-attr]

    return _sink


def configure_loguru():
    """
    Configure console logging with standard library interception.

    Safe to call multiple times — only configures once.

    When LOG_FORMAT=json, emits newline-delimited JSON to stdout (no ANSI codes)
    suitable for Promtail/Loki ingestion. Otherwise, uses the colourised console
    format suited for local development.

    Returns:
        Configured logger instance
    """
    global _LOGURU_CONFIGURED
    if _LOGURU_CONFIGURED:
        return logger
    _LOGURU_CONFIGURED = True

    logger.remove()

    # Set a global default for logger_name so format strings like
    # {extra[logger_name]} never raise KeyError on records that didn't
    # go through InterceptHandler or logger.bind(logger_name=...).
    logger.configure(extra={"logger_name": "APP"})

    if LOG_CONFIG["format_mode"] == "json":
        # Production: one JSON object per line → stdout → Promtail → Loki.
        # Uses a callable sink (not format=callable) to avoid loguru calling
        # str.format_map() on the JSON output, which breaks on curly braces.
        logger.add(
            _json_stdout_sink,
            level=LOG_CONFIG["level"],
            backtrace=False,
            diagnose=False,
            enqueue=True,
            catch=True,
        )
    else:
        # Development: colourised human-readable format → stderr
        logger.add(
            sys.stderr,
            format=LOG_CONFIG["format"]["console"],
            level=LOG_CONFIG["level"],
            colorize=LOG_CONFIG["colorize"],
            backtrace=LOG_CONFIG["backtrace"],
            diagnose=LOG_CONFIG["diagnose"],
            enqueue=True,
            catch=True,
        )

    # Custom levels — use numbers that don't collide with Loguru built-ins:
    # TRACE=5, DEBUG=10, INFO=20, SUCCESS=25, WARNING=30, ERROR=40, CRITICAL=50
    logger.level("PERFORMANCE", no=3, color="<magenta>", icon="⚡")
    logger.level("AUDIT", no=28, color="<blue>", icon="📊")
    logger.level("SECURITY", no=38, color="<red>", icon="🔒")

    # Intercept standard library logging to route through Loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            app_namespaces = [
                "app.",
                "uvicorn",
                "fastapi",
                "gunicorn",
                "livekit",
                "gaia_shared",
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
                "gunicorn": "GUNICORN",
                "livekit": "LIVEKIT",
            }

            if record.name.startswith("app."):
                context_name = record.name.split(".")[-1].upper()[:7]
            else:
                context_name = logger_name_map.get(record.name, record.name.upper()[:7])

            logger.bind(logger_name=context_name).opt(
                depth=depth, exception=record.exc_info
            ).log(level, record.getMessage())

    intercept_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "gunicorn",
        "livekit",
        "app",
    ]

    for logger_name in intercept_loggers:
        specific_logger = logging.getLogger(logger_name)
        specific_logger.handlers = [InterceptHandler()]
        specific_logger.propagate = False

    logging.getLogger("app").setLevel(logging.DEBUG)

    return logger


def configure_file_logging(log_dir: str | Path | None = None) -> None:
    """
    Add rotating file log sinks. Call this once from apps that need persistent logs.

    Creates separate files for general, error, structured JSON, critical,
    and performance logs — all with automatic rotation and compression.

    Safe to call multiple times — only configures once.

    Args:
        log_dir: Directory to write log files into (default: ./logs)
    """
    if log_dir is None:
        log_dir = LOG_CONFIG["log_dir"]
    global _FILE_LOGGING_CONFIGURED
    if _FILE_LOGGING_CONFIGURED:
        return
    _FILE_LOGGING_CONFIGURED = True

    logs_dir = Path(log_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        logs_dir / "gaia-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        backtrace=True,
        diagnose=LOG_CONFIG["diagnose"],
        enqueue=False,
        catch=True,
    )

    logger.add(
        logs_dir / "errors-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="ERROR",
        rotation="10 MB",
        retention="90 days",
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=False,
        catch=True,
    )

    logger.add(
        _json_file_sink_factory(logs_dir),
        level="INFO",
        backtrace=False,
        diagnose=False,
        enqueue=True,
        catch=True,
    )

    logger.add(
        logs_dir / "critical-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="CRITICAL",
        rotation="1 MB",
        retention="1 year",
        compression="zip",
        backtrace=True,
        diagnose=True,
        enqueue=False,
        catch=True,
    )

    # Captures any log where .bind(performance=...) was used, regardless of level.
    # Use logger.bind(performance=True).info("...") to route to this file.
    logger.add(
        logs_dir / "performance-{time:YYYY-MM-DD}.log",
        format=LOG_CONFIG["format"]["file"],
        level="TRACE",
        rotation="20 MB",
        retention="7 days",
        compression="zip",
        filter=lambda record: "performance" in record["extra"],
        backtrace=False,
        diagnose=False,
        enqueue=False,
        catch=True,
    )


def get_contextual_logger(name: str, **context: object):
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


# Initialize console logging on import
configure_loguru()

__all__ = [
    "logger",
    "configure_loguru",
    "configure_file_logging",
    "get_contextual_logger",
]
