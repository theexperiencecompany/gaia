"""Artifact watcher: event routing, accesslog scoping, rescan diffing, lifecycle.

The watcher is what makes an agent-written file appear in the chat UI. When it
drops an event the file silently never shows up, and when it publishes a wrong
one the UI shows a file that isn't there — both are invisible in logs, so they
have to be caught here.

Boundaries mocked: the Redis publish, the JuiceFS stat/list calls, and the E2B
sandbox. Everything else — classification, inode routing, debounce/backstop
scheduling, snapshot diffing — is the real production code.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from e2b import AsyncSandbox
import pytest

from app.agents.workspace.paths import session_artifacts
from app.services.sandbox import artifact_watcher as aw
from app.services.sandbox.artifact_watcher import ArtifactWatcher, _strip_artifacts_prefix
from app.services.storage import JuiceFSUnavailable
from app.services.storage.sessions.artifacts import ArtifactInfo

pytestmark = pytest.mark.unit

USER = "user-1"
CONV = "conv-a"


def info(path: str, size: int = 10, mtime: float = 100.0, inode: int = 0) -> ArtifactInfo:
    return ArtifactInfo(
        path=path, size_bytes=size, mtime=mtime, content_type="text/plain", inode=inode
    )


def fs_event(name: str, etype: str = "WRITE") -> SimpleNamespace:
    """Stand-in for e2b's FilesystemEvent (name is relative to the watch root)."""
    return SimpleNamespace(name=name, type=SimpleNamespace(name=etype))


def fake_sandbox(**files: Any) -> AsyncSandbox:
    """A duck-typed stand-in for e2b's AsyncSandbox.

    The watcher only ever reaches through ``.files``, so a namespace carrying the
    methods under test is a complete double — constructing a real AsyncSandbox
    would require a live E2B session. Stating that once here keeps the assumption
    in one reviewable place instead of repeated at every construction site.
    """
    return cast(AsyncSandbox, SimpleNamespace(files=SimpleNamespace(**files)))


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture what reaches the Redis channel — the watcher's only real output."""
    events: list[dict[str, Any]] = []

    async def capture(user_id: str, payload: dict[str, Any]) -> None:
        events.append({"user_id": user_id, **payload})

    monkeypatch.setattr(aw, "publish_artifact_event", capture)
    return events


@pytest.fixture
def watcher() -> ArtifactWatcher:
    return ArtifactWatcher(USER, sandbox=fake_sandbox())


@pytest.fixture
def stat_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the JuiceFS stat succeed.

    Without this the real ``stat_artifact`` raises ``JuiceFSUnavailable`` (no
    mount under unit tests) and every "publishes nothing" assertion passes for
    that reason instead of the guard under test — a mutation of the guard stays
    green. With it, a publish is what happens unless a guard stops it.
    """

    async def stat(user_id: str, conv: str, rel: str) -> ArtifactInfo:
        return info(rel, size=42, mtime=7.0)

    monkeypatch.setattr(aw, "stat_artifact", stat)


@pytest.fixture
def upserts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Record every upsert_event construction, including invalid ones.

    ``_on_fs_event`` wraps its body in a broad ``except Exception``, so a guard
    removal that makes ``upsert_event`` raise is otherwise indistinguishable
    from the guard working.
    """
    calls: list[tuple[str, Any]] = []
    real = aw.upsert_event

    def record(session_id: str, art: Any, **kw: Any) -> dict[str, Any]:
        calls.append((session_id, art))
        return real(session_id, art, **kw)

    monkeypatch.setattr(aw, "upsert_event", record)
    return calls


# ── _strip_artifacts_prefix ──────────────────────────────────────────


def test_a_nested_artifact_keeps_its_subdirectories_in_the_relative_path() -> None:
    abs_path = f"{session_artifacts(CONV)}/reports/q3/summary.md"
    assert _strip_artifacts_prefix(abs_path, CONV) == "reports/q3/summary.md"


def test_a_file_directly_in_artifacts_strips_to_its_bare_name() -> None:
    assert _strip_artifacts_prefix(f"{session_artifacts(CONV)}/a.md", CONV) == "a.md"


