"""JuiceFS bootstrap — mounts the host-side sidecar at app startup.

Why this lives in Python (not the docker entrypoint):
Production secrets are pulled by `inject_infisical_secrets()` during Pydantic
settings load. By that point the bash entrypoint has already exec-ed Python,
so the R2/JuiceFS env vars are only available *inside* the Python process.

Design (production-manageable):
- **Non-blocking**: the lazy provider spawns a daemon thread and returns
  immediately. App startup is never gated on the mount; the storage helpers
  already soft-fail (`JuiceFSUnavailable`) until `/mnt/jfs` is ready, and
  converge automatically once it is.
- **Supervised foreground mount**: we run `juicefs mount` in the foreground
  as a detached child and poll the mountpoint ourselves, instead of relying
  on `juicefs mount --background`'s aggressive internal 10s readiness check
  (which FATALs under high managed-Postgres meta latency even though the
  mount would have succeeded).
- **Retry with backoff** on transient meta failures (serverless Postgres
  cold-starts, DNS/AAAA flaps, transient network blips) — a real production
  concern with Neon/Supabase, not just a local quirk.
- **Env-tunable**: timeout / attempts / backoff are settings, so prod can
  tune behavior without a code change or redeploy.
- **Idempotent + soft-fail**: safe to run anywhere; never raises.

If the binary is missing or required settings aren't populated, it logs and
returns — the storage helpers treat the missing mount as a soft-fail.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess  # nosec B404 - JuiceFS CLI invocation
import tempfile
import threading
import time

from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider
from app.services.storage.metrics import FsOps, record_fs_op  # noqa: F401
from shared.py.wide_events import log

_ENCRYPTION_KEY_FILE = Path("/etc/gaia/jfs-master.pem")
_CACHE_DIR = Path("/var/cache/juicefs")
_CACHE_SIZE_MB = 4096
_BUFFER_SIZE_MB = 600
_MAX_UPLOADS = 20

# Failure classification is allowlist-by-permanent: only an explicit,
# clearly-permanent misconfiguration should make bootstrap give up. Anything
# else — transient network blips, serverless-Postgres (Neon) cold-starts,
# *and opaque juicefs process crashes* (Go runtime aborts during meta
# NewSession show up as a register dump, not a tidy error string) — is
# retried with backoff. A spurious retry is cheap; giving up on a flaky
# managed-DB dependency that demonstrably works on a later attempt is not.
_PERMANENT_MARKERS = (
    "authentication failed",
    "password authentication failed",
    "permission denied",
    "access denied",
    "invalid access key",
    "signaturedoesnotmatch",
    "no such bucket",
    "specified bucket does not exist",
    "unknown authority",
    "certificate is not valid",
)
# NOTE: DNS failures ("no such host", "server misbehaving", NXDOMAIN) are
# deliberately NOT permanent — Docker's embedded resolver (and serverless
# providers) intermittently fail to resolve an external meta host that
# resolves fine on a later attempt. Treat as transient and retry.


def _classify(text: str) -> str:
    """Return "fatal" only for an explicit permanent error, else "transient"."""
    low = (text or "").lower()
    return "fatal" if any(marker in low for marker in _PERMANENT_MARKERS) else "transient"


# Module state — guards against the bootstrap thread being spawned twice.
_bootstrap_lock = threading.Lock()
_bootstrap_thread: threading.Thread | None = None


def _missing_settings() -> list[str]:
    """Return names of required settings that are still unset."""
    required = {
        "R2_ACCOUNT_ID": settings.R2_ACCOUNT_ID,
        "R2_BUCKET": settings.R2_BUCKET,
        "R2_ACCESS_KEY": settings.R2_ACCESS_KEY,
        "R2_SECRET_KEY": settings.R2_SECRET_KEY,
        "JUICEFS_META_URL_TEMPLATE": settings.JUICEFS_META_URL_TEMPLATE,
    }
    return [name for name, value in required.items() if not value]


def _meta_url(shard: int = 0) -> str:
    """Resolve the metadata URL for a shard, normalizing scheme for JuiceFS."""
    template = settings.JUICEFS_META_URL_TEMPLATE or ""
    if "{shard}" in template:
        template = template.replace("{shard}", str(shard))
    # JuiceFS rejects `postgresql://` — managed PG providers use it; rewrite.
    if template.startswith("postgresql://"):
        template = "postgres://" + template[len("postgresql://") :]
    return template


def _mask_meta(url: str) -> str:
    """Host/db only — never log credentials."""
    tail = url.split("@", 1)[-1] if "@" in url else url
    return tail.split("?", 1)[0]


def _bucket_url() -> str:
    return f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{settings.R2_BUCKET}"


def _is_mounted(path: Path) -> bool:
    """Best-effort mountpoint check that works on Linux + macOS."""
    if not path.exists():
        return False
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["mountpoint", "-q", str(path)],
            check=False,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        try:
            return path.is_mount()
        except (AttributeError, OSError):
            return False


def _materialize_encryption_key() -> Path | None:
    """Write the PEM env var to a file if present, return its path."""
    pem = (settings.JFS_ENCRYPTION_KEY or "").strip()
    if not pem:
        return None
    target = _ENCRYPTION_KEY_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.is_dir():
            raise PermissionError(f"{target.parent} not writable")
    except (PermissionError, OSError):
        fd, fallback = tempfile.mkstemp(prefix="jfs-master-", suffix=".pem")
        os.close(fd)
        target = Path(fallback)
    target.write_text(pem if pem.endswith("\n") else pem + "\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def _run(
    cmd: list[str],
    *,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a short-lived subprocess and capture output for logging.

    When ``env`` is provided, it is merged onto the inherited environment
    (rather than replacing it) so the child still sees PATH / LD_LIBRARY_PATH
    / etc. We use this to feed R2 credentials via env instead of argv when
    invoking ``juicefs format`` — argv is visible to anyone with shell on the
    host via ``ps auxww`` during the format window.
    """
    merged_env: dict[str, str] | None
    if env is None:
        merged_env = None
    else:
        merged_env = {**os.environ, **env}
    return subprocess.run(  # nosec B603 - argv list, no shell
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged_env,
    )


