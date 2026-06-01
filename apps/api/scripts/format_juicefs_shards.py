#!/usr/bin/env python3
"""Format JuiceFS shards against R2.

Runs `juicefs format` once per shard, pointing each at its own PostgreSQL
metadata database. The `gaia-workspaces` R2 bucket is shared across shards;
JuiceFS distributes objects via its own chunk-hash prefix scheme.

Usage:
    cd apps/api
    uv run python scripts/format_juicefs_shards.py --shards 1
    uv run python scripts/format_juicefs_shards.py --shards 16 --dry-run

Required env (mirrors apps/api/app/config/settings.py):
    R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY, R2_SECRET_KEY
    JUICEFS_META_URL_TEMPLATE     (must contain `{shard}`)
    JFS_ENCRYPTION_KEY            (optional — full RSA-4096 PEM; if set, written
                                   to a temp file and passed to `juicefs format`)
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile


def required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


@contextmanager
def _encryption_key_file() -> Iterator[str | None]:
    """Materialize JFS_ENCRYPTION_KEY (PEM content in env) to a temp file."""
    pem = os.environ.get("JFS_ENCRYPTION_KEY") or ""
    if not pem.strip():
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="jfs-master-", suffix=".pem")
    pem_path = Path(path)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(pem if pem.endswith("\n") else pem + "\n")
        pem_path.chmod(0o600)
        yield path
    finally:
        try:
            pem_path.unlink()
        except OSError:
            pass


def format_shard(shard: int, encrypt_key_path: str | None, dry_run: bool = False) -> None:
    account = required("R2_ACCOUNT_ID")
    bucket = required("R2_BUCKET")
    access_key = required("R2_ACCESS_KEY")
    secret_key = required("R2_SECRET_KEY")
    meta_template = required("JUICEFS_META_URL_TEMPLATE")

    meta_url = meta_template.replace("{shard}", str(shard))
    bucket_url = f"https://{account}.r2.cloudflarestorage.com/{bucket}"
    name = f"gaia-{shard}"

    # R2 credentials are passed via env (juicefs reads AWS_ACCESS_KEY_ID /
    # AWS_SECRET_ACCESS_KEY when --access-key/--secret-key are absent), so
    # they do not appear in argv that `ps auxww` could expose during the
    # ~30s format window.
    cmd = [
        "juicefs",
        "format",
        "--storage",
        "s3",
        "--bucket",
        bucket_url,
        "--shards",
        "16",  # Always 16 chunk-distribution shards regardless of FS count
    ]
    if encrypt_key_path:
        cmd.extend(["--encrypt-rsa-key", encrypt_key_path])
    cmd.extend([meta_url, name])

    pretty = " ".join(shlex.quote(c) for c in cmd)
    if dry_run:
        print(f"# Would run (with AWS_ACCESS_KEY_ID/SECRET in env):\n{pretty}")
        return
    print(f"$ {pretty}", file=sys.stderr)
    child_env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": access_key,
        "AWS_SECRET_ACCESS_KEY": secret_key,
    }
    subprocess.run(cmd, check=True, env=child_env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, default=1, help="Number of shards to format")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")

    with _encryption_key_file() as key_path:
        for shard in range(args.shards):
            format_shard(shard, encrypt_key_path=key_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
