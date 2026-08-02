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
apps that need it (e.g. the API). It no-ops under LOG_FORMAT=json, so callers
never repeat that check. Console logging is always enabled on import.

Environment variables:
- LOG_LEVEL: Minimum log level (default: INFO)
- LOG_FORMAT: Output format — "console" (default) or "json" for production/Loki
- LOG_DIAGNOSE: Show error diagnosis (default: false)
- LOG_BACKTRACE: Show stack traces (default: true)
- LOG_COLORIZE: Colored console output (default: true, ignored in json mode)
- LOG_DIR: Directory to write log files into (default: ./logs)

Usage: app code logs through the wide-event facade (``from
shared.py.wide_events import log``), never this module directly — importing
this module (which the facade's package init does) is what activates the
sinks. ``get_contextual_logger`` exists for shared/infra code that needs a
raw loguru logger outside the wide-event lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
import json as _json
import logging
from math import isfinite
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, TextIO, TypedDict

from loguru import logger

if TYPE_CHECKING:
    from loguru import Message, Record


class _LogFormats(TypedDict):
    console: str
    file: str
    json: str


class _LogConfig(TypedDict):
    level: str
    format_mode: str
    diagnose: bool
    backtrace: bool
    colorize: bool
    log_dir: str
    format: _LogFormats


_LOGURU_CONFIGURED = False
_FILE_LOGGING_CONFIGURED = False

# Top-level keys every JSON line is built from. Extra fields must never
# overwrite them — a colliding key is re-emitted under _COLLIDING_KEY_PREFIX.
_CORE_KEYS = frozenset({"time", "level", "logger", "message", "module", "line", "worker"})
_COLLIDING_KEY_PREFIX = "ctx_"
# Extra keys consumed into the core entry (never re-emitted as extra fields).
_CONSUMED_EXTRA_KEYS = frozenset({"logger_name", "worker"})
# Loki rejects lines over its max_line_size (256KB by default) — cap below it.
MAX_JSON_LINE_BYTES = 200_000
# Matches Loki's retention_period (infra/docker/observability/loki-config.yaml)
# and the gaia-*.log sink, so local structured files age out at the same rate.
STRUCTURED_LOG_RETENTION_DAYS = 30
_TRUNCATED_MESSAGE_MAX_CHARS = 10_000

LOG_CONFIG: _LogConfig = {
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
            "<dim>{extra[worker]: <5}</dim> | "
            "<level>{message}</level> "
            "<dim><cyan>({file.name}:{line})</cyan></dim>"
        ),
        "file": (
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <4} | "
            "{extra[logger_name]: <7} | "
            "{extra[worker]: <5} | "
            "{message} | "
            "{file.name}:{function}:{line}"
        ),
        "json": "{time} {level} {extra[logger_name]} {message} {file.name} {function} {line}{extra}",
    },
}


def _core_fields(entry: dict[str, object]) -> dict[str, object]:
    return {
        key: entry[key]
        for key in ("time", "level", "logger", "message", "module", "line", "worker")
    }


def _finite(value: object) -> object:
    """Recursively replace non-finite floats with ``None``.

    Only called after a non-finite value has already been detected, so the
    common path never pays for this walk.
    """
    if isinstance(value, float):
        # bool is not a float, and int cannot be non-finite, so this is total.
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value


def _dumps(entry: object) -> str:
    """Serialize one log line as RFC-8259 JSON.

    ``json.dumps`` emits bare ``NaN``/``Infinity`` by default. Python reads
    those back happily, so the defect is invisible locally — but they are not
    valid JSON, and Loki's ``| json`` (Go) rejects the whole line. The event is
    still ingested as raw text, so it silently disappears from every structured
    query instead of failing loudly. A single ``x / 0`` behind an average (say a
    latency mean over zero samples) is enough to lose the event.

    ``allow_nan=False`` turns that into a ValueError we can catch, so the fast
    path stays the C encoder and only a line that actually contains a
    non-finite float pays for the scrub. Non-finite becomes ``null``, matching
    what the TypeScript bots emit for the same values.
    """
    try:
        return _json.dumps(entry, default=str, allow_nan=False)
    except ValueError:
        return _json.dumps(_finite(entry), default=str, allow_nan=False)


