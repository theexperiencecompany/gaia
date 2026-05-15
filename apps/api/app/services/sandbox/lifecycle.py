"""Per-user E2B sandbox lifecycle.

Public API:

    async with acquire_sandbox(user_id) as sbx:
        await sbx.commands.run(...)

The context manager handles:
  - per-user serialization via `asyncio.Lock` + refcount
  - first-call sandbox creation; subsequent-call resume/reconnect
  - mount-script execution after every cold boot
  - canary verification (E2B GH#884 mitigation) — force recreate if FS is
    stale across a pause/resume cycle
  - debounced pause-on-idle when refcount returns to zero

The yielded object is a live `AsyncSandbox` from `e2b_code_interpreter`.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

from shared.py.wide_events import log
from app.config.settings import settings
from app.db.mongodb.collections import e2b_sandboxes_collection
from app.services.sandbox.artifact_watcher import start_watcher_for
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool
from app.services.sandbox.shard_router import shard_for, shard_meta_url

CANARY_PATH = "/workspace/.gaia/canary.txt"
MOUNT_SCRIPT_PATH = "/etc/gaia/mount.sh"


class SandboxAcquisitionError(RuntimeError):
    """Raised when a usable sandbox cannot be obtained for a user."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _import_e2b() -> Any:
    """Import the E2B AsyncSandbox lazily so module import doesn't fail in dev.

    Uses the base `e2b` package (not `e2b_code_interpreter`) because our
    template is a plain Python image — no Jupyter kernel involved. All
    interaction goes through `sbx.commands.run(...)` which is in the base SDK.
    """
    from e2b import AsyncSandbox

    return AsyncSandbox


async def _create_fresh_sandbox(user_id: str, shard_id: int) -> Any:
    """Provision a new E2B sandbox for the user, run mount script, return handle."""
    if not settings.E2B_API_KEY:
        raise SandboxAcquisitionError("E2B_API_KEY is not configured")
    if not settings.E2B_TEMPLATE_ID:
        raise SandboxAcquisitionError("E2B_TEMPLATE_ID is not configured")

    async_sandbox_cls = _import_e2b()

    # `.strip()` because Infisical-fetched secrets sometimes pick up trailing
    # newlines that AWS SigV4 then rejects with cryptic "InvalidSignature".
    envs = {
        "USER_ID": user_id,
        "JFS_META_URL": shard_meta_url(shard_id),
        "JFS_R2_KEY": (settings.R2_ACCESS_KEY or "").strip(),
        "JFS_R2_SECRET": (settings.R2_SECRET_KEY or "").strip(),
        "JFS_R2_BUCKET": (settings.R2_BUCKET or "").strip(),
        "JFS_R2_ACCOUNT": (settings.R2_ACCOUNT_ID or "").strip(),
    }
    sbx = await async_sandbox_cls.create(
        template=settings.E2B_TEMPLATE_ID,
        timeout=3600,
        metadata={"user_id": user_id, "shard_id": str(shard_id)},
        envs=envs,
    )
    await _run_mount_script(sbx)
    return sbx


async def _run_mount_script(sbx: Any) -> None:
    """Run the bundled mount script that mounts JuiceFS + bind-mounts /workspace.

    The mount itself is best-effort inside the script: if the JuiceFS
    metadata DB or R2 isn't reachable from the sandbox, the script falls
    back to a plain `/workspace` directory and exits 0. We only raise here
    if the script genuinely crashed (couldn't even fall back).
    """
    # sudo strips env by default; preserve the ones the script reads so it
    # can actually find JFS_META_URL / USER_ID / R2 creds.
    preserve = (
        "USER_ID,JFS_META_URL,JFS_R2_KEY,JFS_R2_SECRET,JFS_R2_BUCKET,JFS_R2_ACCOUNT"
    )
    result = await sbx.commands.run(
        f"sudo --preserve-env={preserve} {MOUNT_SCRIPT_PATH}",
        timeout=60,
    )
    if result.exit_code != 0:
        raise SandboxAcquisitionError(
            f"Mount script crashed (exit {result.exit_code}): {result.stderr}"
        )
    # If the script took the ephemeral path it logs a `WARN:` to stderr —
    # surface that so we know the sandbox FS isn't durable.
    stderr = getattr(result, "stderr", "") or ""
    if "WARN:" in stderr:
        log.warning(f"[sandbox] ephemeral /workspace fallback: {stderr.strip()}")


