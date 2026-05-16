"""Filesystem operation metrics — per-request latency aggregation.

Why this exists
---------------
Every chat turn fans out into a handful of FS-shaped operations: the host
JuiceFS mount sees `bootstrap_user_session`, every coding tool call resolves
into a sandbox `commands.run` round-trip, the artifact watcher does a
`list_artifacts`, and so on. Each one is cheap on its own; together they
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
because dashboards will pivot on them. The list lives in ``FS_OPS`` below as
the source of truth; adding a new op = add a constant here first.

Usage
-----

    from app.services.storage.metrics import fs_timer, FS_OPS

    async with fs_timer(FS_OPS.LIST_ARTIFACTS, conv_id=conv):
        return await _go()

    # or, when the caller already has a duration:
    record_fs_op(FS_OPS.WRITE_SESSION_FILE, duration_ms=4.2, bytes=size)

At the end of a `wide_task`, call::

    log.set(fs=flush_fs_metrics())

to attach the aggregate to the wide event. The aggregate ContextVar is
isolated per task (same mechanism as ``shared.py.wide_events``), so there is
no cross-request leakage.
"""

from __future__ import annotations

import contextlib
import contextvars
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Final


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


class FS_OPS:
    """Stable identifiers for every FS-shaped operation we instrument.

    Keep names <= 32 chars and snake_case. Adding a new metric: add the
    constant here, then reference it from the call site. Removing one is a
    breaking dashboard change — coordinate before deleting.
    """

    # Host-side JuiceFS mount management.
    JUICEFS_MOUNT: Final[str] = "juicefs_mount"
    JUICEFS_FORMAT: Final[str] = "juicefs_format"
    JUICEFS_STATUS: Final[str] = "juicefs_status"

    # Per-session host writes (the chat-stream entry path).
    BOOTSTRAP_USER_SESSION: Final[str] = "bootstrap_user_session"
    ENSURE_SESSION_DIRS: Final[str] = "ensure_session_dirs"
    MATERIALIZE_INTEGRATIONS: Final[str] = "materialize_integrations"
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


_metrics_var: contextvars.ContextVar[dict[str, _OpStats] | None] = (
    contextvars.ContextVar("fs_metrics", default=None)
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
    """
    stats = _bucket().setdefault(op, _OpStats())
    stats.count += 1
    stats.total_ms += duration_ms
    if duration_ms > stats.max_ms:
        stats.max_ms = duration_ms
    if bytes:
        stats.bytes += bytes
    if error is not None:
        stats.errors += 1
        stats.last_error_type = type(error).__name__
    if labels:
        stats.labels.update(labels)


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


@contextlib.asynccontextmanager
async def fs_timer(op: str, **labels: Any) -> AsyncIterator[None]:
    """Async context manager that records the wall-clock duration of ``op``.

    On exception, the op is still recorded (with ``error=<exception>``) so we
    can see the latency cost of a failure path in the same dashboard. The
    exception is then re-raised; never swallow.
    """
    start = time.monotonic()
    err: BaseException | None = None
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — surfaced via re-raise
        err = exc
        raise
    finally:
        elapsed_ms = (time.monotonic() - start) * 1000.0
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
    "FS_OPS",
    "add_fs_bytes",
    "flush_fs_metrics",
    "fs_timer",
    "peek_fs_metrics",
    "record_fs_op",
]