def test_a_path_outside_the_conversation_degrades_to_the_basename() -> None:
    # Guards the fallback branch: a path belonging to another conversation must
    # not be reported under this one with its full nesting intact.
    assert _strip_artifacts_prefix(f"{session_artifacts('other')}/deep/x.md", CONV) == "x.md"


# ── _on_fs_event: what must NOT be published ─────────────────────────


async def test_a_temp_file_write_publishes_nothing(
    published: list[dict[str, Any]], stat_ok: None
) -> None:
    # Atomic writes land as `<name>.gaia-tmp` then rename. Publishing the temp
    # file makes a half-written artifact flash in the user's panel.
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/report.md{aw.WORKSPACE_TMP_SUFFIX}"))
    assert published == []


@pytest.mark.parametrize("subdir", ["scratch", "user-uploaded"])
async def test_writes_outside_the_artifacts_dir_publish_nothing(
    published: list[dict[str, Any]], stat_ok: None, subdir: str
) -> None:
    # Only `artifacts/` is user-visible. Scratch is the agent's working dir and
    # must never surface in the file panel.
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/{subdir}/secret.txt"))
    assert published == []


async def test_a_directory_event_publishes_nothing(
    published: list[dict[str, Any]], stat_ok: None
) -> None:
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/"))
    assert published == []


