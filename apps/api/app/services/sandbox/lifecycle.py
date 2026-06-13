"""Per-user E2B sandbox lifecycle.

Public API:

    async with acquire_sandbox(user_id) as sbx:
        await sbx.commands.run(...)

The context manager handles:
  - per-user serialization via `asyncio.Lock` + refcount
  - first-call sandbox creation; subsequent-call connect (auto-resumes a paused
    sandbox — there is no separate resume step)
  - mount-script execution after every cold boot
  - canary verification (E2B GH#884 mitigation) — force recreate if FS is
    stale across a pause/resume cycle
  - debounced pause-on-idle when refcount returns to zero

The yielded object is a live `AsyncSandbox` from `e2b`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
from datetime import UTC, datetime
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from e2b import AsyncSandbox

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.config.settings import settings
from app.constants.sandbox import (
    HEALTH_PROBE_REQUEST_TIMEOUT_SECONDS,
    HEALTH_PROBE_WAIT_TIMEOUT_SECONDS,
    SANDBOX_CONNECT_TIMEOUT_SECONDS,
    SANDBOX_LIFETIME_SECONDS,
    SANDBOX_TIMEOUT_REFRESH_SECONDS,
)
from app.db.mongodb.collections import e2b_sandboxes_collection
from app.decorators import enforce_rate_limit
from app.services.sandbox.artifact_watcher import start_watcher_for
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool
from app.services.sandbox.shard_router import shard_for, shard_meta_url
from app.services.storage import (
    FsOps,
    JuiceFSUnavailable,
    ensure_user_skills_dir,
    ensure_user_workspace,
    fs_timer,
)
from shared.py.wide_events import log

CANARY_PATH = "/workspace/.gaia/canary.txt"
MOUNT_SCRIPT_PATH = "/etc/gaia/mount.sh"
SANDBOX_CREATION_FEATURE_KEY = "sandbox_creation"


class SandboxAcquisitionError(RuntimeError):
    """Raised when a usable sandbox cannot be obtained for a user."""


class SandboxRateLimitError(SandboxAcquisitionError):
    """Raised when the user has exhausted their sandbox-creation rate limit."""


def _now() -> datetime:
    return datetime.now(UTC)


def _split_meta_url(url: str) -> tuple[str, str]:
    """Split a Postgres meta URL into (url_without_password, password).

    Keeping the password out of the URL argv is mandatory: the juicefs daemon
    long-lives with the URL spliced into its `cmdline`, and Linux exposes
    `/proc/<pid>/cmdline` world-readable. The unprivileged sandbox user could
    otherwise recover the meta-DB Postgres credentials with one `cat`. JuiceFS
    reads `META_PASSWORD` from env when the URL has no userinfo password.

    Empty / userinfo-less URLs round-trip cleanly so callers don't need to
    branch (dev / local Postgres without a password).
    """
    if not url:
        return "", ""
    parts = urlsplit(url)
    password = parts.password or ""
    if not password:
        return url, ""
    # Rebuild netloc without the password but with the username intact.
    username = parts.username or ""
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    netloc = f"{username}@{host}" if username else host
    sanitized = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return sanitized, password


def _mount_env(user_id: str, shard_id: int) -> dict[str, str]:
    """Build the env block consumed by ``mount.sh``.

    These values are credentials: the JuiceFS metadata URL plus R2 keys give
    full filesystem access. They MUST NOT appear in argv or in any
    unprivileged process's environ.

    Delivery model: the API invokes ``mount.sh`` via
    ``commands.run(MOUNT_SCRIPT_PATH, user="root", envs=mount_env)``. e2b's
    envd (running as root inside the sandbox) sets these on the new root
    process directly — there is no unprivileged intermediate shell, and the
    sandbox user (who has no `sudo`) cannot read root's ``/proc/<pid>/environ``
    (mode 0o400).

    The meta URL is split here so the Postgres password rides in
    ``META_PASSWORD`` env (which JuiceFS reads) instead of being spliced into
    the URL argv passed to the long-running juicefs daemon — that argv shows
    up world-readable in ``/proc/<pid>/cmdline``.

    ``.strip()`` because Infisical-fetched secrets sometimes pick up trailing
    newlines that AWS SigV4 then rejects with cryptic "InvalidSignature".
    """
    meta_url_with_pw = shard_meta_url(shard_id)
    meta_url, meta_password = _split_meta_url(meta_url_with_pw)
    return {
        "USER_ID": user_id,
        "JFS_META_URL": meta_url,
        "META_PASSWORD": meta_password,
        "JFS_R2_KEY": (settings.R2_ACCESS_KEY or "").strip(),
        "JFS_R2_SECRET": (settings.R2_SECRET_KEY or "").strip(),
        "JFS_R2_BUCKET": (settings.R2_BUCKET or "").strip(),
        "JFS_R2_ACCOUNT": (settings.R2_ACCOUNT_ID or "").strip(),
    }


async def _enforce_creation_limit(user_id: str) -> None:
    """Gate fresh sandbox provisioning behind the tiered rate limiter.

    Only the create path is gated — reusing or resuming an existing sandbox
    stays unlimited; provisioning a new E2B VM is the cost driver.
    """
    try:
        await enforce_rate_limit(user_id, SANDBOX_CREATION_FEATURE_KEY)
    except RateLimitExceededException as e:
        log.warning(f"[sandbox] creation rate limit hit for user {user_id}")
        detail: dict[str, Any] = e.detail if isinstance(e.detail, dict) else {}
        message = "sandbox creation limit reached"
        if detail.get("reset_time"):
            message += f"; resets at {detail['reset_time']}"
        if detail.get("plan_required"):
            message += f" (upgrade to {detail['plan_required'].upper()} for higher limits)"
        raise SandboxRateLimitError(message) from e
    except Exception as e:
        log.error(f"[sandbox] creation limit check failed for user {user_id}: {e}")
        raise SandboxAcquisitionError(f"sandbox creation limit check failed: {e}") from e


async def _create_fresh_sandbox(user_id: str, shard_id: int) -> Any:
    """Provision a new E2B sandbox for the user, run mount script, return handle."""
    if not settings.E2B_API_KEY:
        raise SandboxAcquisitionError("E2B_API_KEY is not configured")
    if not settings.E2B_TEMPLATE_ID:
        raise SandboxAcquisitionError("E2B_TEMPLATE_ID is not configured")

    async_sandbox_cls = AsyncSandbox

    # Sandbox-wide env is deliberately empty of credentials — see _mount_env
    # docstring. USER_ID is not a secret but we still scope it per-call so
    # there's no implicit reliance on sandbox-wide identity for security.
    async with fs_timer(FsOps.SBX_CREATE):
        sbx = await async_sandbox_cls.create(
            template=settings.E2B_TEMPLATE_ID,
            timeout=SANDBOX_LIFETIME_SECONDS,
            metadata={"user_id": user_id, "shard_id": str(shard_id)},
        )
    await _run_mount_script(sbx, _mount_env(user_id, shard_id))
    return sbx


async def _run_mount_script(sbx: Any, mount_env: dict[str, str]) -> None:
    """Run the bundled mount script that mounts JuiceFS + bind-mounts /workspace.

    The mount itself is best-effort inside the script: if the JuiceFS
    metadata DB or R2 isn't reachable from the sandbox, the script falls
    back to a plain ``/workspace`` directory and exits 0. We only raise here
    if the script genuinely crashed (couldn't even fall back).

    ``user="root"`` makes e2b's envd fork the process directly as root, with
    ``envs=mount_env`` set on that root process's environment. The
    unprivileged sandbox user never holds the credentials — no
    ``sudo --preserve-env`` shell is involved, so there is no parent-shell
    environ race window. The sandbox user has no `sudo` (template removes
    them from the `sudo` group), so root's ``/proc/<pid>/environ`` stays
    inaccessible.
    """
    async with fs_timer(FsOps.SBX_MOUNT_SCRIPT):
        result = await sbx.commands.run(
            MOUNT_SCRIPT_PATH,
            timeout=60,
            envs=mount_env,
            user="root",
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


# NOSONAR python:S7483 — `timeout` is the E2B server-side command-stream
# deadline forwarded to `sbx.commands.run`; when it fires the SDK stops
# streaming and raises. An asyncio.timeout() would only cancel the local
# coroutine, not bound the remote command, which is why S7483 doesn't apply.
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


async def _ensure_mounted(sbx: Any, mount_env: dict[str, str]) -> None:
    """No-op if /workspace is mounted, else re-run mount script.

    Handles stale FUSE mounts after pause/resume. ``mount_env`` is required
    because the credentials are no longer sandbox-wide — every call site
    that may re-run the script must supply them (see ``_mount_env``).
    """
    async with fs_timer(FsOps.SBX_ENSURE_MOUNTED):
        exit_code, _, _ = await _run_silent(sbx, "mountpoint -q /workspace", timeout=5)
        if exit_code != 0:
            await _run_mount_script(sbx, mount_env)


async def _write_canary(sbx: Any) -> str:
    """Write a fresh canary timestamp and return its value.

    Native `files.write` auto-creates the `.gaia/` parent and treats the
    timestamp as data, not shell argv — no `mkdir`/`echo` round-trip.
    """
    ts = _now().isoformat()
    await sbx.files.write(CANARY_PATH, ts)
    return ts


async def _read_canary(sbx: Any) -> str | None:
    """Return the canary contents, or None if the file is missing/unreadable."""
    try:
        content = await sbx.files.read(CANARY_PATH)
    except Exception:
        # Missing (NotFoundException) or any read failure → treat as stale.
        return None
    return content.strip() or None


async def _verify_canary_or_die(entry: PooledSandbox) -> bool:
    """Check that the in-sandbox canary matches our cached value.

    Returns True if the canary is valid (proceed with the call). Returns False
    if the FS appears stale and the sandbox should be discarded + recreated.
    """
    async with fs_timer(FsOps.SBX_CANARY_VERIFY):
        if entry.last_canary_ts is None:
            # First use after acquire — write canary now.
            entry.last_canary_ts = await _write_canary(entry.sandbox)
            return True
        actual = await _read_canary(entry.sandbox)
        return actual == entry.last_canary_ts


async def _connect_sandbox(sandbox_id: str) -> Any | None:
    """Connect to a recorded sandbox, auto-resuming it if paused. None on failure.

    `AsyncSandbox.connect` already resumes a paused sandbox — there is no
    separate `resume()` in the SDK. Passing `timeout` refreshes the sandbox's
    server-side lifetime so a resumed sandbox doesn't inherit the SDK's short
    default. Bounded so a hung E2B control-plane call falls through to a fresh
    create instead of stalling the agent.
    """
    async with fs_timer(FsOps.SBX_CONNECT_RESUME):
        try:
            return await asyncio.wait_for(
                AsyncSandbox.connect(sandbox_id, timeout=SANDBOX_LIFETIME_SECONDS),
                timeout=SANDBOX_CONNECT_TIMEOUT_SECONDS,
            )
        except Exception as e:
            log.info(f"AsyncSandbox.connect({sandbox_id}) failed: {e}")
            return None


async def _health_probe(sbx: Any) -> bool:
    """Return True if the sandbox responds within a short window.

    Uses the official E2B health endpoint (HTTP GET /health) which is faster
    and more reliable than spawning a shell process — a degraded sandbox can
    still fork `true` while being unable to execute real I/O workloads.
    """
    async with fs_timer(FsOps.SBX_HEALTH_PROBE):
        try:
            return await asyncio.wait_for(
                sbx.is_running(request_timeout=HEALTH_PROBE_REQUEST_TIMEOUT_SECONDS),
                timeout=HEALTH_PROBE_WAIT_TIMEOUT_SECONDS,
            )
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


async def _seed_user_subtrees(user_id: str) -> None:
    """Pre-create the per-user JuiceFS subtrees the sandbox's --subdir mounts
    need on the HOST side, so the sandbox never has to do a full-FS admin
    mount itself.

    Soft-fails when the host JuiceFS mount is missing (dev mode) — the
    sandbox-side mount.sh will then take its ephemeral-fallback branch.
    """
    try:
        await ensure_user_workspace(user_id)
        await ensure_user_skills_dir(user_id)
    except JuiceFSUnavailable:
        # Dev mode without juicefs — mount.sh will fall back to ephemeral
        # /workspace, which is fine for tool calls but won't persist.
        return


async def _reuse_cached_entry(user_id: str, mount_env: dict[str, str]) -> PooledSandbox | None:
    """Return a healthy cached PooledSandbox, or None if it must be recreated.

    Evicts the cached entry when it is unhealthy or its canary is stale.
    """
    pool = get_sandbox_pool()
    entry = pool.get(user_id)
    if entry is None or entry.sandbox is None:
        return None

    # Stop any in-flight idle-pause before reusing, and wait for it to actually
    # finish — a bare cancel() only *requests* cancellation, so without the await
    # the pause could already be mid-flight server-side and we'd reuse a pausing
    # sandbox (the health probe below would then force a wasteful recreate).
    await _cancel_pause_task(entry)

    # Cheap liveness check first — if the cached handle is stale (sandbox
    # was paused / killed since we last touched it), evict and create
    # fresh. Otherwise we'd hang for the full command timeout below.
    if not await _health_probe(entry.sandbox):
        log.info(f"[sandbox] cached handle unhealthy for {user_id}; evicting")
        await _hard_evict(user_id, entry)
        return None

    # Running commands does NOT reset E2B's server-side kill timer — only
    # connect()/set_timeout() do. Refresh it so a continuously active session is
    # never killed mid-use at the original create deadline — but only once per
    # refresh window, not on every tool call: a rapid multi-tool turn would
    # otherwise pay a set_timeout round-trip per call for no benefit.
    if time.monotonic() - entry.timeout_refreshed_at > SANDBOX_TIMEOUT_REFRESH_SECONDS:
        with contextlib.suppress(Exception):
            await entry.sandbox.set_timeout(SANDBOX_LIFETIME_SECONDS)
            entry.timeout_refreshed_at = time.monotonic()

    await _ensure_mounted(entry.sandbox, mount_env)
    if not await _verify_canary_or_die(entry):
        log.warning(f"Canary stale for user {user_id}; recreating sandbox")
        await _hard_evict(user_id, entry)
        return None

    await _ensure_watcher(user_id, entry)
    return entry


async def _resume_existing_sandbox(doc: dict[str, Any], mount_env: dict[str, str]) -> Any | None:
    """Connect to a recorded sandbox (auto-resuming if paused); None if unusable."""
    sbx = await _connect_sandbox(doc["sandbox_id"])
    if sbx is not None and not await _health_probe(sbx):
        log.info(
            f"[sandbox] resumed sandbox {doc['sandbox_id']} still unhealthy "
            f"after connect; falling through to fresh create"
        )
        sbx = None
    if sbx is not None:
        await _ensure_mounted(sbx, mount_env)
    return sbx


async def _acquire_or_create(user_id: str) -> PooledSandbox:
    """Return a PooledSandbox for the user, creating/resuming as needed."""
    pool = get_sandbox_pool()
    shard_id = shard_for(user_id)
    # Built once per acquire so _ensure_mounted can re-run mount.sh on a
    # stale FUSE without resorting to sandbox-wide credential env vars.
    mount_env = _mount_env(user_id, shard_id)

    cached = await _reuse_cached_entry(user_id, mount_env)
    if cached is not None:
        return cached

    doc = await e2b_sandboxes_collection.find_one({"user_id": user_id})

    sbx: Any | None = None
    workspace_version = 0

    if doc and doc.get("sandbox_id"):
        sbx = await _resume_existing_sandbox(doc, mount_env)
        workspace_version = doc.get("workspace_version", 0)

    if sbx is None:
        await _enforce_creation_limit(user_id)
        # Pre-create the per-user subtrees host-side so the sandbox's
        # ``--subdir`` mounts find them ready. Doing this on the host (which
        # holds the full JuiceFS mount) avoids ever exposing the full
        # cross-user namespace inside the sandbox, even briefly.
        await _seed_user_subtrees(user_id)
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

    # create()/connect() just set the kill timer to a full lifetime, so stamp
    # the refresh clock now — the first reuse won't redundantly re-set it.
    entry = PooledSandbox(
        sandbox=sbx, last_canary_ts=canary_ts, timeout_refreshed_at=time.monotonic()
    )
    pool.put(user_id, entry)
    await _ensure_watcher(user_id, entry)
    return entry


async def _cancel_pause_task(entry: PooledSandbox) -> None:
    """Cancel a pending idle-pause task and wait for it to fully unwind."""
    task = entry.pause_task
    entry.pause_task = None
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def _pause_sandbox(user_id: str, entry: PooledSandbox) -> bool:
    """Pause the sandbox and record the paused state. False on failure.

    The SDK method is `beta_pause` (there is no plain `pause`); it snapshots
    both filesystem and memory so a later `connect()` resumes in place.
    """
    try:
        await entry.sandbox.beta_pause()
        await e2b_sandboxes_collection.update_one(
            {"user_id": user_id},
            {"$set": {"state": "paused", "paused_at": _now()}},
        )
        return True
    except Exception as e:
        log.warning(f"Pause failed for user {user_id}: {e}")
        return False


def _schedule_pause(user_id: str, entry: PooledSandbox) -> None:
    """Pause the sandbox after the idle window if no further work arrives."""

    async def _pause_after_delay() -> None:
        # CancelledError (from the sleep or the pause) propagates naturally — the
        # inner ``except Exception`` never catches it — so the idle-pause task
        # cancels cleanly when work arrives.
        await asyncio.sleep(settings.E2B_SANDBOX_IDLE_PAUSE_SECONDS)
        if entry.refcount > 0:
            return
        await _stop_watcher(entry)
        await _pause_sandbox(user_id, entry)

    # Replace any prior pending pause so two tasks can't both fire on one entry.
    if entry.pause_task is not None and not entry.pause_task.done():
        entry.pause_task.cancel()
    entry.pause_task = asyncio.create_task(_pause_after_delay())


async def _hard_evict(user_id: str, entry: PooledSandbox) -> None:
    """Drop a sandbox from the pool and best-effort kill it."""
    get_sandbox_pool().evict(user_id)
    await _cancel_pause_task(entry)
    await _stop_watcher(entry)
    # `kill()` returns False (never raises) if the sandbox is already gone.
    with contextlib.suppress(Exception):
        await entry.sandbox.kill()


async def mark_sandbox_dead(user_id: str) -> None:
    """Forcibly drop the cached sandbox and mark it dead in Mongo. Caller's
    next acquire will create a fresh one."""
    entry = get_sandbox_pool().get(user_id)
    if entry is not None:
        await _hard_evict(user_id, entry)
    await e2b_sandboxes_collection.update_one(
        {"user_id": user_id},
        {"$set": {"state": "dead", "last_used_at": _now()}},
    )


async def pause_sandbox_for_user(user_id: str) -> bool:
    """Synchronous pause request (e.g. for tests or maintenance)."""
    entry = get_sandbox_pool().get(user_id)
    if entry is None:
        return False
    await _cancel_pause_task(entry)
    await _stop_watcher(entry)
    return await _pause_sandbox(user_id, entry)


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
        async with fs_timer(FsOps.SBX_ACQUIRE):
            entry = await _acquire_or_create(user_id)
        entry.refcount += 1
        sandbox_dead = False
        try:
            yield entry.sandbox
        except Exception:
            # A tool op failed. It could mean the sandbox itself died (E2B
            # timeout/kill, transport gone) or just a command/file error. Ask
            # the official /health endpoint rather than parsing error text — if
            # it's not running, evict so the next acquire recreates. Owning this
            # here means every tool (bash/read/write/edit) gets death-eviction
            # uniformly; none need their own detection.
            sandbox_dead = not await _health_probe(entry.sandbox)
            raise
        finally:
            entry.refcount -= 1
            if sandbox_dead:
                with contextlib.suppress(Exception):
                    await mark_sandbox_dead(user_id)
            else:
                with contextlib.suppress(Exception):
                    await e2b_sandboxes_collection.update_one(
                        {"user_id": user_id},
                        {"$set": {"last_used_at": _now()}},
                    )
                if entry.refcount <= 0:
                    _schedule_pause(user_id, entry)
    finally:
        lock.release()
