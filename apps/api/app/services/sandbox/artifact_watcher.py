"""Per-sandbox artifact watcher.

Watches a user's `/workspace/sessions/*/artifacts/` trees inside their E2B
sandbox and publishes change events to the Redis channel `artifacts:{user_id}`.
The chat stream subscribes to that channel and forwards matching events to the
browser as `artifact_data` tool chunks, so anything the agent drops into
`artifacts/` shows up in the chat UI within ~1-2s — including writes from
bash, background processes, and non-shell writers, not just the `write` tool.

Two interchangeable detection mechanisms behind one interface (the active one
is decided empirically in Phase 0 and pinned via `ARTIFACT_DETECTION_MODE`):

* ``watch_dir`` — E2B envd's native recursive directory watch. Low latency,
  path-accurate. Primary.
* ``accesslog`` — tail JuiceFS's FUSE-native ``/workspace/.accesslog``. Every
  FS op streams through it (so FUSE-on-inotify limitations don't apply); on
  any mutating op we debounce-rescan the host-side `artifacts/` dirs and
  diff against the last snapshot. Robust fallback.

The host-side JuiceFS mount is authoritative for file contents/metadata
(zero-R2 PG reads); the sandbox-side stream is only a latency optimization.
The Phase 6 `GET /sessions/{conv}/artifacts` endpoint is the defense-in-depth
recovery path for any missed event. The wire contract lives in
`app.services.artifact_events`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Literal

from app.agents.workspace.paths import (
    SESSIONS_DIRNAME,
    WORKSPACE_ROOT,
    MountRole,
    classify,
    session_artifacts,
)
from app.config.settings import settings
from app.services.artifact_events import (
    publish_artifact_event,
    remove_event,
    upsert_event,
)
from app.services.storage import (
    FsOps,
    JuiceFSUnavailable,
    fs_timer,
    list_artifacts,
    list_session_ids,
    stat_artifact,
)
from shared.py.wide_events import log

SESSIONS_WATCH_ROOT = f"{WORKSPACE_ROOT}/{SESSIONS_DIRNAME}"
# `.accesslog` is a JuiceFS *mount-root* virtual file. mount_juicefs.sh mounts
# JuiceFS at /mnt/jfs and bind-mounts users/<uid> -> /workspace, so the
# accesslog lives at /mnt/jfs/.accesslog (NOT /workspace/.accesslog, which is
# just a nonexistent path under the bound user prefix). It is root-owned
# (mounted by mount.sh under user="root"), so reads need root — we drive them
# through `commands.run(user="root")` so the sandbox user never needs sudo.
SANDBOX_JFS_MOUNT = "/mnt/jfs"
ACCESSLOG_PATH = f"{SANDBOX_JFS_MOUNT}/.accesslog"
_TMP_SUFFIX = ".gaia-tmp"

# accesslog ops that can change what's visible. JuiceFS .accesslog lines look
# like: "<ts> [uid:..,gid:..,pid:..] write (12345,4096,0): OK <0.000123>".
_ACCESSLOG_MUTATING_OPS = (
    "write",
    "create",
    "mkdir",
    "rename",
    "unlink",
    "rmdir",
    "truncate",
    "fallocate",
    "copy_file_range",
    "link",
    "setattr",
)
_ACCESSLOG_DEBOUNCE_SECONDS = 0.7

DetectionMode = Literal["watch_dir", "accesslog"]


def _strip_artifacts_prefix(abs_path: str, conv_id: str) -> str:
    """`/workspace/sessions/{c}/artifacts/a/b.md` -> `a/b.md`."""
    root = session_artifacts(conv_id) + "/"
    if abs_path.startswith(root):
        return abs_path[len(root) :]
    return abs_path.rsplit("/", 1)[-1]


class ArtifactWatcher:
    """One instance per pooled sandbox. Owned by `PooledSandbox.watcher`."""

    def __init__(self, user_id: str, sandbox: Any) -> None:
        self.user_id = user_id
        self.sandbox = sandbox
        self._mode: DetectionMode = settings.ARTIFACT_DETECTION_MODE
        self._handle: Any = None
        self._stopped = True
        # per-conv snapshot {rel_path: (size, mtime)} for diffing
        self._snapshots: dict[str, dict[str, tuple[int, float]]] = {}
        self._rescan_task: asyncio.Task[None] | None = None

    # -- public surface ---------------------------------------------------

    async def start(self) -> None:
        if not self._stopped:
            return
        try:
            if self._mode == "accesslog":
                await self._start_accesslog()
            else:
                await self._start_watch_dir()
            self._stopped = False
            log.info(
                "[artifact-watcher] started",
                user_id=self.user_id,
                mode=self._mode,
            )
        except Exception as e:
            # Watcher is a latency optimization; never block sandbox acquire.
            self._stopped = True
            log.warning(
                "[artifact-watcher] start failed",
                user_id=self.user_id,
                mode=self._mode,
                error=str(e),
            )

    async def stop(self) -> None:
        self._stopped = True
        if self._rescan_task is not None and not self._rescan_task.done():
            self._rescan_task.cancel()
        self._rescan_task = None
        handle, self._handle = self._handle, None
        if handle is None:
            return
        if self._mode == "accesslog":
            kill = getattr(handle, "kill", None)
            if kill is not None:
                with contextlib.suppress(Exception):
                    await kill()
            with contextlib.suppress(Exception):
                await self.sandbox.commands.run(
                    f"pkill -f 'tail -n0 -F {ACCESSLOG_PATH}'",
                    timeout=5,
                    user="root",
                )
        else:
            stop = getattr(handle, "stop", None)
            if stop is not None:
                with contextlib.suppress(Exception):
                    await handle.stop()

    def is_alive(self) -> bool:
        return not self._stopped and self._handle is not None

    # -- watch_dir mode ---------------------------------------------------

    async def _start_watch_dir(self) -> None:
        # watch_dir errors if the path doesn't exist yet; sessions are created
        # lazily on first chat message, so make the root eagerly.
        with contextlib.suppress(Exception):
            await self.sandbox.commands.run(f"mkdir -p {SESSIONS_WATCH_ROOT}", timeout=10)
        self._handle = await self.sandbox.files.watch_dir(
            SESSIONS_WATCH_ROOT,
            self._on_fs_event,
            on_exit=self._on_watch_exit,
            recursive=True,
            timeout=0,
        )

    def _on_watch_exit(self, _exc: Exception | None = None) -> None:
        # Stream died (envd restart / pause). Mark dead so the next acquire
        # transparently reopens it.
        self._stopped = True
        self._handle = None

    async def _on_fs_event(self, ev: Any) -> None:
        try:
            name = getattr(ev, "name", "") or ""
            abs_path = f"{SESSIONS_WATCH_ROOT}/{name}"
            if abs_path.endswith(_TMP_SUFFIX):
                return
            role, conv = classify(abs_path)
            if role != MountRole.ARTIFACTS or conv is None:
                return
            etype = getattr(getattr(ev, "type", None), "name", "")
            rel = _strip_artifacts_prefix(abs_path, conv)
            if not rel or rel.endswith("/"):
                return
            if etype in ("REMOVE", "RENAME"):
                await publish_artifact_event(self.user_id, remove_event(conv, rel))
                return
            info = await stat_artifact(self.user_id, conv, rel)
            if info is None:
                return
            await publish_artifact_event(self.user_id, upsert_event(conv, info))
        except JuiceFSUnavailable:
            return
        except Exception as e:
            log.debug(f"[artifact-watcher] event dispatch failed: {e}")

    # -- accesslog mode ---------------------------------------------------

    async def _start_accesslog(self) -> None:
        # `user="root"`: mount.sh creates the JuiceFS mount and its root-only
        # `.accesslog` as root, so we have to read it as root. We drive that
        # through envd's `user=` parameter instead of sudo — the sandbox user
        # has no sudo capability (template removes them from the `sudo` group).
        self._handle = await self.sandbox.commands.run(
            f"tail -n0 -F {ACCESSLOG_PATH}",
            background=True,
            on_stdout=self._on_accesslog_line,
            timeout=0,
            user="root",
        )

    def _on_accesslog_line(self, line: str) -> None:
        if not line:
            return
        lowered = line.lower()
        if not any(op in lowered for op in _ACCESSLOG_MUTATING_OPS):
            return
        self._schedule_rescan()

    def _schedule_rescan(self) -> None:
        if self._rescan_task is not None and not self._rescan_task.done():
            return  # a rescan is already pending; it'll pick up the change
        self._rescan_task = asyncio.create_task(self._debounced_rescan())

    async def _debounced_rescan(self) -> None:
        try:
            await asyncio.sleep(_ACCESSLOG_DEBOUNCE_SECONDS)
            await self._rescan_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug(f"[artifact-watcher] rescan failed: {e}")

    async def _rescan_all(self) -> None:
        async with fs_timer(FsOps.WATCHER_RESCAN):
            try:
                conv_ids = await list_session_ids(self.user_id)
            except JuiceFSUnavailable:
                return
            await self._rescan_each(conv_ids)

    async def _rescan_each(self, conv_ids: list[str]) -> None:
        for conv in conv_ids:
            try:
                infos = await list_artifacts(self.user_id, conv)
            except JuiceFSUnavailable:
                return
            except Exception as exc:
                log.debug(
                    "artifact_watcher.rescan_skipped",
                    user_id=self.user_id,
                    conv=conv,
                    error=str(exc),
                )
                continue
            prev = self._snapshots.get(conv, {})
            current: dict[str, tuple[int, float]] = {}
            for info in infos:
                current[info.path] = (info.size_bytes, info.mtime)
                if prev.get(info.path) != (info.size_bytes, info.mtime):
                    await publish_artifact_event(self.user_id, upsert_event(conv, info))
            for gone in prev.keys() - current.keys():
                await publish_artifact_event(self.user_id, remove_event(conv, gone))
            self._snapshots[conv] = current


async def start_watcher_for(user_id: str, sandbox: Any) -> ArtifactWatcher:
    """Construct + start a watcher for a freshly acquired sandbox."""
    watcher = ArtifactWatcher(user_id, sandbox)
    await watcher.start()
    return watcher