async def test_an_unreadable_workspace_is_swallowed_rather_than_killing_the_stream(
    published: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The watcher is a latency optimization; a JuiceFS blip must not propagate
    # out of the e2b callback and tear down the whole watch stream.
    async def unavailable(*_a: Any, **_k: Any) -> ArtifactInfo | None:
        raise JuiceFSUnavailable("mount gone")

    monkeypatch.setattr(aw, "stat_artifact", unavailable)
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/a.md"))
    assert published == []


async def test_a_file_deleted_between_the_event_and_the_stat_publishes_nothing(
    published: list[dict[str, Any]],
    upserts: list[tuple[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def gone(*_a: Any, **_k: Any) -> ArtifactInfo | None:
        return None

    monkeypatch.setattr(aw, "stat_artifact", gone)
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/a.md"))

    assert published == []
    # The watcher must bail before building an event, not build a broken one and
    # rely on the catch-all to hide it.
    assert upserts == []


# ── _on_fs_event: what MUST be published ─────────────────────────────


async def test_a_written_artifact_is_published_as_an_upsert_for_its_conversation(
    published: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stat(user_id: str, conv: str, rel: str) -> ArtifactInfo:
        return info(rel, size=42, mtime=7.0)

    monkeypatch.setattr(aw, "stat_artifact", stat)
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/nested/a.md"))

    assert len(published) == 1
    assert published[0]["user_id"] == USER
    assert published[0]["session_id"] == CONV
    assert "nested/a.md" in str(published[0])


@pytest.mark.parametrize("etype", ["REMOVE", "RENAME"])
async def test_a_removed_artifact_is_published_without_being_stat_ed(
    published: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, etype: str
) -> None:
    # A deleted file cannot be stat'd; the watcher must emit the removal from
    # the event alone rather than dropping it when the stat fails.
    async def must_not_run(*_a: Any, **_k: Any) -> ArtifactInfo | None:
        raise AssertionError("stat_artifact must not be called for a removal")

    monkeypatch.setattr(aw, "stat_artifact", must_not_run)
    w = ArtifactWatcher(USER, fake_sandbox())
    await w._on_fs_event(fs_event(f"{CONV}/artifacts/a.md", etype))

    assert len(published) == 1
    assert published[0]["session_id"] == CONV


# ── _on_accesslog_line: routing ──────────────────────────────────────


def line(op: str, args: str = "500,4096,0") -> str:
    return f"2026.07.30 10:00:00 [uid:1000,gid:1000,pid:9] {op} ({args}): OK <0.0001>"


def test_an_unparseable_accesslog_line_schedules_no_rescan(watcher: ArtifactWatcher) -> None:
    watcher._on_accesslog_line("garbage without the expected shape")
    assert watcher._rescan_task is None


@pytest.mark.parametrize("op", ["read", "getattr", "lookup", "open", "flush"])
def test_a_read_only_op_schedules_no_rescan(watcher: ArtifactWatcher, op: str) -> None:
    # Reads dominate the accesslog. Rescanning on them would hammer JuiceFS.
    watcher._on_accesslog_line(line(op))
    assert watcher._rescan_task is None


@pytest.mark.parametrize("op", ["write", "create", "rename", "unlink", "mkdir", "truncate"])
async def test_a_mutating_op_schedules_a_rescan(watcher: ArtifactWatcher, op: str) -> None:
    watcher._on_accesslog_line(line(op))
    assert watcher._rescan_task is not None
    watcher._rescan_task.cancel()


async def test_the_first_mutating_op_forces_a_full_rescan_to_seed_the_inode_map(
    watcher: ArtifactWatcher,
) -> None:
    assert watcher._inode_conv == {}
    # Clear the constructor's default so the flag can only be True if the
    # unseeded-map branch actually set it.
    watcher._need_full_rescan = False
    watcher._on_accesslog_line(line("write"))
    assert watcher._need_full_rescan is True
    assert watcher._rescan_task is not None
    watcher._rescan_task.cancel()


async def test_touching_the_sessions_root_forces_a_full_rescan(watcher: ArtifactWatcher) -> None:
    # A new conversation dir appears/disappears under the sessions root; a
    # scoped rescan of known convs would never notice it.
    watcher._inode_conv = {900: CONV}
    watcher._need_full_rescan = False
    watcher._sessions_root_ino = 77
    watcher._on_accesslog_line(line("mkdir", args="77,0"))
    assert watcher._need_full_rescan is True
    assert watcher._rescan_task is not None
    watcher._rescan_task.cancel()


async def test_a_known_inode_scopes_the_rescan_to_just_that_conversation(
    watcher: ArtifactWatcher,
) -> None:
    watcher._inode_conv = {900: CONV, 901: "conv-b"}
    watcher._need_full_rescan = False
    watcher._sessions_root_ino = 77
    watcher._on_accesslog_line(line("write", args="900"))
    assert watcher._dirty_convs == {CONV}
    assert watcher._need_full_rescan is False
    assert watcher._rescan_task is not None
    watcher._rescan_task.cancel()


async def test_an_untracked_inode_dirties_no_conversation(watcher: ArtifactWatcher) -> None:
    # Writes to scratch/.gaia/skills share the accesslog. They must not trigger
    # a rescan of a real conversation.
    watcher._inode_conv = {900: CONV}
    watcher._need_full_rescan = False
    watcher._sessions_root_ino = 77
    watcher._on_accesslog_line(line("write", args="12345"))
    assert watcher._dirty_convs == set()
    assert watcher._need_full_rescan is False
    if watcher._rescan_task is not None:
        watcher._rescan_task.cancel()


async def test_a_second_op_while_a_rescan_is_pending_reuses_the_same_task(
    watcher: ArtifactWatcher,
) -> None:
    # Debounce: a burst of writes must coalesce into one rescan, not one per line.
    watcher._on_accesslog_line(line("write"))
    first = watcher._rescan_task
    watcher._on_accesslog_line(line("write"))
    assert watcher._rescan_task is first
    assert first is not None
    first.cancel()


# ── _rescan_each: snapshot diffing ───────────────────────────────────


@pytest.fixture
def stub_scan(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Drive _rescan_each's JuiceFS reads from an in-test table."""
    state: dict[str, Any] = {"artifacts": {}, "inodes": (10, 11), "sessions": [CONV]}

    async def list_artifacts(user_id: str, conv: str) -> list[ArtifactInfo]:
        return state["artifacts"].get(conv, [])

    async def session_dir_inodes(user_id: str, conv: str) -> tuple[int | None, int | None]:
        return state["inodes"]

    async def list_session_ids(user_id: str) -> list[str]:
        return state["sessions"]

    async def sessions_root_inode(user_id: str) -> int | None:
        return 77

    monkeypatch.setattr(aw, "list_artifacts", list_artifacts)
    monkeypatch.setattr(aw, "session_dir_inodes", session_dir_inodes)
    monkeypatch.setattr(aw, "list_session_ids", list_session_ids)
    monkeypatch.setattr(aw, "sessions_root_inode", sessions_root_inode)
    return state


async def test_a_new_artifact_is_published_on_the_first_scan(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    stub_scan["artifacts"] = {CONV: [info("a.md")]}
    await watcher._rescan_each([CONV])
    assert len(published) == 1


async def test_an_unchanged_artifact_is_not_republished(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    # Re-publishing every scan would make the UI flicker and the channel noisy.
    stub_scan["artifacts"] = {CONV: [info("a.md", size=10, mtime=100.0)]}
    await watcher._rescan_each([CONV])
    published.clear()
    await watcher._rescan_each([CONV])
    assert published == []


@pytest.mark.parametrize(
    ("size", "mtime"),
    [(11, 100.0), (10, 101.0)],
    ids=["size changed", "mtime changed"],
)
async def test_a_modified_artifact_is_republished(
    watcher: ArtifactWatcher,
    published: list[dict[str, Any]],
    stub_scan: dict[str, Any],
    size: int,
    mtime: float,
) -> None:
    stub_scan["artifacts"] = {CONV: [info("a.md", size=10, mtime=100.0)]}
    await watcher._rescan_each([CONV])
    published.clear()
    stub_scan["artifacts"] = {CONV: [info("a.md", size=size, mtime=mtime)]}
    await watcher._rescan_each([CONV])
    assert len(published) == 1


async def test_a_deleted_artifact_is_published_as_a_removal(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    stub_scan["artifacts"] = {CONV: [info("a.md"), info("b.md")]}
    await watcher._rescan_each([CONV])
    published.clear()
    stub_scan["artifacts"] = {CONV: [info("a.md")]}
    await watcher._rescan_each([CONV])

    assert len(published) == 1
    assert "b.md" in str(published[0])


async def test_a_scan_maps_artifact_inodes_so_later_ops_can_be_scoped(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    stub_scan["artifacts"] = {CONV: [info("a.md", inode=555)]}
    await watcher._rescan_each([CONV])
    # file inode + both session dir inodes all route back to this conversation
    assert watcher._inode_conv[555] == CONV
    assert watcher._inode_conv[10] == CONV
    assert watcher._inode_conv[11] == CONV


async def test_a_deleted_artifacts_inode_stops_routing_to_its_conversation(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    # Inodes get reused by the filesystem. A stale entry would misroute a write
    # from an unrelated file into this conversation.
    stub_scan["artifacts"] = {CONV: [info("a.md", inode=555)]}
    await watcher._rescan_each([CONV])
    stub_scan["artifacts"] = {CONV: [info("b.md", inode=556)]}
    await watcher._rescan_each([CONV])
    assert 555 not in watcher._inode_conv
    assert watcher._inode_conv[556] == CONV


async def test_a_conversation_that_fails_to_scan_does_not_block_the_others(
    watcher: ArtifactWatcher,
    published: list[dict[str, Any]],
    stub_scan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def list_artifacts(user_id: str, conv: str) -> list[ArtifactInfo]:
        if conv == "bad":
            raise OSError("stat failed")
        return [info("a.md")]

    monkeypatch.setattr(aw, "list_artifacts", list_artifacts)
    await watcher._rescan_each(["bad", CONV])
    assert len(published) == 1


async def test_a_vanished_mount_aborts_the_scan_without_raising(
    watcher: ArtifactWatcher,
    published: list[dict[str, Any]],
    stub_scan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*_a: Any, **_k: Any) -> list[ArtifactInfo]:
        raise JuiceFSUnavailable("mount gone")

    monkeypatch.setattr(aw, "list_artifacts", unavailable)
    await watcher._rescan_each([CONV])
    assert published == []


async def test_a_full_rescan_forgets_conversations_that_no_longer_exist(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    # Otherwise the inode map grows unbounded over a long-lived sandbox.
    watcher._inode_conv = {999: "deleted-conv"}
    stub_scan["artifacts"] = {CONV: [info("a.md", inode=555)]}
    stub_scan["sessions"] = [CONV]
    await watcher._rescan_all()
    assert 999 not in watcher._inode_conv


# ── _debounced_rescan: scheduling ────────────────────────────────────


async def test_the_backstop_forces_a_full_rescan_even_with_nothing_marked_dirty(
    watcher: ArtifactWatcher, published: list[dict[str, Any]], stub_scan: dict[str, Any]
) -> None:
    # The safety net for an op whose inode never mapped to a conversation.
    stub_scan["artifacts"] = {CONV: [info("a.md")]}
    watcher._need_full_rescan = False
    watcher._dirty_convs = set()
    watcher._last_full_rescan = 0.0  # far past the backstop window
    await watcher._debounced_rescan()
    assert len(published) == 1


async def test_a_scoped_rescan_only_touches_the_dirty_conversation(
    watcher: ArtifactWatcher,
    published: list[dict[str, Any]],
    stub_scan: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanned: list[str] = []

    async def list_artifacts(user_id: str, conv: str) -> list[ArtifactInfo]:
        scanned.append(conv)
        return []

    monkeypatch.setattr(aw, "list_artifacts", list_artifacts)
    monkeypatch.setattr(aw, "_ACCESSLOG_DEBOUNCE_SECONDS", 0.0)
    import time as _time

    watcher._need_full_rescan = False
    watcher._last_full_rescan = _time.monotonic()  # backstop not due
    watcher._dirty_convs = {CONV}
    await watcher._debounced_rescan()
    assert scanned == [CONV]


async def test_a_cancelled_rescan_propagates_cancellation(watcher: ArtifactWatcher) -> None:
    # Swallowing CancelledError here would leak the task past stop().
    task = asyncio.create_task(watcher._debounced_rescan())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── lifecycle ────────────────────────────────────────────────────────


class FakeHandle:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


def sandbox_for_watch_dir(handle: FakeHandle) -> AsyncSandbox:
    async def watch_dir(*_a: Any, **_k: Any) -> FakeHandle:
        return handle

    async def make_dir(*_a: Any, **_k: Any) -> None:
        return None

    return fake_sandbox(watch_dir=watch_dir, make_dir=make_dir)


async def test_a_started_watcher_reports_itself_alive() -> None:
    handle = FakeHandle()
    w = ArtifactWatcher(USER, sandbox_for_watch_dir(handle))
    await w.start()
    assert w.is_alive() is True


async def test_a_watcher_that_fails_to_start_stays_dead_instead_of_raising() -> None:
    # A watcher failure must never block sandbox acquisition.
    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("envd unavailable")

    sandbox = fake_sandbox(watch_dir=boom, make_dir=boom)
    w = ArtifactWatcher(USER, sandbox)
    await w.start()
    assert w.is_alive() is False


async def test_starting_an_already_running_watcher_does_not_open_a_second_stream() -> None:
    calls: list[int] = []

    async def watch_dir(*_a: Any, **_k: Any) -> FakeHandle:
        calls.append(1)
        return FakeHandle()

    async def make_dir(*_a: Any, **_k: Any) -> None:
        return None

    sandbox = fake_sandbox(watch_dir=watch_dir, make_dir=make_dir)
    w = ArtifactWatcher(USER, sandbox)
    await w.start()
    await w.start()
    assert len(calls) == 1


async def test_stopping_releases_the_handle_and_reports_not_alive() -> None:
    handle = FakeHandle()
    w = ArtifactWatcher(USER, sandbox_for_watch_dir(handle))
    await w.start()
    await w.stop()
    assert handle.stopped is True
    assert w.is_alive() is False


async def test_stopping_cancels_a_pending_rescan_so_it_cannot_publish_afterwards(
    published: list[dict[str, Any]],
) -> None:
    handle = FakeHandle()
    w = ArtifactWatcher(USER, sandbox_for_watch_dir(handle))
    await w.start()
    w._schedule_rescan()
    task = w._rescan_task
    await w.stop()
    assert (task is not None and task.cancelled()) or task.done() or True
    await asyncio.sleep(0)
    assert task is not None
    assert task.cancelled() or task.done()


async def test_a_dead_watch_stream_marks_the_watcher_not_alive() -> None:
    # envd restart / sandbox pause kills the stream; the next acquire must be
    # able to tell so it can reopen it.
    handle = FakeHandle()
    w = ArtifactWatcher(USER, sandbox_for_watch_dir(handle))
    await w.start()
    w._on_watch_exit(None)
    assert w.is_alive() is False


async def test_start_watcher_for_returns_a_started_watcher() -> None:
    handle = FakeHandle()
    w = await aw.start_watcher_for(USER, sandbox_for_watch_dir(handle))
    assert isinstance(w, ArtifactWatcher)
    assert w.is_alive() is True
