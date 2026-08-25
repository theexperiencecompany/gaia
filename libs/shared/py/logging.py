"""
Advanced logging configuration for GAIA applications.

╔══════════════════════════════════════════════════════════════════════════╗
║ CROSS-RUNTIME CONTRACT — MIRROR EVERY SHAPE CHANGE IN TYPESCRIPT         ║
║                                                                          ║
║ This file is ONE HALF of GAIA's log envelope. The other half is          ║
║   libs/shared/ts/src/bots/utils/logger.ts  (function `buildRecord`)      ║
║ and it MUST emit the same key names, the same value types and the same   ║
║ timestamp format, because one LogQL query (`| json | ...`) has to span   ║
║ the Python services and the TypeScript bots at once. A field that        ║
║ exists here and not there — or exists on both with a different type —    ║
║ silently breaks every dashboard that joins the two surfaces.             ║
║                                                                          ║
║ If you are an agent editing ONLY this file, before you finish:           ║
║  1. Open libs/shared/ts/src/bots/utils/logger.ts and make the matching   ║
║     change in `buildRecord` / `RESERVED_LOG_KEYS` / `COLLIDING_KEY_      ║
║     PREFIX` / `sanitizeErrorForLog`.                                     ║
║  2. Update the shared contract that both sides are checked against:      ║
║     scripts/ci/wide-event-conformance/contract.json                      ║
║  3. Run the conformance check — it emits real lines from BOTH runtimes   ║
║     and diffs their shapes:                                              ║
║       python3 scripts/ci/wide-event-conformance/run.py                   ║
║     It fails if the two runtimes disagree, so skipping step 1 or 2 is    ║
║     a red CI lane, not a silent drift.                                   ║
║                                                                          ║
║ Envelope keys stamped on EVERY line by both runtimes:                    ║
║   time, level, env, service, commit, logger, message                     ║
║ Python-only provenance (loguru record data with no TS equivalent, and    ║
║ declared as such in the contract): module, line, worker                  ║
║ TS-only envelope: platform, component (Python carries them as ordinary   ║
║ optional wide-event fields with the same names and types)                ║
╚══════════════════════════════════════════════════════════════════════════╝

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
- LOG_LEVEL: Minimum log level for GAIA's own namespaces (default: INFO)
- LOG_LEVEL_THIRD_PARTY: Minimum level for every other library (default: WARNING)
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
from datetime import UTC, date, datetime, timedelta
import functools
import json as _json
import logging
from math import isfinite
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, TextIO, TypedDict

from loguru import logger

if TYPE_CHECKING:
    from loguru import Logger, Message, Record


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

# Promtail labels every line with the service it came from (see
# infra/docker/observability/promtail-config.yaml). The in-line `service` field
# MUST match that label, so `{service="X"}` and `| json | service="X"` agree —
# a query that mixes the two must not silently return nothing.
#
# Three Python services share this module, so the name cannot be a constant:
# GAIA_SERVICE_NAME is set per service (compose/Dockerfile/mise task) and must
# equal the Promtail label for that service. The API keeps the historical
# default so an unset var is still correct for the most common process.
_DEFAULT_SERVICE_NAME = "gaia-backend"
# Deployment environment. `ENV` is GAIA's own variable (apps/api/Dockerfile sets
# it); `NODE_ENV` is the Node-ecosystem spelling the bots' image sets. Both
# runtimes resolve `env` from ENV → NODE_ENV → "development", so one value
# vocabulary spans every surface and an unset var reads as "not a configured
# deployment" rather than mislabelling a laptop as production.
_DEFAULT_ENV = "development"

# Top-level keys every JSON line is built from. Extra fields must never
# overwrite them — a colliding key is re-emitted under _COLLIDING_KEY_PREFIX.
# env/service/commit are core precisely because they are the line's infra
# identity: app code that sets `service` must not be able to contradict the
# Promtail label for its own process.
_CORE_KEYS = frozenset(
    {
        "time",
        "level",
        "env",
        "service",
        "commit",
        "logger",
        "message",
        "module",
        "line",
        "worker",
    }
)
_COLLIDING_KEY_PREFIX = "ctx_"
# Extra keys consumed into the core entry (never re-emitted as extra fields).
_CONSUMED_EXTRA_KEYS = frozenset({"logger_name", "worker"})
# A structure that contains itself cannot be serialized; this marker keeps the
# rest of the line intact instead of the sanitize fallback dropping it.
_CIRCULAR_MARKER = "<circular reference>"
# Loki rejects lines over its max_line_size (256KB by default) — cap below it.
MAX_JSON_LINE_BYTES = 200_000
# Matches Loki's retention_period (infra/docker/observability/loki-config.yaml)
# and the gaia-*.log sink, so local structured files age out at the same rate.
STRUCTURED_LOG_RETENTION_DAYS = 30
_TRUNCATED_MESSAGE_MAX_CHARS = 10_000


@functools.lru_cache(maxsize=1)
def env_context() -> dict[str, str]:
    """Infra identity stamped on every emitted JSON line.

    The Python half of the envelope's `env`/`service`/`commit` — mirrored by
    `buildRecord` in libs/shared/ts/src/bots/utils/logger.ts, which resolves the
    same three fields from the same variables. Resolved once and cached.

    `commit` reads GIT_COMMIT_SHA (or COMMIT_SHA), set in the Docker image / CI,
    and falls back to "local" during development. `service` reads
    GAIA_SERVICE_NAME, which each service sets to its own Promtail label.
    """
    return {
        # `or`-chained so a set-but-empty var still falls through to the default.
        "env": os.getenv("ENV") or os.getenv("NODE_ENV") or _DEFAULT_ENV,
        "service": os.getenv("GAIA_SERVICE_NAME") or _DEFAULT_SERVICE_NAME,
        "commit": (os.getenv("GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA") or "local")[:8],
    }


LOG_CONFIG: _LogConfig = {
    "level": os.getenv("LOG_LEVEL", "INFO"),
    # Set LOG_FORMAT=json in production Docker to emit newline-delimited JSON to
    # stdout. Promtail picks this up and ships it to Loki with zero parsing issues.
    # Default is "console" which keeps the colourised format for local development.
    # Defaults to NDJSON in production so a service that forgets to set
    # LOG_FORMAT still ships parseable logs. It was previously "console"
    # everywhere, which meant the eight compose services that set it were the
    # only ones Promtail could parse — a ninth would have degraded silently to
    # colourised text with ANSI escapes, and nothing would have failed.
    "format_mode": os.getenv("LOG_FORMAT")
    or ("json" if env_context()["env"] == "production" else "console"),
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


# Third-party libraries log at INFO/DEBUG far more freely than we do, and every
# stdlib record now reaches our sink (see configure_loguru). WARNING keeps the
# stream to what an operator would act on; raise or lower this — independently
# of LOG_LEVEL, which governs GAIA's own namespaces — to debug a library.
THIRD_PARTY_LOG_LEVEL = os.getenv("LOG_LEVEL_THIRD_PARTY", "WARNING")

# Namespaces GAIA owns: they log at LOG_LEVEL, not the third-party floor above.
# uvicorn/gunicorn/livekit are framework loggers we treat as ours because their
# records are about our process, not about a library's internals.
_OWNED_LOG_NAMESPACES = ("app", "gaia_shared", "uvicorn", "fastapi", "gunicorn", "livekit")

# Short display names for the busiest loggers. Anything unmapped falls back to
# its top-level package (`aiormq.connection` → `AIORMQ`).
_LOGGER_DISPLAY_NAMES = {
    "uvicorn": "UVICORN",
    "uvicorn.error": "UVICORN",
    "uvicorn.access": "UVICORN",
    "fastapi": "FASTAPI",
    "gunicorn": "GUNICOR",
    "livekit": "LIVEKIT",
    "py.warnings": "WARNING",
}

if LOG_CONFIG["format_mode"] == "json":
    # Under LOG_FORMAT=json, stdout is a data stream — one JSON object per line,
    # parsed by Promtail. A tqdm progress bar writes straight to that descriptor
    # and ends its frames with \r instead of \n, so the next event is appended to
    # the bar's last frame and the line stops being JSON: the event is not ugly,
    # it is gone from every structured query. No logging configuration can fix a
    # direct fd write, so the bars have to be off.
    #
    # Both switches are read by their libraries at import time (huggingface_hub
    # binds HF_HUB_DISABLE_PROGRESS_BARS in its constants module, tqdm reads
    # TQDM_* through its envwrap decorator), so they are set here — the earliest
    # import in every GAIA process — rather than at a call site. setdefault keeps
    # an operator's explicit value.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TQDM_DISABLE", "1")


# Emission order of the core entry. Same order as ENVELOPE_KEYS in
# libs/shared/ts/src/bots/utils/logger.ts, minus the loguru-only provenance
# (module/line/worker) that has no TypeScript equivalent.
_CORE_KEY_ORDER = (
    "time",
    "level",
    "env",
    "service",
    "commit",
    "logger",
    "message",
    "module",
    "line",
    "worker",
)


def _core_fields(entry: dict[str, object]) -> dict[str, object]:
    return {key: entry[key] for key in _CORE_KEY_ORDER}


def _iso_utc_millis(moment: datetime) -> str:
    """Serialize a timestamp exactly as `new Date().toISOString()` does in TS.

    Loguru records carry the *local* timezone, so the same instant serialized on
    a laptop in UTC+05:30 and in a UTC container produced two different strings
    — enough to break any query that compares or groups on the raw `time` value
    across surfaces. Normalizing to UTC with millisecond precision and a `Z`
    suffix makes both runtimes emit byte-identical timestamps for one instant.
    """
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _finite(value: object) -> object:
    """Recursively replace non-finite floats with ``None`` and cycles with a marker.

    Only called after a non-finite value has already been detected, so the
    common path never pays for this walk. A structure that contains itself
    (directly or transitively) would recurse forever here and is rejected by
    ``json.dumps`` anyway — replacing it with a constant marker keeps the rest
    of the line intact instead of forcing the sanitize fallback to drop it.
    """
    ancestors: set[int] = set()

    def _walk(node: object) -> object:
        if isinstance(node, float):
            # bool is not a float, and int cannot be non-finite, so this is total.
            return node if isfinite(node) else None
        if isinstance(node, dict):
            if id(node) in ancestors:
                return _CIRCULAR_MARKER
            ancestors.add(id(node))
            try:
                return {key: _walk(item) for key, item in node.items()}
            finally:
                ancestors.remove(id(node))
        if isinstance(node, (list, tuple)):
            if id(node) in ancestors:
                return _CIRCULAR_MARKER
            ancestors.add(id(node))
            try:
                return [_walk(item) for item in node]
            finally:
                ancestors.remove(id(node))
        return node

    return _walk(value)


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

    ``default=str`` cannot save non-str dict keys — rather than dropping the
    whole line, preserve the core fields (all plain str/int, always
    serializable) plus trace_id, and record what went wrong. (Cyclic values
    are handled in ``_finite`` by degrading to a marker, so they do not reach
    this fallback.)
    """
    sanitized = _core_fields(entry)
    if "trace_id" in entry:
        sanitized["trace_id"] = str(entry["trace_id"])
    sanitized["serialization_error"] = type(exc).__name__
    return sanitized


