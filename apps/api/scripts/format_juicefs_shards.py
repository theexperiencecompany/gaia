#!/usr/bin/env python3
"""Format JuiceFS shards against R2.

Runs `juicefs format` once per shard, pointing each at its own metadata engine
(Redis DB in prod, PostgreSQL database elsewhere) via JUICEFS_META_URL_TEMPLATE.
The R2 bucket is shared across shards; JuiceFS distributes objects via its own
chunk-hash prefix scheme, which is why `--shards 16` below needs no `%d` in the
bucket name.

Usage:
    cd apps/api
    uv run python scripts/format_juicefs_shards.py --shards 1
    uv run python scripts/format_juicefs_shards.py --shards 16 --dry-run

Secrets come from Infisical (same bootstrap as payment_setup.py), so no env
plumbing is needed to run this locally — only the `juicefs` binary on PATH.
Values already in the environment take precedence, so a local `.env` or an
explicit export still wins.

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

# Must precede the `app.*` import so the script works from any cwd.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.secrets import (  # noqa: E402
    InfisicalConfigError,
    inject_infisical_secrets,
)


def required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise SystemExit(f"Missing required env var: {name}")
    return val


def _mask_meta(url: str) -> str:
    """Redact the password from a meta URL so it can be printed."""
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


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


def format_shard(
    shard: int,
    encrypt_key_path: str | None,
    name_suffix: str = "",
    dry_run: bool = False,
) -> None:
    account = required("R2_ACCOUNT_ID")
    bucket = required("R2_BUCKET")
    access_key = required("R2_ACCESS_KEY")
    secret_key = required("R2_SECRET_KEY")
    meta_template = required("JUICEFS_META_URL_TEMPLATE")

    meta_url = meta_template.replace("{shard}", str(shard))
    bucket_url = f"https://{account}.r2.cloudflarestorage.com/{bucket}"
    # The volume name is the object-store prefix (<bucket>/<name>/), so juicefs
    # refuses to format when that prefix already holds blocks. Re-formatting
    # after losing the metadata engine therefore needs a fresh name — the old
    # blocks stay readable for a later restore instead of being overwritten.
    name = f"gaia-{shard}{name_suffix}"

    # R2 credentials are passed via env (juicefs reads AWS_ACCESS_KEY_ID /
    # AWS_SECRET_ACCESS_KEY when --access-key/--secret-key are absent), so
    # they do not appear in argv that `ps auxww` could expose during the
    # ~30s format window.
    # No --shards: it splits blocks across N *buckets* and requires a `%d` in the
    # bucket name to generate the endpoints. With a single bucket juicefs exits
    # with "can not generate different endpoint", so `--shards 16` here never
    # worked against gaia-workspaces — it only appeared to because the caller in
    # docker-entrypoint.sh swallows a failed format with `|| echo`.
    cmd = [
        "juicefs",
        "format",
        "--storage",
        "s3",
        "--bucket",
        bucket_url,
    ]
    if encrypt_key_path:
        cmd.extend(["--encrypt-rsa-key", encrypt_key_path])
    cmd.extend([meta_url, name])

    # The meta URL carries the metadata-engine password; mask it so it never
    # reaches a terminal, a CI log, or Loki.
    pretty = " ".join(shlex.quote(_mask_meta(c)) for c in cmd)
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
    parser.add_argument(
        "--name-suffix",
        default="",
        help="Appended to the volume name, e.g. '-v2' -> gaia-0-v2. Use when "
        "re-formatting against a bucket that still holds a previous volume.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.shards < 1:
        raise SystemExit("--shards must be >= 1")

    # Not fatal on its own: the env may already be populated from a .env or
    # explicit exports. `required()` below is the real gate and names precisely
    # what is missing.
    try:
        inject_infisical_secrets()
    except InfisicalConfigError as exc:
        print(f"[warn] Infisical injection skipped: {exc}", file=sys.stderr)

    with _encryption_key_file() as key_path:
        for shard in range(args.shards):
            format_shard(
                shard,
                encrypt_key_path=key_path,
                name_suffix=args.name_suffix,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