async def _run_silent(sbx: Any, cmd: str, *, timeout: int = 10) -> tuple[int, str, str]:
    """Run a command, returning (exit_code, stdout, stderr) without raising.

    `sbx.commands.run` raises `CommandExitException` on any non-zero exit,
    which is wrong for our internal probes (mountpoint -q, canary read, etc.)
    where non-zero is a legitimate "no" answer, not an error.
    """
    try:
        result = await sbx.commands.run(cmd, timeout=timeout)
        return (
            getattr(result, "exit_code", 0) or 0,
            getattr(result, "stdout", "") or "",
            getattr(result, "stderr", "") or "",
        )
    except Exception as e:
        msg = str(e)
        # E2B's CommandExitException includes the exit code in its string repr;
        # we don't need to parse it precisely — any non-zero is "no".
        return 1, "", msg


async def _ensure_mounted(sbx: Any) -> None:
    """No-op if /workspace is mounted, else re-run mount script.

    Handles stale FUSE mounts after pause/resume.
    """
    exit_code, _, _ = await _run_silent(sbx, "mountpoint -q /workspace", timeout=5)
    if exit_code != 0:
        await _run_mount_script(sbx)


async def _write_canary(sbx: Any) -> str:
    """Write a fresh canary timestamp and return its value."""
    ts = _now().isoformat()
    await _run_silent(
        sbx,
        f"mkdir -p /workspace/.gaia && echo '{ts}' > {CANARY_PATH}",
        timeout=5,
    )
    return ts


async def _read_canary(sbx: Any) -> Optional[str]:
    """Return the canary contents, or None if the file is missing/unreadable."""
    exit_code, stdout, _ = await _run_silent(sbx, f"cat {CANARY_PATH}", timeout=5)
    if exit_code != 0:
        return None
    return stdout.strip() or None


async def _verify_canary_or_die(entry: PooledSandbox) -> bool:
    """Check that the in-sandbox canary matches our cached value.

    Returns True if the canary is valid (proceed with the call). Returns False
    if the FS appears stale and the sandbox should be discarded + recreated.
    """
    if entry.last_canary_ts is None:
        # First use after acquire — write canary now.
        entry.last_canary_ts = await _write_canary(entry.sandbox)
        return True
    actual = await _read_canary(entry.sandbox)
    return actual == entry.last_canary_ts


async def _try_connect_or_resume(sandbox_id: str) -> Optional[Any]:
    """Try `connect`, then `resume`. Returns None if both fail.

    Each attempt is bounded to 10s so a hung E2B control-plane call doesn't
    stall the agent — we'd rather just create a fresh sandbox.
    """
    async_sandbox_cls = _import_e2b()
    for method_name in ("connect", "resume"):
        method = getattr(async_sandbox_cls, method_name, None)
        if method is None:
            continue
        try:
            return await asyncio.wait_for(method(sandbox_id), timeout=10)
        except (asyncio.TimeoutError, Exception) as e:
            log.info(
                f"AsyncSandbox.{method_name}({sandbox_id}) failed: {e}",
            )
    return None


async def _health_probe(sbx: Any) -> bool:
    """Return True if the sandbox responds within a short window."""
    try:
        exit_code, _, _ = await asyncio.wait_for(
            _run_silent(sbx, "true", timeout=3),
            timeout=5,
        )
        return exit_code == 0
    except Exception:
        return False


async def _ensure_watcher(user_id: str, entry: PooledSandbox) -> None:
    """Start the artifact watcher if it isn't already running.

    Best-effort: the watcher is a latency optimization for surfacing
    `artifacts/` artifacts; the host-side JuiceFS list is authoritative,
    so a watcher failure must never block sandbox acquisition.
    """
    if entry.watcher is not None and entry.watcher.is_alive():
        return
    with contextlib.suppress(Exception):
        entry.watcher = await start_watcher_for(user_id, entry.sandbox)


async def _stop_watcher(entry: PooledSandbox) -> None:
    """Stop + drop the watcher. HTTP/2 streams to envd don't survive
    pause/kill, so we reopen on the next acquire."""
    if entry.watcher is not None:
        with contextlib.suppress(Exception):
            await entry.watcher.stop()
        entry.watcher = None


