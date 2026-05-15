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
import contextlib
import os
import shutil
import subprocess  # nosec B404 - JuiceFS CLI invocation
import tempfile
import threading
import time
from pathlib import Path

from shared.py.wide_events import log
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider

_ENCRYPTION_KEY_FILE = Path("/etc/gaia/jfs-master.pem")
_CACHE_DIR = Path("/var/cache/juicefs")
_MOUNT_LOG = _CACHE_DIR / "mount.log"
_CACHE_SIZE_MB = 4096
_BUFFER_SIZE_MB = 600
_MAX_UPLOADS = 20

# Substrings that mark a *transient* meta/network failure worth retrying
# (vs. a permanent misconfiguration). Kept broad on purpose: a spurious retry
# is cheap; giving up on a Neon cold-start is not.
_TRANSIENT_MARKERS = (
    "network is unreachable",
    "no route to host",
    "connection refused",
    "connection reset",
    "i/o timeout",
    "io timeout",
    "deadline exceeded",
    "dial tcp",
    "ping database",
    "is not available",
    "temporary failure in name resolution",
    "tls handshake timeout",
    "the mount point is not ready",
    "eof",
)

# Module state — guards against double-spawn and keeps the long-lived
# foreground `juicefs mount` process from being garbage collected.
_bootstrap_lock = threading.Lock()
_bootstrap_thread: threading.Thread | None = None
_mount_proc: subprocess.Popen[bytes] | None = None


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


def _is_transient(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _TRANSIENT_MARKERS)


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
    os.chmod(target, 0o600)
    return target


def _run(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a short-lived subprocess and capture output for logging."""
    return subprocess.run(  # nosec B603 - argv list, no shell
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _format_if_needed(meta_url: str, encrypt_key: Path | None) -> str:
    """Format the volume if the meta isn't initialized yet.

    Returns "ok" | "transient" | "fatal". Idempotent: an already-formatted
    volume (status==0) or a concurrent-format race is "ok".
    """
    status = _run(["juicefs", "status", meta_url], timeout=20)
    if status.returncode == 0:
        log.info("[juicefs] filesystem already formatted")
        return "ok"
    if _is_transient(status.stderr):
        log.warning(
            "[juicefs] meta unreachable during status; will retry",
            meta=_mask_meta(meta_url),
        )
        return "transient"

    log.info(f"[juicefs] formatting filesystem against {_bucket_url()}")
    cmd: list[str] = [
        "juicefs",
        "format",
        "--storage",
        "s3",
        "--bucket",
        _bucket_url(),
        "--access-key",
        (settings.R2_ACCESS_KEY or "").strip(),
        "--secret-key",
        (settings.R2_SECRET_KEY or "").strip(),
    ]
    if encrypt_key is not None:
        cmd.extend(["--encrypt-rsa-key", str(encrypt_key)])
    cmd.extend([meta_url, "gaia-0"])
    fmt = _run(cmd, timeout=120)
    if fmt.returncode == 0:
        return "ok"
    if _is_transient(fmt.stderr):
        log.warning(
            "[juicefs] meta unreachable during format; will retry",
            meta=_mask_meta(meta_url),
        )
        return "transient"
    # A second replica racing to format gets "already exists" / "not empty";
    # the volume is usable, so treat as success rather than retry forever.
    log.warning(
        f"[juicefs] format returned {fmt.returncode} (treating as ready): "
        f"{fmt.stderr.strip()[:400]}"
    )
    return "ok"


def _spawn_mount(meta_url: str, mount_path: Path) -> subprocess.Popen[bytes]:
    """Start `juicefs mount` in the foreground as a detached child.

    Foreground (no `--background`) so juicefs's 10s self-readiness check
    can't kill an otherwise-fine mount under slow managed-PG meta latency —
    we supervise readiness ourselves. `start_new_session` detaches it so it
    keeps serving for the container's lifetime.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    mount_path.mkdir(parents=True, exist_ok=True)
    cmd = [
        "juicefs",
        "mount",
        "--backup-meta=0",  # R2 ListObjects unsorted → auto-backup won't work
        f"--cache-dir={_CACHE_DIR}",
        f"--cache-size={_CACHE_SIZE_MB}",
        f"--max-uploads={_MAX_UPLOADS}",
        f"--buffer-size={_BUFFER_SIZE_MB}",
        meta_url,
        str(mount_path),
    ]
    logf = _MOUNT_LOG.open("ab")
    return subprocess.Popen(  # nosec B603 - argv list, no shell
        cmd,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _mount(meta_url: str, mount_path: Path) -> str:
    """Mount JuiceFS, supervising readiness ourselves.

    Returns "ok" | "transient" | "fatal".
    """
    global _mount_proc

    if _is_mounted(mount_path):
        log.info(f"[juicefs] already mounted at {mount_path}")
        return "ok"

    timeout = max(15, settings.JUICEFS_MOUNT_READY_TIMEOUT)
    proc = _spawn_mount(meta_url, mount_path)
    _mount_proc = proc

    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if _is_mounted(mount_path):
            log.info(
                "[juicefs] mounted",
                mount=str(mount_path),
                elapsed_s=round(time.monotonic() - started, 1),
            )
            return "ok"  # leave the process running — it IS the FUSE server
        if proc.poll() is not None:
            tail = ""
            try:
                tail = _MOUNT_LOG.read_text(errors="replace")[-600:]
            except OSError:
                pass
            kind = "transient" if _is_transient(tail) else "fatal"
            log.warning(
                f"[juicefs] mount process exited (code {proc.returncode}; {kind})",
                meta=_mask_meta(meta_url),
            )
            return kind
        time.sleep(1)

    # Timed out waiting for readiness — stop the orphan and let the caller
    # decide whether to retry.
    with contextlib.suppress(Exception):
        proc.terminate()
    log.warning(
        f"[juicefs] mount not ready within {timeout}s; will retry",
        mount=str(mount_path),
    )
    return "transient"


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
            delay = min(base_backoff * (2 ** (attempt - 1)), 60)
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
        log.info(
            "[juicefs] skipping bootstrap; missing settings: " + ", ".join(missing)
        )
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