def _format_if_needed(meta_url: str, encrypt_key: Path | None) -> str:
    """Format the volume if the meta isn't initialized yet.

    Returns "ok" | "transient" | "fatal". Idempotent: an already-formatted
    volume (status==0) or a concurrent-format race is "ok".
    """
    status_started = time.monotonic()
    status = _run(["juicefs", "status", meta_url], timeout=20)
    record_fs_op(
        FsOps.JUICEFS_STATUS,
        duration_ms=(time.monotonic() - status_started) * 1000.0,
        outcome="ok" if status.returncode == 0 else "miss",
    )
    if status.returncode == 0:
        log.info("[juicefs] filesystem already formatted")
        return "ok"
    if _classify(status.stderr) == "fatal":
        log.warning(
            "[juicefs] permanent error during status",
            meta=_mask_meta(meta_url),
            detail=status.stderr.strip()[:300],
        )
        return "fatal"
    # Non-zero status with no permanent marker == "not formatted yet" (or a
    # transient blip); attempt format — it will surface its own outcome.
    # R2 credentials ride in env (the JuiceFS CLI honours the standard AWS
    # variables when --access-key/--secret-key are absent), so they do not
    # appear in argv visible to `ps auxww` during the format window.
    log.info(f"[juicefs] formatting filesystem against {_bucket_url()}")
    cmd: list[str] = [
        "juicefs",
        "format",
        "--storage",
        "s3",
        "--bucket",
        _bucket_url(),
    ]
    if encrypt_key is not None:
        cmd.extend(["--encrypt-rsa-key", str(encrypt_key)])
    cmd.extend([meta_url, "gaia-0"])
    fmt_env = {
        "AWS_ACCESS_KEY_ID": (settings.R2_ACCESS_KEY or "").strip(),
        "AWS_SECRET_ACCESS_KEY": (settings.R2_SECRET_KEY or "").strip(),
    }
    fmt_started = time.monotonic()
    fmt = _run(cmd, timeout=120, env=fmt_env)
    record_fs_op(
        FsOps.JUICEFS_FORMAT,
        duration_ms=(time.monotonic() - fmt_started) * 1000.0,
        outcome="ok" if fmt.returncode == 0 else "fail",
    )
    if fmt.returncode == 0:
        return "ok"
    err = fmt.stderr.strip()
    low = err.lower()
    # Shared volume already initialized (the normal case: E2B/prod formatted
    # it) or a concurrent-format race — the volume is usable.
    if any(m in low for m in ("is not empty", "already exists", "already formatted")):
        log.info("[juicefs] volume already initialized; proceeding to mount")
        return "ok"
    if _classify(err) == "fatal":
        log.warning(
            "[juicefs] permanent error during format",
            meta=_mask_meta(meta_url),
            detail=err[:300],
        )
        return "fatal"
    log.warning(f"[juicefs] format failed (transient; will retry): {err[:300]}")
    return "transient"