def _sanitized_entry(entry: dict[str, object], exc: Exception) -> dict[str, object]:
    """Fallback entry when the full record cannot be serialized.

    `default=str` cannot save non-str dict keys or circular structures — rather
    than dropping the whole line, preserve the core fields (all plain str/int,
    always serializable) plus trace_id, and record what went wrong.
    """
    sanitized = _core_fields(entry)
    if "trace_id" in entry:
        sanitized["trace_id"] = str(entry["trace_id"])
    sanitized["serialization_error"] = type(exc).__name__
    return sanitized


def _truncated_entry(entry: dict[str, object], original_size_bytes: int) -> dict[str, object]:
    """Minimal entry emitted when the full line would exceed MAX_JSON_LINE_BYTES."""
    truncated = _core_fields(entry)
    truncated["message"] = str(entry["message"])[:_TRUNCATED_MESSAGE_MAX_CHARS]
    if "trace_id" in entry:
        truncated["trace_id"] = str(entry["trace_id"])
    truncated["line_truncated"] = True
    truncated["original_size_bytes"] = original_size_bytes
    return truncated


def _build_json_entry(record: Record) -> str:
    """Serialize a loguru record to a flat NDJSON line — total, never raises.

    Produces one JSON object per line. Fields from `.bind()` calls are merged
    into the top-level object so that LogQL `| json` can filter on them directly.
    Three guarantees keep the sink total:

    - Core keys always win: an extra field colliding with a core key (e.g.
      `log.set(level=...)`) is emitted as `ctx_<key>` instead of corrupting the
      line's real level/message.
    - Serialization never drops a record: unserializable extras (non-str dict
      keys, circular refs) fall back to a sanitized entry carrying the core
      fields, trace_id and `serialization_error`.
    - Lines are capped at MAX_JSON_LINE_BYTES: oversized lines are replaced by
      a minimal entry with `line_truncated` + `original_size_bytes`, so Loki
      (default max_line_size 256KB) never rejects them.

    NOTE: must NOT be used as loguru's `format=` parameter — loguru treats
    callable formats as template generators and calls str.format_map() on the
    returned string, which breaks on JSON's curly braces. Use as a callable
    sink instead (see _json_stdout_sink).

    Example output:
        {"time": "2024-01-01T12:00:00+00:00", "level": "INFO", "logger": "REQUEST",
         "message": "http_request", "method": "GET", "path": "/api/v1/chat",
         "status_code": 200, "duration_ms": 234.56, "client_ip": "1.2.3.4"}
    """
    extra = record["extra"]
    entry: dict[str, object] = {
        "time": record["time"].isoformat(),
        "level": record["level"].name,
        "logger": extra.get("logger_name", "app"),
        "message": record["message"],
        "module": record["module"],
        "line": record["line"],
        "worker": extra.get("worker", "main"),
    }

    for key, value in extra.items():
        if key in _CONSUMED_EXTRA_KEYS:
            continue
        entry[f"{_COLLIDING_KEY_PREFIX}{key}" if key in _CORE_KEYS else key] = value

    if record["exception"] is not None:
        exc = record["exception"]
        entry["exception"] = {
            "type": exc.type.__name__ if exc.type else None,
            "value": str(exc.value) if exc.value else None,
        }

    try:
        line = _dumps(entry)
    except (TypeError, ValueError) as serialization_exc:
        line = _dumps(_sanitized_entry(entry, serialization_exc))

    original_size_bytes = len(line.encode("utf-8"))
    if original_size_bytes > MAX_JSON_LINE_BYTES:
        line = _dumps(_truncated_entry(entry, original_size_bytes))

    return line + "\n"


def _json_stdout_sink(message: Message) -> None:
    """Callable sink that writes flat JSON to stdout.

    Using a callable sink (not format=callable) bypasses loguru's str.format_map()
    post-processing, which would otherwise choke on the curly braces in JSON output.
    """
    record = message.record
    sys.stdout.write(_build_json_entry(record))
    sys.stdout.flush()


