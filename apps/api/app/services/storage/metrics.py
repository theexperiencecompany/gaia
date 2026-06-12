"""Filesystem operation metrics — per-request latency aggregation.

Why this exists
---------------
Every chat turn fans out into a handful of FS-shaped operations: a new
conversation creates session dirs (`ensure_session_dirs`), every coding tool
call resolves into a sandbox `commands.run` round-trip, the artifact watcher
does a `list_artifacts`, and so on. Each one is cheap on its own; together they
quietly dominate end-to-end latency once the cache misses or the meta DB
takes a coffee break.

We need to see *where the milliseconds go* without N+1 emission of one log
line per FS call. So this module accumulates per-op stats into a ContextVar
for the lifetime of a request / `wide_task`, then ships a single structured
``fs={...}`` field on the canonical wide event at the end. LogQL can split
on op name, count, total_ms, max_ms across users / hosts / time.

Wire contract
-------------
The wide event field is::

    fs: {
        "<op>": {
            "count":    <int>,
            "total_ms": <float>,
            "max_ms":   <float>,
            "errors":   <int>,
            "bytes":    <int>,           # only when the op reports bytes
            "last_error_type": <str>,    # only when at least one error fired
        }
    }

Op names are stable, lowercased, snake_cased identifiers — keep them stable
because dashboards will pivot on them. The list lives in ``FsOps`` below as
the source of truth; adding a new op = add a constant here first.

Prometheus export
-----------------
Every call to ``record_fs_op`` (and ``add_fs_bytes`` for byte volume) emits to
the following Prometheus collectors, all registered on the default registry:

- ``fs_op_duration_seconds`` (Histogram, labels ``operation, mode, status``).
  Standard latency view. ``mode`` carries the acquire-path label for
  ``sbx_acquire`` and defaults to ``"none"`` elsewhere.
- ``fs_op_bytes_total`` (Counter, label ``operation``). Only incremented when
  an op reports a non-zero byte count.
- ``fs_op_total`` (Counter, labels ``operation, mode, status``). Lifetime
  count — never decays. Backs lifetime-totals dashboard panels.
- ``fs_op_last_seen_unix_seconds`` (Gauge, label ``operation``). Wall-clock
  timestamp of the most recent observation. Drives "last seen N minutes ago"
  columns.
- ``fs_op_in_flight`` (Gauge, label ``operation``). Maintained by ``fs_timer``:
  inc on enter, dec in finally. Exposes contention + stuck operations.
- ``sandbox_pool_size`` (Gauge, labels ``kind, shard``). Set by the sandbox
  pool on add/remove via :func:`set_sandbox_pool_size`. ``kind`` is
  ``"user"`` or ``"warm"``.

Bash exit-code distribution lives in ``apps/api/app/agents/tools/coding/
bash_tool.py`` as ``tool_bash_exit_code_total`` (Counter, label ``exit_code``
bucketed into ``0``, ``1-126``, ``127``, ``128-254``, ``255``, ``timeout``).

Label discipline: the labels above are the *complete* allowed set. Adding a
label requires updating the matching OpenSpec capability (``fs-metrics-
prometheus`` for the original two, ``fs-metrics-coverage`` for the rest)
because dashboards pivot on these names.

The API process exposes everything via ``/metrics`` mounted by
``prometheus-fastapi-instrumentator``. The ARQ worker re-registers the same
collector instances on its custom registry inside
``apps/api/app/workers/metrics.py`` so the worker's ``/metrics`` endpoint
mirrors the API.

Grafana panels live in
``infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json``.

Usage
-----

    from app.services.storage.metrics import fs_timer, FsOps

    async with fs_timer(FsOps.LIST_ARTIFACTS, conv_id=conv):
        return await _go()

    # or, when the caller already has a duration:
    record_fs_op(FsOps.WRITE_SESSION_FILE, duration_ms=4.2, bytes=size)

At the end of a `wide_task`, call::

    log.set(fs=flush_fs_metrics())

to attach the aggregate to the wide event. The aggregate ContextVar is
isolated per task (same mechanism as ``shared.py.wide_events``), so there is
no cross-request leakage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import contextlib
import contextvars
from dataclasses import dataclass, field
import time
from typing import Any, Final

from prometheus_client import (  # noqa: F401  # Gauge used via lambda factories below
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
)

from shared.py.logging import get_contextual_logger

_log = get_contextual_logger("app.services.storage.metrics")


# Prometheus collectors. Allowed labels (CHANGES REQUIRE A SPEC UPDATE on
# either the `fs-metrics-prometheus` or `fs-metrics-coverage` capability):
#   - fs_op_duration_seconds:        operation, mode, status
#   - fs_op_bytes_total:              operation
#   - fs_op_total:                    operation, mode, status
#   - fs_op_last_seen_unix_seconds:   operation
#   - fs_op_in_flight:                operation
#   - sandbox_pool_size:              kind, shard
# High-cardinality identifiers (user_id, conv_id, paths) MUST stay on the wide
# event, never on these collectors. The default registry is what the existing
# /metrics endpoint serves; the worker process re-registers these same instances
# on its custom registry inside app/workers/metrics.py.

_FS_OP_BUCKETS: Final[tuple[float, ...]] = (
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)


def _register_once(name: str, factory: Callable[[], Any]) -> Any:
    """Register a Prometheus collector at module load, tolerating re-imports.

    `uvicorn --reload` and some test fixtures import this module twice in the
    same process. The second registration raises ``ValueError("Duplicated
    timeseries...")``. We catch that and return the previously-registered
    collector, so the same instance is used across imports.
    """
    try:
        return factory()
    except ValueError:
        existing = REGISTRY._names_to_collectors.get(name)  # noqa: SLF001
        if existing is None:
            raise
        return existing


_FS_OP_DURATION_SECONDS = _register_once(
    "fs_op_duration_seconds",
    lambda: Histogram(
        name="fs_op_duration_seconds",
        documentation="FsOps measurement duration in seconds",
        labelnames=("operation", "mode", "status"),
        buckets=_FS_OP_BUCKETS,
    ),
)

_FS_OP_BYTES_TOTAL = _register_once(
    "fs_op_bytes_total",
    lambda: Counter(
        name="fs_op_bytes_total",
        documentation="FsOps measurement byte volume",
        labelnames=("operation",),
    ),
)

_FS_OP_TOTAL = _register_once(
    "fs_op_total",
    lambda: Counter(
        name="fs_op_total",
        documentation="FsOps lifetime total observations",
        labelnames=("operation", "mode", "status"),
    ),
)

_FS_OP_LAST_SEEN = _register_once(
    "fs_op_last_seen_unix_seconds",
    lambda: Gauge(
        name="fs_op_last_seen_unix_seconds",
        documentation="Wall-clock time of the most recent FsOps observation per op",
        labelnames=("operation",),
    ),
)

_FS_OP_IN_FLIGHT = _register_once(
    "fs_op_in_flight",
    lambda: Gauge(
        name="fs_op_in_flight",
        documentation="FsOps operations currently executing per op",
        labelnames=("operation",),
    ),
)

_SANDBOX_POOL_SIZE = _register_once(
    "sandbox_pool_size",
    lambda: Gauge(
        name="sandbox_pool_size",
        documentation="Sandbox pool occupancy by kind and shard",
        labelnames=("kind", "shard"),
    ),
)


def set_sandbox_pool_size(kind: str, shard: str, n: int) -> None:
    """Publish the current pool size for ``(kind, shard)``.

    ``kind`` is ``"user"`` (per-user pooled sandboxes) or ``"warm"`` (warm
    pre-created sandboxes). ``shard`` is the stringified shard id. The
    underlying ``sandbox_pool_size`` gauge supports ``set`` semantics —
    last-writer-wins per (kind, shard), which matches the desired "current
    count" view.

    Wrap in try/except so a registry bug never breaks the pool mutation that
    called us.
    """
    try:
        _SANDBOX_POOL_SIZE.labels(kind=kind, shard=shard).set(n)
    except Exception as e:  # noqa: BLE001
        _log.warning(
            "[metrics] sandbox_pool_size set failed",
            kind=kind,
            shard=shard,
            error_type=type(e).__name__,
        )


@dataclass(slots=True)
class _OpStats:
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    errors: int = 0
    bytes: int = 0
    last_error_type: str | None = None
    labels: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "count": self.count,
            "total_ms": round(self.total_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "errors": self.errors,
        }
        if self.bytes:
            out["bytes"] = self.bytes
        if self.last_error_type is not None:
            out["last_error_type"] = self.last_error_type
        if self.labels:
            out["labels"] = self.labels
        return out


class FsOps:
    """Stable identifiers for every FS-shaped operation we instrument.

    Keep names <= 32 chars and snake_case. Adding a new metric: add the
    constant here, then reference it from the call site. Removing one is a
    breaking dashboard change — coordinate before deleting.
    """

    # Host-side JuiceFS mount management.
    JUICEFS_MOUNT: Final[str] = "juicefs_mount"
    JUICEFS_FORMAT: Final[str] = "juicefs_format"
    JUICEFS_STATUS: Final[str] = "juicefs_status"

    # Per-session host writes.
    ENSURE_SESSION_DIRS: Final[str] = "ensure_session_dirs"
    MATERIALIZE_INTEGRATIONS: Final[str] = "materialize_integrations"
    SYNC_GAIA_TASKS_VFS: Final[str] = "sync_gaia_tasks_vfs"
    SYNC_USER_TODOS_VFS: Final[str] = "sync_user_todos_vfs"
    TOUCH_LAST_ACTIVE: Final[str] = "touch_last_active"

    # Read paths driving the HTTP `GET /sessions` endpoints + watcher fallback.
    LIST_ARTIFACTS: Final[str] = "list_artifacts"
    LIST_USER_UPLOADED: Final[str] = "list_user_uploaded"
    STAT_ARTIFACT: Final[str] = "stat_artifact"
    RESOLVE_SESSION_PATH: Final[str] = "resolve_session_path"
    LIST_SESSION_IDS: Final[str] = "list_session_ids"
    LIST_STALE_SESSIONS: Final[str] = "list_stale_sessions"

    # Single-file writes (upload pipeline + skill installer).
    WRITE_SESSION_FILE: Final[str] = "write_session_file"
    WRITE_SKILL_FILE: Final[str] = "write_skill_file"
    PIN_ARTIFACT: Final[str] = "pin_artifact"
    DELETE_SESSION_DIR: Final[str] = "delete_session_dir"

    # Sandbox lifecycle (E2B control plane + mount script).
    SBX_ACQUIRE: Final[str] = "sbx_acquire"
    SBX_CREATE: Final[str] = "sbx_create"
    SBX_CONNECT_RESUME: Final[str] = "sbx_connect_resume"
    SBX_HEALTH_PROBE: Final[str] = "sbx_health_probe"
    SBX_MOUNT_SCRIPT: Final[str] = "sbx_mount_script"
    SBX_ENSURE_MOUNTED: Final[str] = "sbx_ensure_mounted"
    SBX_CANARY_VERIFY: Final[str] = "sbx_canary_verify"

    # Tool entry points (one timing per agent tool invocation).
    TOOL_BASH: Final[str] = "tool_bash"
    TOOL_READ: Final[str] = "tool_read"
    TOOL_WRITE: Final[str] = "tool_write"
    TOOL_EDIT: Final[str] = "tool_edit"

    # Tool-internal sub-steps worth separating (writes are dominated by the
    # base64 round-trip; artifact publishing fans out N find/stat ops).
    TOOL_BASH_PUBLISH: Final[str] = "tool_bash_publish_artifacts"
    SBX_COMMANDS_RUN: Final[str] = "sbx_commands_run"

    # Upload pipeline FS write (separates Cloudinary from the JuiceFS leg).
    UPLOAD_PERSIST_SANDBOX: Final[str] = "upload_persist_sandbox"

    # Artifact watcher rescan loop (accesslog mode).
    WATCHER_RESCAN: Final[str] = "watcher_rescan"


_metrics_var: contextvars.ContextVar[dict[str, _OpStats] | None] = contextvars.ContextVar(
    "fs_metrics", default=None
)


def _bucket() -> dict[str, _OpStats]:
    """Return the per-task metrics bucket, creating it on first use."""
    bucket = _metrics_var.get()
    if bucket is None:
        bucket = {}
        _metrics_var.set(bucket)
    return bucket


def record_fs_op(
    op: str,
    *,
    duration_ms: float,
    error: BaseException | None = None,
    bytes: int = 0,
    **labels: Any,
) -> None:
    """Record one completed FS op.

    ``error`` if non-None bumps the error counter and stamps the type. Labels
    are merged into the op's ``labels`` dict on a last-write-wins basis — use
    them for very low-cardinality identifiers (role, mount status). High-
    cardinality values (conv_id, path) belong in the wide event, not here.

    Additionally emits to the Prometheus collectors declared at module scope.
    Prometheus emit is wrapped in ``try/except`` so a registry bug never breaks
    the wide event flush — the ContextVar bucket update above is the canonical
    record, the Prometheus emit is a parallel surface.
    """
    stats = _bucket().setdefault(op, _OpStats())
    stats.count += 1
    stats.total_ms += duration_ms
    stats.max_ms = max(stats.max_ms, duration_ms)
    if bytes:
        stats.bytes += bytes
    if error is not None:
        stats.errors += 1
        stats.last_error_type = type(error).__name__
    if labels:
        stats.labels.update(labels)

    try:
        mode = labels.get("mode") or "none"
        status = "error" if error is not None else "ok"
        _FS_OP_DURATION_SECONDS.labels(operation=op, mode=mode, status=status).observe(
            duration_ms / 1000.0
        )
        _FS_OP_TOTAL.labels(operation=op, mode=mode, status=status).inc()
        _FS_OP_LAST_SEEN.labels(operation=op).set(time.time())
        if bytes > 0:
            _FS_OP_BYTES_TOTAL.labels(operation=op).inc(bytes)
    except Exception as e:  # noqa: BLE001 — dashboard surface must not break callers
        _log.warning(
            "[metrics] prometheus observe failed",
            op=op,
            error_type=type(e).__name__,
        )


def add_fs_bytes(op: str, n: int) -> None:
    """Add bytes to an op's running total without bumping count/duration.

    Useful when the byte size is only known after a timed operation completes
    (e.g. a write where the payload is computed inside the timer body).
    Records nothing if ``n`` is zero or negative.
    """
    if n <= 0:
        return
    stats = _bucket().setdefault(op, _OpStats())
    stats.bytes += n

    try:
        _FS_OP_BYTES_TOTAL.labels(operation=op).inc(n)
    except Exception as e:  # noqa: BLE001
        _log.warning(
            "[metrics] prometheus bytes inc failed",
            op=op,
            error_type=type(e).__name__,
        )


@contextlib.asynccontextmanager
async def fs_timer(op: str, **labels: Any) -> AsyncIterator[None]:
    """Async context manager that records the wall-clock duration of ``op``.

    On exception, the op is still recorded (with ``error=<exception>``) so we
    can see the latency cost of a failure path in the same dashboard. The
    exception is then re-raised; never swallow.

    Also maintains the ``fs_op_in_flight`` Prometheus gauge: incremented on
    entry, decremented in ``finally``. The increment is wrapped in
    try/except so a registry bug never breaks the yield; the decrement is
    similarly guarded so a paired-state inconsistency never blocks
    ``record_fs_op`` from running.
    """
    start = time.monotonic()
    err: BaseException | None = None
    try:
        _FS_OP_IN_FLIGHT.labels(operation=op).inc()
    except Exception as e:  # noqa: BLE001
        _log.warning(
            "[metrics] in_flight inc failed",
            op=op,
            error_type=type(e).__name__,
        )
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — surfaced via re-raise
        err = exc
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        try:
            _FS_OP_IN_FLIGHT.labels(operation=op).dec()
        except Exception as e:  # noqa: BLE001
            _log.warning(
                "[metrics] in_flight dec failed",
                op=op,
                error_type=type(e).__name__,
            )
        record_fs_op(op, duration_ms=elapsed_ms, error=err, **labels)


def flush_fs_metrics() -> dict[str, dict[str, Any]]:
    """Return the accumulated metrics as a serializable dict, and clear the bucket.

    Call from inside a ``wide_task`` / request middleware just before emitting
    the canonical log line::

        log.set(fs=flush_fs_metrics())

    Returns ``{}`` if nothing was recorded — safe to attach unconditionally.
    """
    bucket = _metrics_var.get()
    if not bucket:
        return {}
    snapshot = {op: stats.to_dict() for op, stats in bucket.items()}
    # Reset the bucket so a long-lived event loop (workers) doesn't leak
    # state across tasks; the wide_task entry will also reset via ContextVar
    # isolation, but explicit clear keeps the contract obvious.
    _metrics_var.set(None)
    return snapshot


def peek_fs_metrics() -> dict[str, dict[str, Any]]:
    """Read the bucket without clearing it — for in-flight debugging only."""
    bucket = _metrics_var.get()
    if not bucket:
        return {}
    return {op: stats.to_dict() for op, stats in bucket.items()}


__all__ = [
    "FsOps",
    "add_fs_bytes",
    "flush_fs_metrics",
    "fs_timer",
    "peek_fs_metrics",
    "record_fs_op",
    "set_sandbox_pool_size",
]
