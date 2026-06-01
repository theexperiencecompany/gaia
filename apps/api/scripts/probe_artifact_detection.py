#!/usr/bin/env python3
"""Phase 0 gate — empirically pick the artifact-detection mechanism.

This is an inline runnable probe, NOT a pytest (we don't want it in CI). It
acquires a real E2B sandbox for a test user, opens an E2B `watch_dir` stream
on `/workspace/sessions`, and runs a four-case matrix that tells us whether
the native watcher catches every write path we care about (tool writes, bash
writes, background-process writes, cross-mount host writes).

It prints a structured verdict to stdout:

    {"primary": "watch_dir" | "accesslog", "evidence": {...}}

Paste that verdict into the Phase 3 implementation PR description. The verdict
drives the `ARTIFACT_DETECTION_MODE` setting.

Decision matrix (see .agents/plans/workspace-v2.md Phase 0):
  * all 4 pass                 -> primary = watch_dir
  * 1,2,3 pass but 4 fails     -> primary = watch_dir; cross-mount uploads
                                   need a separate Redis signal (Phase 5)
  * any of 1,2,3 fail          -> primary = accesslog

Usage:
    cd apps/api
    uv run python scripts/probe_artifact_detection.py --user <USER_ID>
    uv run python scripts/probe_artifact_detection.py --user <A> --user-b <B>

Requires E2B_API_KEY + E2B_TEMPLATE_ID and (for case 4) the host JuiceFS
mount at JUICEFS_HOST_MOUNT_PATH.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from app.services.sandbox import acquire_sandbox
from app.services.storage import JuiceFSUnavailable, write_session_file

SESSIONS_WATCH_ROOT = "/workspace/sessions"
PROBE_CONV = "probe"
PROBE_VISIBLE = f"{SESSIONS_WATCH_ROOT}/{PROBE_CONV}/artifacts"

# Event types we accept as "the file appeared / changed".
WRITE_EVENT_TYPES = {"CREATE", "WRITE", "RENAME", "CHMOD"}


def _event_type_name(ev: Any) -> str:
    t = getattr(ev, "type", None)
    return getattr(t, "name", str(t))


async def _wait_for(queue: asyncio.Queue[Any], suffix: str, timeout: float) -> dict[str, Any]:
    """Drain events until one whose name ends with `suffix`, or time out."""
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"passed": False, "seen": seen, "matched": None}
        try:
            ev = await asyncio.wait_for(queue.get(), timeout=remaining)
        except TimeoutError:
            return {"passed": False, "seen": seen, "matched": None}
        name = getattr(ev, "name", "")
        etype = _event_type_name(ev)
        seen.append(f"{etype}:{name}")
        if name.endswith(suffix) and etype in WRITE_EVENT_TYPES:
            return {"passed": True, "seen": seen, "matched": f"{etype}:{name}"}


async def _run_matrix(user_a: str, user_b: str | None) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def on_event(ev: Any) -> None:
        await queue.put(ev)

    async with acquire_sandbox(user_a) as sbx:
        handle = await sbx.files.watch_dir(
            SESSIONS_WATCH_ROOT,
            on_event,
            recursive=True,
            timeout=0,
        )
        try:
            # Case 1: tool-style write via shell (mkdir + echo).
            await sbx.commands.run(
                f"mkdir -p {PROBE_VISIBLE} && echo hi > {PROBE_VISIBLE}/a.md",
                timeout=15,
            )
            evidence["case1_shell_write"] = await _wait_for(queue, "a.md", 3.0)

            # Case 2: background-process write (proves detached writes caught).
            t0 = time.monotonic()
            await sbx.commands.run(
                f"nohup bash -c 'sleep 2 && echo late > {PROBE_VISIBLE}/b.md' >/dev/null 2>&1 &",
                timeout=10,
            )
            r2 = await _wait_for(queue, "b.md", 8.0)
            r2["latency_s"] = round(time.monotonic() - t0, 2)
            evidence["case2_background_write"] = r2

            # Case 3: non-shell writer (python open().write()).
            await sbx.commands.run(
                f'python3 -c \'open("{PROBE_VISIBLE}/c.md","w").write("hi")\'',
                timeout=15,
            )
            evidence["case3_python_write"] = await _wait_for(queue, "c.md", 5.0)

            # Case 4: cross-mount host write into user_a's JuiceFS prefix.
            if user_b:
                # Hold a second user's sandbox to mirror realistic concurrent
                # state while the host writes cross-mount.
                async with acquire_sandbox(user_b):
                    pass
            try:
                await write_session_file(
                    user_id=user_a,
                    conversation_id=PROBE_CONV,
                    relative_path="artifacts/d.md",
                    content="hi",
                )
                evidence["case4_cross_mount"] = await _wait_for(queue, "d.md", 5.0)
            except JuiceFSUnavailable as e:
                evidence["case4_cross_mount"] = {
                    "passed": False,
                    "skipped": f"host JuiceFS mount unavailable: {e}",
                }
        finally:
            with_stop = getattr(handle, "stop", None)
            if with_stop is not None:
                try:
                    await handle.stop()
                except Exception as e:  # noqa: BLE001
                    evidence["watcher_stop_error"] = str(e)

    return evidence


def _verdict(evidence: dict[str, Any]) -> dict[str, Any]:
    def passed(key: str) -> bool:
        return bool(evidence.get(key, {}).get("passed"))

    core_ok = (
        passed("case1_shell_write")
        and passed("case2_background_write")
        and passed("case3_python_write")
    )
    cross_ok = passed("case4_cross_mount")

    if core_ok:
        primary = "watch_dir"
        note = (
            "all four passed"
            if cross_ok
            else "cross-mount (case 4) failed — host-side uploads must "
            "publish to Redis directly (Phase 5), not rely on the watcher"
        )
    else:
        primary = "accesslog"
        note = (
            "one of the core write paths (case 1/2/3) was not caught by "
            "watch_dir — fall back to JuiceFS .accesslog parsing"
        )
    return {"primary": primary, "note": note, "evidence": evidence}


async def main_async(args: argparse.Namespace) -> int:
    try:
        evidence = await _run_matrix(args.user, args.user_b)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"primary": "unknown", "error": str(e)}, indent=2))
        return 1
    print(json.dumps(_verdict(evidence), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="Test user_id (gets sandbox A)")
    parser.add_argument(
        "--user-b",
        dest="user_b",
        default=None,
        help="Optional second user_id for the concurrent-state leg of case 4",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