def _prune_structured_logs(log_dir: Path, today: date) -> None:
    """Delete structured-*.json files older than the retention window.

    Loguru applies `retention=` only to sinks it owns; this one is a callable
    sink, so it prunes its own files. Called on handle open, i.e. once per
    process and again on each midnight rollover.
    """
    cutoff = today - timedelta(days=STRUCTURED_LOG_RETENTION_DAYS)
    for path in log_dir.glob("structured-*.json"):
        try:
            file_date = date.fromisoformat(path.stem.removeprefix("structured-"))
        except ValueError:
            continue  # not one of ours — a foreign file matching the glob
        if file_date >= cutoff:
            continue
        try:
            path.unlink()
        except OSError as exc:
            # Inside loguru's own sink — cannot log via loguru, so surface on stderr.
            sys.stderr.write(f"[gaia-logging] failed to prune old log {path}: {exc}\n")


def _json_file_sink_factory(log_dir: Path) -> Callable[[Message], None]:
    """Create a callable sink that writes flat NDJSON to daily rotating files.

    Produces the same flat JSON format as _json_stdout_sink so that Promtail
    and Grafana dashboards work identically for local dev and Docker.
    """
    _handles: dict[str, TextIO] = {}

    def _sink(message: Message) -> None:
        record = message.record
        date_str = record["time"].strftime("%Y-%m-%d")
        resolved = log_dir / f"structured-{date_str}.json"
        key = str(resolved)

        fh = _handles.get(key)
        if fh is None or fh.closed:
            # Close stale handles from previous days before opening a new one
            for old_key in list(_handles):
                if old_key != key:
                    old_fh = _handles.pop(old_key)
                    try:
                        old_fh.close()
                    except OSError as exc:
                        # We are inside loguru's own sink, so we cannot log via
                        # loguru here. Surface the failure on stderr instead of
                        # dropping it — a leaked handle is worth knowing about.
                        sys.stderr.write(
                            f"[gaia-logging] failed to close stale log handle {old_key}: {exc}\n"
                        )
            _prune_structured_logs(log_dir, record["time"].date())
            fh = open(resolved, "a", encoding="utf-8")  # noqa: SIM115
            _handles[key] = fh

        fh.write(_build_json_entry(record))
        fh.flush()

    return _sink


def _worker_name_patcher(record: Record) -> None:
    """Derive a short worker label from the OS process name.

    uvicorn --workers spawns processes named SpawnProcess-1, SpawnProcess-2, etc.
    This collapses them to w1, w2 so log lines are easy to diff between workers.
    Single-process / dev mode shows 'main'.
    """
    name: str = record["process"].name
    if name.startswith("SpawnProcess-"):
        record["extra"]["worker"] = "w" + name.rsplit("-", maxsplit=1)[-1]
    elif name == "MainProcess":
        record["extra"]["worker"] = "main"
    else:
        record["extra"]["worker"] = name[:5]


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

    # Set global defaults for extra fields used in format strings so they
    # never raise KeyError on records that bypass InterceptHandler or bind().
    logger.configure(
        extra={"logger_name": "APP", "worker": "main"},
        patcher=_worker_name_patcher,
    )

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
                record.name.startswith(namespace) or record.name == namespace.rstrip(".")
                for namespace in app_namespaces
            )

            if not should_intercept:
                return

            level: str | int
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

            logger.bind(logger_name=context_name).opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

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

    Creates separate files for general, error, structured JSON, and critical
    logs — all with automatic rotation and compression.

    No-ops under ``LOG_FORMAT=json`` (the container setting): there, stdout NDJSON
    is captured by the Docker daemon and shipped to Loki via Promtail, so file
    sinks would only fill an ephemeral filesystem. Owning that rule here — rather
    than at each call site — keeps it a single decision every app inherits.

    Safe to call multiple times — only configures once.

    Args:
        log_dir: Directory to write log files into (default: ./logs)
    """
    if LOG_CONFIG["format_mode"] == "json":
        return
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