def _truncated_entry(entry: dict[str, object], original_size_bytes: int) -> dict[str, object]:
    """Rebuild an oversized entry under the byte cap, dropping only what does not fit.

    Truncation must cost payload, never identity. Collapsing to the core fields
    alone kept ``message`` — so the line still reads as a canonical boundary
    event — while discarding ``service``, ``env``, ``task``, ``outcome`` and
    ``duration_ms``, the fields that make it one. A single fat job argument was
    then enough to erase a task's outcome from the record while the event itself
    still appeared in Loki.

    Fields are spent smallest-first, so what gets shed is whatever is actually
    fat. Identity is small — ``service``, ``env``, ``task``, ``outcome``,
    ``trace_id`` are a few dozen bytes between them — so it survives any line an
    oversized payload can produce, without this sink having to know the
    wide-event vocabulary. The names that did not fit are listed in
    ``dropped_fields``, so a dropped field reads as shed-for-size rather than as
    a field the code never set.
    """
    truncated = _core_fields(entry)
    truncated["message"] = str(entry["message"])[:_TRUNCATED_MESSAGE_MAX_CHARS]
    truncated["line_truncated"] = True
    truncated["original_size_bytes"] = original_size_bytes
    dropped: list[str] = []
    truncated["dropped_fields"] = dropped

    candidates = {key: value for key, value in entry.items() if key not in truncated}
    sizes = {key: len(_dumps({key: value}).encode("utf-8")) for key, value in candidates.items()}
    # Reserve room for every candidate's name up front. Worst case is that all
    # of them end up in dropped_fields, so reserving unconditionally makes the
    # cap hold no matter how the split lands.
    names = sum(len(_dumps(key).encode("utf-8")) + 2 for key in candidates)
    budget = MAX_JSON_LINE_BYTES - len(_dumps(truncated).encode("utf-8")) - names

    kept: set[str] = set()
    for key in sorted(candidates, key=lambda k: sizes[k]):
        if sizes[key] > budget:
            break  # ascending order: nothing after this fits either
        kept.add(key)
        budget -= sizes[key]

    for key, value in candidates.items():  # emit in the order app code set them
        if key in kept:
            truncated[key] = value
        else:
            dropped.append(key)
    return truncated


