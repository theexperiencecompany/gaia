"""Smoke-test a (re)built gaia-coder E2B template's JuiceFS mounts.

Creates a real E2B sandbox from ``settings.E2B_TEMPLATE_ID``, seeds the per-user
subtrees (what the dockered API does host-side via ``ensure_user_workspace``),
runs the PRODUCTION mount script, then verifies the ``/_system`` bake, the
JuiceFS mounts and their flags, a simulated session's folders, and the graceful
unmount path. Kills the sandbox at the end.

Run (from apps/api):
    uv run python scripts/verify_sandbox_mounts.py

Requires Infisical creds in apps/api/.env (E2B + JuiceFS meta + R2 are pulled
from Infisical). This is a manual dev tool — it provisions a billable sandbox
and issues JuiceFS metadata requests; do not run it in CI.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import uuid

from dotenv import load_dotenv
from e2b import AsyncSandbox

# Make `app.*` importable when run directly (sys.path[0] is the scripts/ dir).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))
load_dotenv(_BACKEND_ROOT / ".env")

from app.config.secrets import inject_infisical_secrets  # noqa: E402

inject_infisical_secrets()

from app.config.settings import settings  # noqa: E402
from app.services.sandbox.lifecycle import (  # noqa: E402
    _mount_env,
    _release_juicefs_sessions,
    _run_mount_script,
)
from app.services.sandbox.shard_router import shard_for  # noqa: E402

TEST_USER = f"verify-{uuid.uuid4().hex[:8]}"
CONV = f"conv-{uuid.uuid4().hex[:8]}"

# Seed the per-user subtrees via a brief full-volume mount inside the sandbox —
# the standalone equivalent of the host-side ensure_user_workspace, so mount.sh's
# --subdir mounts have a target. The dockered API does this host-side instead.
SEED = """
set -e
export AWS_ACCESS_KEY_ID="$JFS_R2_KEY"
export AWS_SECRET_ACCESS_KEY="$JFS_R2_SECRET"
mkdir -p /mnt/seed
setsid nohup juicefs mount --no-bgjob --backup-meta=0 "$JFS_META_URL" /mnt/seed </dev/null >/var/log/seed.log 2>&1 &
for _ in $(seq 1 60); do mountpoint -q /mnt/seed && break; sleep 1; done
mountpoint -q /mnt/seed || { echo "SEED MOUNT FAILED"; tail -20 /var/log/seed.log; exit 1; }
mkdir -p "/mnt/seed/users/$USER_ID" "/mnt/seed/skills/$USER_ID"
juicefs umount /mnt/seed 2>/dev/null || umount -l /mnt/seed
echo "SEED OK"
"""

_results: list[bool] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    _results.append(ok)
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""), flush=True
    )


async def sh(sbx, cmd: str, *, user: str = "user", timeout: int = 60, envs: dict | None = None):
    """Run a command without raising; return (exit_code, stdout, stderr)."""
    try:
        r = await sbx.commands.run(cmd, user=user, timeout=timeout, envs=envs or {})
        return 0, (r.stdout or ""), (r.stderr or "")
    except Exception as e:  # noqa: BLE001 - probe helper, surface code/output
        return (
            int(getattr(e, "exit_code", 1) or 1),
            getattr(e, "stdout", "") or "",
            getattr(e, "stderr", "") or str(e),
        )


async def main() -> int:
    print(f"\n== verify template {settings.E2B_TEMPLATE_ID}  user={TEST_USER}  conv={CONV} ==\n")
    env = _mount_env(TEST_USER, shard_for(TEST_USER))

    print("Creating sandbox...", flush=True)
    sbx = await AsyncSandbox.create(template=settings.E2B_TEMPLATE_ID, timeout=600)
    print(f"  sandbox_id={getattr(sbx, 'sandbox_id', '?')}\n", flush=True)
    try:
        code, out, _ = await sh(sbx, "ls /etc/gaia/system 2>/dev/null | head", user="root")
        check(
            code == 0 and bool(out.strip()),
            "/etc/gaia/system baked in template",
            out.replace("\n", " ")[:80],
        )

        print("\nSeeding /users + /skills subtrees...", flush=True)
        code, out, err = await sh(sbx, SEED, user="root", timeout=150, envs=env)
        check(
            code == 0 and "SEED OK" in out, "seed user/skills subtrees", (err or out).strip()[:120]
        )

        print("\nRunning production mount.sh...", flush=True)
        try:
            await _run_mount_script(sbx, env)
            check(True, "mount.sh ran (exit 0)")
        except Exception as e:  # noqa: BLE001
            check(False, "mount.sh ran (exit 0)", str(e)[:160])

        print("\nVerifying mounts...", flush=True)
        code, _, _ = await sh(sbx, "mountpoint -q /workspace", user="root")
        check(code == 0, "/workspace is a mountpoint (JuiceFS, not ephemeral)")

        code, out, _ = await sh(sbx, "stat -f -c %T /workspace 2>/dev/null", user="root")
        check("fuse" in out.lower(), "/workspace is FUSE-backed", out.strip())

        code, _, _ = await sh(sbx, "mountpoint -q /workspace/.system", user="root")
        _, out2, _ = await sh(sbx, "ls /workspace/.system 2>/dev/null | head", user="root")
        check(
            code == 0 and bool(out2.strip()),
            "/workspace/.system bound + populated",
            out2.replace("\n", " ")[:80],
        )

        code, _, _ = await sh(sbx, "mountpoint -q /workspace/skills", user="root")
        check(code == 0, "/workspace/skills mounted (JuiceFS RO)")

        code, _, _ = await sh(sbx, "touch /workspace/.system/__rotest 2>&1", user="user")
        check(code != 0, "/workspace/.system is read-only")

        # Count distinct JuiceFS FUSE devices (MAJ:MIN), so bind mounts of a
        # JuiceFS mount aren't double-counted. Expect 2: user RW + skills RO.
        code, out, _ = await sh(sbx, "findmnt -rn -t fuse.juicefs -o MAJ:MIN || true", user="root")
        devs = sorted({d for d in out.split() if d})
        check(
            len(devs) == 2,
            f"JuiceFS daemons (distinct FUSE devices) == 2 (got {len(devs)})",
            " ".join(devs),
        )

        code, out, _ = await sh(
            sbx,
            "for p in $(pgrep -f 'juicefs .*mount'); do tr '\\0' ' ' < /proc/$p/cmdline; echo; done",
            user="root",
        )
        cmd_rw = next((ln for ln in out.splitlines() if "/users/" in ln), "")
        cmd_sk = next((ln for ln in out.splitlines() if "/skills/" in ln), "")
        check("--no-bgjob" in cmd_rw, "RW mount has --no-bgjob")
        check("--readdir-cache" in cmd_rw and "--attr-cache" in cmd_rw, "RW mount has cache flags")
        check("--heartbeat" in cmd_rw, "RW mount has --heartbeat")
        check("--read-only" in cmd_sk and "--attr-cache" in cmd_sk, "skills mount RO + cached")

        code, out, _ = await sh(
            sbx,
            "ls -d /workspace/.gaia/runs /workspace/pinned /workspace/settings 2>&1",
            user="root",
        )
        check(
            code == 0,
            "base dirs (.gaia/runs, pinned, settings) present",
            out.replace("\n", " ")[:80],
        )

        print("\nSimulating session folders + file round-trip...", flush=True)
        sess = f"/workspace/sessions/{CONV}"
        mk = (
            f"mkdir -p {sess}/scratch {sess}/artifacts {sess}/user-uploaded && "
            f"echo 'hello-artifact' > {sess}/artifacts/out.txt && "
            f"echo 'scratch-work' > {sess}/scratch/notes.md && "
            f"echo 'uploaded' > {sess}/user-uploaded/data.csv && "
            f"ls -1 {sess}"
        )
        _, out, _ = await sh(sbx, mk, user="user")
        listed = {ln.strip() for ln in out.splitlines() if ln.strip()}
        check(
            {"scratch", "artifacts", "user-uploaded"} <= listed,
            "session has scratch/artifacts/user-uploaded",
            " ".join(sorted(listed)),
        )

        _, out, _ = await sh(sbx, f"cat {sess}/artifacts/out.txt", user="user")
        check(
            out.strip() == "hello-artifact",
            "artifact file content round-trips through JuiceFS",
            out.strip()[:40],
        )

        code, out, _ = await sh(
            sbx, f"sync; stat -c %s {sess}/user-uploaded/data.csv 2>&1", user="user"
        )
        check(
            code == 0 and out.strip().isdigit(),
            "user-uploaded file is stat-able (persisted)",
            out.strip(),
        )

        print("\nExercising graceful unmount...", flush=True)
        await _release_juicefs_sessions(sbx)
        _, out, _ = await sh(sbx, "findmnt -rn -t fuse.juicefs -o TARGET || true", user="root")
        remaining = [t for t in out.split() if t]
        check(
            len(remaining) == 0, "all JuiceFS mounts released on unmount", f"remaining={remaining}"
        )
    finally:
        print("\nKilling sandbox...", flush=True)
        try:
            await sbx.kill()
        except Exception as e:  # noqa: BLE001
            print(f"  kill error: {e}")

    npass = sum(_results)
    print(f"\n== {npass}/{len(_results)} checks passed ==")
    return 0 if npass == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