def _mount(meta_url: str, mount_path: Path) -> str:
    """Daemonize `juicefs mount` and supervise readiness by polling.

    `juicefs mount --background` forks a detached child + watchdog. Its
    supervisor self-exits non-zero after an internal ~10s mountpoint-ready
    check, but the *detached child keeps initializing* and the mount appears
    seconds later — so we ignore the invocation's exit code and poll the
    mountpoint ourselves for a generous, env-tunable window. (Foreground
    mode is worse: the same 10s check kills the child outright.)

    Returns "ok" | "transient" | "fatal".
    """
    if _is_mounted(mount_path):
        log.info(f"[juicefs] already mounted at {mount_path}")
        return "ok"

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mount_path.mkdir(parents=True, exist_ok=True)
    cmd = [
        "juicefs",
        "mount",
        "--background",
        "--backup-meta=0",  # R2 ListObjects unsorted → auto-backup won't work
        f"--cache-dir={_CACHE_DIR}",
        f"--cache-size={_CACHE_SIZE_MB}",
        f"--max-uploads={_MAX_UPLOADS}",
        f"--buffer-size={_BUFFER_SIZE_MB}",
        meta_url,
        str(mount_path),
    ]
    res = _run(cmd, timeout=40)

    timeout = max(15, settings.JUICEFS_MOUNT_READY_TIMEOUT)
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if _is_mounted(mount_path):
            elapsed_ms = (time.monotonic() - started) * 1000.0
            record_fs_op(FsOps.JUICEFS_MOUNT, duration_ms=elapsed_ms, outcome="ok")
            log.info(
                "[juicefs] mounted",
                mount=str(mount_path),
                elapsed_s=round(elapsed_ms / 1000.0, 1),
            )
            return "ok"
        time.sleep(1)

    elapsed_ms = (time.monotonic() - started) * 1000.0
    detail = (res.stderr or "")[-4000:]
    kind = _classify(detail)  # transient unless an explicit permanent error
    record_fs_op(FsOps.JUICEFS_MOUNT, duration_ms=elapsed_ms, outcome=kind)
    log.warning(
        f"[juicefs] mount not ready within {timeout}s ({kind})",
        meta=_mask_meta(meta_url),
        detail=detail.strip()[:300],
    )
    return kind


def _bootstrap_once() -> str:
    """One full attempt. Returns "ok" | "transient" | "skip" | "fatal"."""
    mount_path = Path(settings.JUICEFS_HOST_MOUNT_PATH)
    if _is_mounted(mount_path):
        log.info(f"[juicefs] mount already healthy at {mount_path}")
        return "ok"
    encrypt_key = _materialize_encryption_key()
    meta_url = _meta_url()
    fmt = _format_if_needed(meta_url, encrypt_key)
    if fmt != "ok":
        return fmt
    return _mount(meta_url, mount_path)


def _bootstrap_loop() -> None:
    """Retry-with-backoff supervisor. Runs in a daemon thread."""
    attempts = max(1, settings.JUICEFS_BOOTSTRAP_MAX_ATTEMPTS)
    base_backoff = max(1, settings.JUICEFS_BOOTSTRAP_RETRY_BACKOFF)
    for attempt in range(1, attempts + 1):
        try:
            result = _bootstrap_once()
        except Exception as e:  # noqa: BLE001 - never let the thread die silently
            log.warning(f"[juicefs] bootstrap attempt errored: {e}")
            result = "transient"
        if result in ("ok", "skip", "fatal"):
            if result == "fatal":
                log.warning(
                    "[juicefs] bootstrap gave up (non-transient failure); "
                    "storage helpers will soft-fail until reconfigured"
                )
            return
        if attempt < attempts:
            delay = min(base_backoff * (2 ** (attempt - 1)), 15)
            log.info(
                "[juicefs] transient mount failure; backing off",
                attempt=attempt,
                of=attempts,
                retry_in_s=delay,
            )
            time.sleep(delay)
    log.warning(
        f"[juicefs] mount still unavailable after {attempts} attempts; "
        "storage helpers will soft-fail (next app start retries)"
    )


@lazy_provider(
    name="juicefs_mount",
    strategy=MissingKeyStrategy.SILENT,
)
async def init_juicefs_mount() -> str:
    """Kick off the JuiceFS mount in the background; return immediately.

    Startup is never blocked on the mount: a daemon thread formats (if
    needed) and mounts with retry/backoff while the app serves traffic. The
    storage helpers raise `JuiceFSUnavailable` until `/mnt/jfs` converges,
    which every caller already treats as a soft-fail.
    """
    global _bootstrap_thread

    if shutil.which("juicefs") is None:
        log.warning("[juicefs] CLI not found on PATH — skipping bootstrap")
        return settings.JUICEFS_HOST_MOUNT_PATH

    missing = _missing_settings()
    if missing:
        log.info("[juicefs] skipping bootstrap; missing settings: " + ", ".join(missing))
        return settings.JUICEFS_HOST_MOUNT_PATH

    with _bootstrap_lock:
        if _bootstrap_thread is not None and _bootstrap_thread.is_alive():
            return settings.JUICEFS_HOST_MOUNT_PATH
        if _is_mounted(Path(settings.JUICEFS_HOST_MOUNT_PATH)):
            log.info("[juicefs] mount already healthy")
            return settings.JUICEFS_HOST_MOUNT_PATH
        _bootstrap_thread = threading.Thread(
            target=_bootstrap_loop,
            name="juicefs-bootstrap",
            daemon=True,
        )
        _bootstrap_thread.start()

    # Yield control so the provider returns promptly without blocking startup.
    await asyncio.sleep(0)
    return settings.JUICEFS_HOST_MOUNT_PATH