def _build_json_entry(record: Record) -> str:
    """Serialize a loguru record to a flat NDJSON line — total, never raises.

    Produces one JSON object per line. Fields from `.bind()` calls are merged
    into the top-level object so that LogQL `| json` can filter on them directly.
    The envelope — time/level/env/service/commit/logger/message — is stamped
    HERE, on every line, exactly as `buildRecord` does for the TypeScript bots,
    so `| json | env="production"` selects the same lines on both surfaces. It
    is also the single place the infra identity is resolved: no caller adds
    `env_context()` to its own payload.

    Three guarantees keep the sink total:

    - Core keys always win: an extra field colliding with a core key (e.g.
      `log.set(level=...)` or a service-layer `log.set(service=...)`) is emitted
      as `ctx_<key>` instead of corrupting the line's real level/message or
      contradicting the Promtail label for this process.
    - Serialization never drops a record: unserializable extras (non-str dict
      keys, circular refs) fall back to a sanitized entry carrying the core
      fields, trace_id and `serialization_error`.
    - Lines are capped at MAX_JSON_LINE_BYTES: an oversized line sheds its
      largest fields (named in `dropped_fields`, flagged with `line_truncated` +
      `original_size_bytes`) and keeps the rest, so Loki (default max_line_size
      256KB) never rejects it and the event stays attributable.

    NOTE: must NOT be used as loguru's `format=` parameter — loguru treats
    callable formats as template generators and calls str.format_map() on the
    returned string, which breaks on JSON's curly braces. Use as a callable
    sink instead (see _json_stdout_sink).

    Example output:
        {"time": "2024-01-01T12:00:00.123Z", "level": "INFO", "env": "production",
         "service": "gaia-backend", "commit": "abc1234", "logger": "REQUEST",
         "message": "http_request", "method": "GET", "path": "/api/v1/chat",
         "status_code": 200, "duration_ms": 234.56, "client_ip": "1.2.3.4"}
    """
    extra = record["extra"]
    identity = env_context()
    entry: dict[str, object] = {
        "time": _iso_utc_millis(record["time"]),
        "level": record["level"].name,
        "env": identity["env"],
        "service": identity["service"],
        "commit": identity["commit"],
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
        # UTC, so the file a line lands in always agrees with the UTC `time` the
        # line carries — the same rule appendStructuredLogLine follows in
        # libs/shared/ts/src/bots/utils/log-file-sink.ts (`isoTime.slice(0, 10)`).
        utc_day = record["time"].astimezone(UTC).date()
        resolved = log_dir / f"structured-{utc_day.isoformat()}.json"
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
            _prune_structured_logs(log_dir, utc_day)
            # Handle is cached in _handles and outlives this call by design.
            fh = resolved.open("a", encoding="utf-8")
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


class _InterceptHandler(logging.Handler):
    """Re-emit a stdlib logging record through loguru.

    Installed on the ROOT logger, so it is the single exit for every library
    that uses ``logging`` — there is no namespace it can be registered under
    that escapes the sink.
    """

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        if record.name.startswith("app."):
            display_name = record.name.split(".")[-1].upper()[:7]
        else:
            display_name = _LOGGER_DISPLAY_NAMES.get(
                record.name, record.name.split(".")[0].upper()[:7]
            )

        logger.bind(logger_name=display_name).opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _route_through_root(logger_name: str, level: str) -> None:
    """Drop a logger's own handlers so its records reach the root interceptor.

    uvicorn ships its own stdout/stderr StreamHandlers and sets
    ``propagate = False``; leaving them attached under LOG_FORMAT=json would put
    colourised text on the descriptor that is supposed to be pure NDJSON.
    """
    stdlib_logger = logging.getLogger(logger_name)
    stdlib_logger.handlers.clear()
    stdlib_logger.propagate = True
    stdlib_logger.setLevel(level)


def configure_loguru() -> Logger:
    """
    Configure console logging with standard library interception.

    Every ``logging`` record in the process — GAIA's, the framework's, and any
    library's — is routed through loguru, so the configured sink is the only
    writer on the descriptor. GAIA's namespaces log at LOG_LEVEL; everything
    else at THIRD_PARTY_LOG_LEVEL.

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

    # Route the ENTIRE stdlib logging tree into loguru. force=True closes and
    # removes whatever handlers a library already put on the root logger —
    # composio calls logging.basicConfig() on import, which is how 86 aiormq
    # broker failures escaped as unstructured "[<date>][ERROR] ..." text — and
    # captureWarnings redirects warnings.warn, which otherwise prints its own
    # two-line "file:line: Category" block straight to stderr.
    #
    # This replaces a namespace allowlist inside the handler. That allowlist was
    # the only thing keeping third-party volume down, since it was the sole
    # filter on what became a log line; the floor is now a level
    # (THIRD_PARTY_LOG_LEVEL) instead of a list of names, so a library can be
    # quiet without being invisible. Nothing is denied by name: every logger
    # that was on the list is reachable from root, and no library can bypass the
    # sink by picking a name we did not think of.
    logging.captureWarnings(True)
    logging.basicConfig(handlers=[_InterceptHandler()], level=THIRD_PARTY_LOG_LEVEL, force=True)

    for logger_name in _OWNED_LOG_NAMESPACES:
        _route_through_root(logger_name, LOG_CONFIG["level"])

    # uvicorn decides whether an access log exists at all, and re-checks that
    # decision per connection with `uvicorn.access`.hasHandlers(): --no-access-log
    # clears the handlers and stops propagation. Unconditionally re-attaching a
    # handler here — as this did — silently switched the flag back on, emitting a
    # second, trace-less line per request that duplicates the canonical
    # http_request event and carries the raw query string the wide event drops.
    # Only take the logger over when uvicorn left it enabled.
    if logging.getLogger("uvicorn.access").hasHandlers():
        _route_through_root("uvicorn.access", LOG_CONFIG["level"])

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


def get_contextual_logger(name: str, **context: object) -> Logger:
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
    "env_context",
    "get_contextual_logger",
]
