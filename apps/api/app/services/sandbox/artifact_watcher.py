"""Per-sandbox artifact watcher.

Watches a user's /workspace/sessions/*/artifacts/ trees inside their E2B
sandbox and publishes change events to the Redis channel artifacts:{user_id},
which the chat stream forwards to the browser within ~1-2s — including bash,
background, and non-shell writes, not just the write tool.

Two interchangeable detection mechanisms behind one interface, picked via
ARTIFACT_DETECTION_MODE: watch_dir (E2B envd's native recursive watch, low
latency, primary) and accesslog (tail JuiceFS's FUSE-native .accesslog, where
every FS op streams through — debounce-rescan + diff on mutation, fallback).

The host-side JuiceFS mount is authoritative for file contents/metadata; the
sandbox-side stream is only a latency optimization. GET /sessions/{conv}/artifacts
is the defense-in-depth recovery path for any missed event.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from typing import Literal

from e2b import AsyncCommandHandle, AsyncSandbox, AsyncWatchHandle, FilesystemEvent

from app.agents.workspace.paths import (
    SESSIONS_DIRNAME,
    WORKSPACE_ROOT,
    MountRole,
    classify,
    session_artifacts,
)
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.sandbox import WORKSPACE_TMP_SUFFIX
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
    session_dir_inodes,
    sessions_root_inode,
    stat_artifact,
)
from shared.py.wide_events import log, log_context, spawn_logged_task

SESSIONS_WATCH_ROOT = f"{WORKSPACE_ROOT}/{SESSIONS_DIRNAME}"
# `.accesslog` is a JuiceFS mount-root virtual file, so it lives at
# /mnt/jfs/.accesslog (not /workspace/.accesslog). It's root-owned; read via
# `commands.run(user="root")` since the sandbox user has no sudo.
SANDBOX_JFS_MOUNT = "/mnt/jfs"
ACCESSLOG_PATH = f"{SANDBOX_JFS_MOUNT}/.accesslog"

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
# Force a full rescan at least this often during ongoing activity, so an op whose
# inode we couldn't map to a conversation can never strand an artifact update.
_ACCESSLOG_FULL_BACKSTOP_SECONDS = 30.0
# Pull op + parenthesized inode args from a line like
# "<ts> [..] write (12345,4096,0): OK <0.000123>" -> op="write",
# args="12345,4096,0" (stops at first ")", so a result tuple is ignored).
_ACCESSLOG_OP_RE = re.compile(r"\]\s+(\w+)\s+\(([^)]*)\)")
_ACCESSLOG_INT_RE = re.compile(r"\d+")

DetectionMode = Literal["watch_dir", "accesslog"]


def _strip_artifacts_prefix(abs_path: str, conv_id: str) -> str:
    """/workspace/sessions/{c}/artifacts/a/b.md -> a/b.md."""
    root = session_artifacts(conv_id) + "/"
    if abs_path.startswith(root):
        return abs_path[len(root) :]
    return abs_path.rsplit("/", 1)[-1]


async def _record_watch_exit(user_id: str, mode: DetectionMode, exc: Exception | None) -> None:
    """One wide event per dead watch stream, with the reason when there is one."""
    async with log_context(
        "sandbox_artifact_watch_exit",
        user={"id": user_id},
        sandbox={"artifact_mode": mode},
    ):
        log.warning(
            f"{LogTag.ARTIFACT_WATCHER} watch stream exited",
            error=str(exc) if exc else None,
            error_type=type(exc).__name__ if exc else None,
        )


class ArtifactWatcher:
    """One instance per pooled sandbox. Owned by PooledSandbox.watcher."""

    def __init__(self, user_id: str, sandbox: AsyncSandbox) -> None:
        self.user_id = user_id
        self.sandbox = sandbox
        self._mode: DetectionMode = settings.ARTIFACT_DETECTION_MODE
        # A watch_dir subscription in "watch_dir" mode, the backgrounded `tail`
        # in "accesslog" mode; None whenever the watcher is stopped or dead.
        self._handle: AsyncWatchHandle | AsyncCommandHandle | None = None
        self._stopped = True
        # per-conv snapshot {rel_path: (size, mtime)} for diffing
        self._snapshots: dict[str, dict[str, tuple[int, float]]] = {}
        self._rescan_task: asyncio.Task[None] | None = None
        # accesslog scoping: map a mutating-op inode -> conv so a rescan hits
        # only the changed session. Populated from each rescan (artifact files +
        # their session/artifacts dir inodes, all from stats the scan already did).
        self._inode_conv: dict[int, str] = {}
        self._sessions_root_ino: int | None = None
        self._dirty_convs: set[str] = set()
        # First rescan is full (seeds the inode map); thereafter scoped, with a
        # periodic full rescan as a backstop so an unmapped op can never strand
        # an artifact update.
        self._need_full_rescan = True
        self._last_full_rescan = 0.0
        # accesslog mode only: watches the background tail handle for exit so
        # is_alive() reflects a dead stream (watch_dir gets this via on_exit).
        self._accesslog_monitor: asyncio.Task[None] | None = None

    # -- public surface ---------------------------------------------------

    async def start(self) -> None:
        """Begin watching the sandbox for artifact changes (accesslog or watch_dir).

        Best-effort: a failure is logged and leaves the watcher stopped — it's a
        latency optimization and must never block sandbox acquisition.
        """
        if not self._stopped:
            return
        try:
            if self._mode == "accesslog":
                await self._start_accesslog()
            else:
                await self._start_watch_dir()
            self._stopped = False
            log.set_ns("sandbox", artifact_mode=self._mode)
            log.info(
                f"{LogTag.ARTIFACT_WATCHER} started",
                user_id=self.user_id,
                mode=self._mode,
            )
        except Exception as e:
            # Watcher is a latency optimization; never block sandbox acquire.
            self._stopped = True
            log.warning(
                f"{LogTag.ARTIFACT_WATCHER} start failed",
                user_id=self.user_id,
                mode=self._mode,
                error=str(e),
            )

    async def stop(self) -> None:
        """Stop watching and tear down the tail/watch handle and rescan tasks."""
        self._stopped = True
        if self._rescan_task is not None and not self._rescan_task.done():
            self._rescan_task.cancel()
        self._rescan_task = None
        if self._accesslog_monitor is not None and not self._accesslog_monitor.done():
            self._accesslog_monitor.cancel()
        self._accesslog_monitor = None
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
        """Return True if the watcher is running with a live underlying handle."""
        return not self._stopped and self._handle is not None

    # -- watch_dir mode ---------------------------------------------------

    async def _start_watch_dir(self) -> None:
        # watch_dir errors if the path doesn't exist yet; sessions are created
        # lazily on first chat message, so make the root eagerly. `make_dir`
        # creates parents and no-ops if it already exists.
        with contextlib.suppress(Exception):
            await self.sandbox.files.make_dir(SESSIONS_WATCH_ROOT)
        self._handle = await self.sandbox.files.watch_dir(
            SESSIONS_WATCH_ROOT,
            self._on_fs_event,
            on_exit=self._on_watch_exit,
            recursive=True,
            timeout=0,
        )

    def _on_watch_exit(self, exc: Exception | None = None) -> None:
        # Stream died (envd restart/pause); mark dead synchronously — envd's
        # callback can't await — so the next acquire reopens it. Previously this
        # failed silently, indistinguishable from a sandbox nobody wrote to.
        self._stopped = True
        self._handle = None
        spawn_logged_task(
            "sandbox_artifact_watch_exit",
            _record_watch_exit(self.user_id, self._mode, exc),
        )

    async def _on_fs_event(self, ev: FilesystemEvent) -> None:
        async with log_context(
            "sandbox_artifact_event",
            user={"id": self.user_id},
            sandbox={"artifact_mode": self._mode},
        ):
            try:
                name = getattr(ev, "name", "") or ""
                abs_path = f"{SESSIONS_WATCH_ROOT}/{name}"
                if abs_path.endswith(WORKSPACE_TMP_SUFFIX):
                    return
                role, conv = classify(abs_path)
                if role != MountRole.ARTIFACTS or conv is None:
                    return
                etype = getattr(getattr(ev, "type", None), "name", "")
                rel = _strip_artifacts_prefix(abs_path, conv)
                if not rel or rel.endswith("/"):
                    return
                log.set(chat={"conversation_id": conv}, file_name=rel, operation=etype)
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
                # Was debug — i.e. below the default level, so an artifact that
                # never reached the chat UI left no record anywhere.
                log.warning(
                    f"{LogTag.ARTIFACT_WATCHER} event dispatch failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

    # -- accesslog mode ---------------------------------------------------

    async def _start_accesslog(self) -> None:
        # `user="root"`: `.accesslog` is root-only, and driven via envd's `user=`
        # param instead of sudo — the sandbox user has no sudo capability
        # (template removes them from the `sudo` group).
        self._handle = await self.sandbox.commands.run(
            f"tail -n0 -F {ACCESSLOG_PATH}",
            background=True,
            on_stdout=self._on_accesslog_line,
            timeout=0,
            user="root",
        )
        self._accesslog_monitor = spawn_logged_task(
            "sandbox_accesslog_watch",
            self._watch_accesslog_exit(self._handle),
            user={"id": self.user_id},
            sandbox={"artifact_mode": self._mode},
        )

    async def _watch_accesslog_exit(self, handle: AsyncCommandHandle) -> None:
        """Mark the watcher dead when the background tail stream ends.

        The tail handle has no exit callback (unlike watch_dir's on_exit), so a
        paused/restarted sandbox would otherwise leave is_alive() returning True
        forever and the next acquire would never reopen the watcher.
        """
        with contextlib.suppress(Exception):
            await handle.wait()
        if self._handle is handle:
            self._stopped = True
            self._handle = None
            log.warning(f"{LogTag.ARTIFACT_WATCHER} accesslog tail stream ended")

    def _on_accesslog_line(self, line: str) -> None:
        """Route a mutating accesslog op to a scoped or full rescan.

        Ops carry inode args, not paths, resolved against the inode->conv map:
        a hit scopes the rescan to that conversation, a sessions-root touch
        means a conv was added/removed (full rescan), and an unmapped inode is
        ignored — the periodic full-rescan backstop still catches it.
        """
        m = _ACCESSLOG_OP_RE.search(line)
        if m is None:
            return
        op, args = m.group(1), m.group(2)
        if op not in _ACCESSLOG_MUTATING_OPS:
            return
        inodes = {int(n) for n in _ACCESSLOG_INT_RE.findall(args)}
        if not self._inode_conv:
            # Map not seeded yet — first rescan must be full.
            self._need_full_rescan = True
        elif self._sessions_root_ino is not None and self._sessions_root_ino in inodes:
            self._need_full_rescan = True  # session dir created/removed
        else:
            self._dirty_convs |= {self._inode_conv[i] for i in inodes if i in self._inode_conv}
        self._schedule_rescan()

    def _schedule_rescan(self) -> None:
        if self._rescan_task is not None and not self._rescan_task.done():
            return  # a rescan is already pending; it'll pick up the change
        self._rescan_task = spawn_logged_task(
            "sandbox_artifact_rescan",
            self._debounced_rescan(),
            user={"id": self.user_id},
            sandbox={"artifact_mode": self._mode},
        )

    async def _debounced_rescan(self) -> None:
        try:
            await asyncio.sleep(_ACCESSLOG_DEBOUNCE_SECONDS)
            now = time.monotonic()
            due_full = self._need_full_rescan or (
                now - self._last_full_rescan >= _ACCESSLOG_FULL_BACKSTOP_SECONDS
            )
            if due_full:
                self._need_full_rescan = False
                self._dirty_convs.clear()
                self._last_full_rescan = now
                await self._rescan_all()
            elif self._dirty_convs:
                convs = sorted(self._dirty_convs)
                self._dirty_convs.clear()
                async with fs_timer(FsOps.WATCHER_RESCAN):
                    await self._rescan_each(convs)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Was debug — a rescan that never ran is an artifact the user never
            # sees, so it has to survive on the event.
            log.warning(
                f"{LogTag.ARTIFACT_WATCHER} rescan failed",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def _rescan_all(self) -> None:
        async with fs_timer(FsOps.WATCHER_RESCAN):
            try:
                conv_ids = await list_session_ids(self.user_id)
                self._sessions_root_ino = await sessions_root_inode(self.user_id)
            except JuiceFSUnavailable:
                return
            await self._rescan_each(conv_ids)
            # Drop inode-map entries for conversations that no longer exist so
            # the map can't grow without bound across a long-lived sandbox.
            live = set(conv_ids)
            self._inode_conv = {ino: c for ino, c in self._inode_conv.items() if c in live}

    async def _rescan_each(self, conv_ids: list[str]) -> None:
        for conv in conv_ids:
            try:
                conv_ino, artifacts_ino = await session_dir_inodes(self.user_id, conv)
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
            # Rebuild this conv's inode entries from scratch so deleted files
            # don't linger in the map.
            self._inode_conv = {ino: c for ino, c in self._inode_conv.items() if c != conv}
            for dir_ino in (conv_ino, artifacts_ino):
                if dir_ino is not None:
                    self._inode_conv[dir_ino] = conv
            prev = self._snapshots.get(conv, {})
            current: dict[str, tuple[int, float]] = {}
            for info in infos:
                current[info.path] = (info.size_bytes, info.mtime)
                if info.inode:
                    self._inode_conv[info.inode] = conv
                if prev.get(info.path) != (info.size_bytes, info.mtime):
                    await publish_artifact_event(self.user_id, upsert_event(conv, info))
            for gone in prev.keys() - current.keys():
                await publish_artifact_event(self.user_id, remove_event(conv, gone))
            self._snapshots[conv] = current


async def start_watcher_for(user_id: str, sandbox: AsyncSandbox) -> ArtifactWatcher:
    """Construct + start a watcher for a freshly acquired sandbox."""
    watcher = ArtifactWatcher(user_id, sandbox)
    await watcher.start()
    return watcher
