"""JuiceFS bootstrap — runs at app startup, after Infisical injection.

Why this lives in Python (not the docker entrypoint):
Production secrets are pulled by `inject_infisical_secrets()` during Pydantic
settings load. By that point the bash entrypoint has already exec-ed Python,
so the R2/JuiceFS env vars are only available *inside* the Python process.
This module mounts JuiceFS lazily on first use of `init_juicefs_mount()`.

The mount runs as a subprocess (`juicefs` CLI). If the binary is missing or
required settings aren't populated, the function logs a warning and returns
without raising — the storage helpers treat the missing mount as a soft-fail.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess  # nosec B404 - JuiceFS CLI invocation
import tempfile
from pathlib import Path

from shared.py.wide_events import log
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider

_ENCRYPTION_KEY_FILE = Path("/etc/gaia/jfs-master.pem")
_CACHE_DIR = Path("/var/cache/juicefs")
_FORMAT_SHARDS = "16"  # JuiceFS chunk-distribution shards (separate from FS shard count)
_CACHE_SIZE_MB = 4096
_BUFFER_SIZE_MB = 600
_MAX_UPLOADS = 20


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
        template = "postgres://" + template[len("postgresql://"):]
    return template


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
        # `mountpoint` may not exist on macOS; fall back to a heuristic.
        try:
            return path.is_mount()
        except (AttributeError, OSError):
            return False


def _materialize_encryption_key() -> Path | None:
    """Write the PEM env var to a file if present, return its path."""
    pem = (settings.JFS_ENCRYPTION_KEY or "").strip()
    if not pem:
        return None
    # Prefer the well-known production path; fall back to /tmp in dev when
    # /etc/gaia isn't writable.
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
    """Run a subprocess and capture output for logging."""
    return subprocess.run(  # nosec B603 - argv list, no shell
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _format_if_needed(meta_url: str, encrypt_key: Path | None) -> None:
    """Run `juicefs format` if the FS isn't formatted yet. Idempotent.

    Notes on choices:
    - No `--shards`: requires a `%d` placeholder per-shard bucket URL which
      we don't use; single bucket is fine at our scale.
    - No `--encrypt-rsa-key` by default: JuiceFS stores the PEM in its
      settings table which is varchar(4096); RSA-4096 overflows. R2 still
      encrypts at rest. Encryption can be re-enabled later with RSA-2048.
    """
    status = _run(["juicefs", "status", meta_url], timeout=15)
    if status.returncode == 0:
        log.info("[juicefs] filesystem already formatted")
        return

    log.info(f"[juicefs] formatting filesystem against {_bucket_url()}")
    cmd: list[str] = [
        "juicefs",
        "format",
        "--storage", "s3",
        "--bucket", _bucket_url(),
        "--access-key", (settings.R2_ACCESS_KEY or "").strip(),
        "--secret-key", (settings.R2_SECRET_KEY or "").strip(),
    ]
    if encrypt_key is not None:
        cmd.extend(["--encrypt-rsa-key", str(encrypt_key)])
    cmd.extend([meta_url, "gaia-0"])
    fmt = _run(cmd, timeout=120)
    if fmt.returncode != 0:
        # Concurrent replicas racing to format will get a "already exists"
        # error from the second invocation — treat as success.
        log.warning(
            f"[juicefs] format returned {fmt.returncode}: {fmt.stderr.strip()}"
        )


def _mount(meta_url: str, mount_path: Path) -> None:
    """Mount JuiceFS in background. No-op if already mounted."""
    if _is_mounted(mount_path):
        log.info(f"[juicefs] already mounted at {mount_path}")
        return
    mount_path.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "juicefs",
        "mount",
        "--backup-meta=0",  # R2 ListObjects unsorted → JuiceFS auto-backup won't work
        f"--cache-dir={_CACHE_DIR}",
        f"--cache-size={_CACHE_SIZE_MB}",
        f"--max-uploads={_MAX_UPLOADS}",
        f"--buffer-size={_BUFFER_SIZE_MB}",
        "--background",
        meta_url,
        str(mount_path),
    ]
    mount = _run(cmd, timeout=60)
    if mount.returncode != 0:
        log.warning(
            f"[juicefs] mount returned {mount.returncode}: {mount.stderr.strip()}"
        )
        return
    log.info(f"[juicefs] mounted at {mount_path}")


def _bootstrap_sync() -> None:
    """The blocking work that runs once at startup."""
    if shutil.which("juicefs") is None:
        log.warning("[juicefs] CLI not found on PATH — skipping bootstrap")
        return

    missing = _missing_settings()
    if missing:
        log.info(
            "[juicefs] skipping bootstrap; missing settings: " + ", ".join(missing)
        )
        return

    mount_path = Path(settings.JUICEFS_HOST_MOUNT_PATH)
    if _is_mounted(mount_path):
        log.info(f"[juicefs] mount already healthy at {mount_path}")
        return

    encrypt_key = _materialize_encryption_key()
    meta_url = _meta_url()
    _format_if_needed(meta_url, encrypt_key)
    _mount(meta_url, mount_path)


@lazy_provider(
    name="juicefs_mount",
    strategy=MissingKeyStrategy.SILENT,
)
async def init_juicefs_mount() -> str:
    """Format (if needed) and mount JuiceFS at `JUICEFS_HOST_MOUNT_PATH`.

    Subprocess calls are blocking so we run them in a thread to avoid stalling
    the event loop. Returns the mount path as a sentinel so the lazy-provider
    machinery has something to cache.
    """
    await asyncio.to_thread(_bootstrap_sync)
    return settings.JUICEFS_HOST_MOUNT_PATH