async def _acquire_or_create(user_id: str) -> PooledSandbox:
    """Return a PooledSandbox for the user, creating/resuming as needed."""
    pool = get_sandbox_pool()
    entry = pool.get(user_id)
    if entry is not None and entry.sandbox is not None:
        if entry.pause_task is not None and not entry.pause_task.done():
            entry.pause_task.cancel()
            entry.pause_task = None
        # Cheap liveness check first — if the cached handle is stale (sandbox
        # was paused / killed since we last touched it), evict and create
        # fresh. Otherwise we'd hang for the full command timeout below.
        if not await _health_probe(entry.sandbox):
            log.info(f"[sandbox] cached handle unhealthy for {user_id}; evicting")
            await _hard_evict(user_id, entry)
            entry = None  # type: ignore[assignment]
        else:
            await _ensure_mounted(entry.sandbox)
            if not await _verify_canary_or_die(entry):
                log.warning(f"Canary stale for user {user_id}; recreating sandbox")
                await _hard_evict(user_id, entry)
                entry = None  # type: ignore[assignment]
            else:
                await _ensure_watcher(user_id, entry)
                return entry

    shard_id = shard_for(user_id)
    doc = await e2b_sandboxes_collection.find_one({"user_id": user_id})

    sbx: Optional[Any] = None
    workspace_version = 0

    if doc and doc.get("sandbox_id"):
        sbx = await _try_connect_or_resume(doc["sandbox_id"])
        workspace_version = doc.get("workspace_version", 0)
        if sbx is not None and not await _health_probe(sbx):
            log.info(
                f"[sandbox] resumed sandbox {doc['sandbox_id']} still unhealthy "
                f"after connect/resume; falling through to fresh create"
            )
            sbx = None
        if sbx is not None:
            await _ensure_mounted(sbx)

    if sbx is None:
        sbx = await _create_fresh_sandbox(user_id, shard_id)
        workspace_version += 1

    canary_ts = await _write_canary(sbx)

    await e2b_sandboxes_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "sandbox_id": getattr(sbx, "sandbox_id", None),
                "template_id": settings.E2B_TEMPLATE_ID,
                "shard_id": shard_id,
                "state": "active",
                "workspace_version": workspace_version,
                "last_used_at": _now(),
                "last_canary_ts": canary_ts,
            },
            "$setOnInsert": {"created_at": _now()},
            "$inc": {"total_invocations": 1},
        },
        upsert=True,
    )

    entry = PooledSandbox(sandbox=sbx, last_canary_ts=canary_ts)
    pool.put(user_id, entry)
    await _ensure_watcher(user_id, entry)
    return entry


async def _schedule_pause(user_id: str, entry: PooledSandbox) -> None:
    """Pause the sandbox after the idle window if no further work arrives."""

    async def _pause_after_delay() -> None:
        try:
            await asyncio.sleep(settings.E2B_SANDBOX_IDLE_PAUSE_SECONDS)
            if entry.refcount > 0:
                return
            pause = getattr(entry.sandbox, "pause", None)
            if pause is None:
                return
            await _stop_watcher(entry)
            try:
                await pause()
                await e2b_sandboxes_collection.update_one(
                    {"user_id": user_id},
                    {"$set": {"state": "paused", "paused_at": _now()}},
                )
            except Exception as e:
                log.warning(f"Pause failed for user {user_id}: {e}")
        except asyncio.CancelledError:
            return

    entry.pause_task = asyncio.create_task(_pause_after_delay())


async def _hard_evict(user_id: str, entry: PooledSandbox) -> None:
    """Drop a sandbox from the pool and best-effort kill it."""
    pool = get_sandbox_pool()
    pool.evict(user_id)
    if entry.pause_task is not None and not entry.pause_task.done():
        entry.pause_task.cancel()
    await _stop_watcher(entry)
    kill = getattr(entry.sandbox, "kill", None)
    if kill is not None:
        with contextlib.suppress(Exception):
            await kill()


async def mark_sandbox_dead(user_id: str) -> None:
    """Forcibly drop the cached sandbox and mark it dead in Mongo. Caller's
    next acquire will create a fresh one."""
    pool = get_sandbox_pool()
    entry = pool.evict(user_id)
    if entry is not None:
        await _hard_evict(user_id, entry)
    await e2b_sandboxes_collection.update_one(
        {"user_id": user_id},
        {"$set": {"state": "dead", "last_used_at": _now()}},
    )


async def pause_sandbox_for_user(user_id: str) -> bool:
    """Synchronous pause request (e.g. for tests or maintenance)."""
    pool = get_sandbox_pool()
    entry = pool.get(user_id)
    if entry is None:
        return False
    pause = getattr(entry.sandbox, "pause", None)
    if pause is None:
        return False
    try:
        await pause()
        await e2b_sandboxes_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": "paused", "paused_at": _now()}},
        )
        return True
    except Exception as e:
        log.warning(f"Manual pause failed for user {user_id}: {e}")
        return False


@contextlib.asynccontextmanager
async def acquire_sandbox(user_id: str) -> AsyncIterator[Any]:
    """Context manager that yields a live `AsyncSandbox` for the user.

    Serializes against concurrent calls for the same user. Schedules a
    debounced pause when the last in-flight call finishes.
    """
    if not user_id:
        raise SandboxAcquisitionError("user_id is required")

    pool = get_sandbox_pool()
    lock = await pool.get_lock(user_id)
    await lock.acquire()
    try:
        entry = await _acquire_or_create(user_id)
        entry.refcount += 1
        try:
            yield entry.sandbox
        finally:
            entry.refcount -= 1
            await e2b_sandboxes_collection.update_one(
                {"user_id": user_id},
                {"$set": {"last_used_at": _now()}},
            )
            if entry.refcount <= 0:
                await _schedule_pause(user_id, entry)
    finally:
        lock.release()
