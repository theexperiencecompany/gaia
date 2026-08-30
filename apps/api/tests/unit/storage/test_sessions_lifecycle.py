"""Session lifecycle: on-disk enumeration, deletion, meta touching, idle scan.

This module is the only thing that decides which conversations the artifact
watcher rescans (``list_session_ids`` / ``sessions_root_inode``), which session
trees get recursively deleted, and which sessions the idle pruner destroys. A
wrong answer here is either a conversation whose files silently never appear in
the UI, or a user's data deleted early — neither shows up in a log line.

The filesystem IS the logic under test, so it is not mocked: the JuiceFS mount
root is pointed at a real ``tmp_path`` and the real directory walking runs. The
only mocked boundaries are ``_is_mounted`` (a tmpdir is not a real mountpoint),
the Mongo-backed instructions read, and the skill materializers, which live in
their own module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
from typing import Any

import pytest

from app.config.settings import settings
from app.services.storage import JuiceFSUnavailable
from app.services.storage.sessions import lifecycle as lc
from app.services.storage.sessions.meta import SESSION_META_FILENAME

USER = "user-1"
OTHER_USER = "user-2"
CONV = "conv-a"


def set_mounted(monkeypatch: pytest.MonkeyPatch, value: bool) -> None:
    """Flip the mount-presence probe in both namespaces that read it.

    ``lifecycle`` imported ``_is_mounted`` by value, and ``_require_mount``
    (reached via ``session_base``) reads the ``juicefs`` module global — a test
    that patched only one would leave half the guards live.
    """
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: value)
    monkeypatch.setattr(lc, "_is_mounted", lambda: value)


@pytest.fixture
def mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    set_mounted(monkeypatch, True)
    return root


def sessions_dir(mount: Path, user: str = USER) -> Path:
    d = mount / "users" / user / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def make_session(mount: Path, conv: str, user: str = USER) -> Path:
    d = sessions_dir(mount, user) / conv
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_meta(session: Path, **fields: Any) -> None:
    (session / SESSION_META_FILENAME).write_text(json.dumps(fields), encoding="utf-8")


def aged_session(mount: Path, conv: str, *, days: float, user: str = USER) -> Path:
    d = make_session(mount, conv, user)
    write_meta(d, last_active=(datetime.now(UTC) - timedelta(days=days)).isoformat())
    return d


# ── list_session_ids — the watcher's conversation enumeration ────────


async def test_no_sessions_are_listed_when_the_mount_is_gone(
    mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The tree exists but the mount is down: the watcher must get an empty list
    # rather than a stale read of whatever the container's local disk holds.
    make_session(mount, CONV)
    set_mounted(monkeypatch, False)
    assert await lc.list_session_ids(USER) == []


async def test_a_user_with_no_sessions_directory_lists_nothing(mount: Path) -> None:
    # A brand-new user has no sessions/ dir; the watcher's first rescan must not
    # blow up on the missing path.
    (mount / "users" / USER).mkdir(parents=True)
    assert await lc.list_session_ids(USER) == []


async def test_an_empty_sessions_directory_lists_nothing(mount: Path) -> None:
    sessions_dir(mount)
    assert await lc.list_session_ids(USER) == []


async def test_every_session_directory_is_listed_in_sorted_order(mount: Path) -> None:
    # The watcher zips these ids against its snapshot map; unsorted output makes
    # the diff order (and any bisect over it) non-deterministic.
    for conv in ("zeta", "alpha", "middle"):
        make_session(mount, conv)
    assert await lc.list_session_ids(USER) == ["alpha", "middle", "zeta"]


async def test_a_loose_file_under_sessions_is_not_reported_as_a_conversation(
    mount: Path,
) -> None:
    # Dropping the is_dir() filter would hand the watcher a "conversation" named
    # after a stray file, and every artifact listing for it would fail.
    make_session(mount, CONV)
    (sessions_dir(mount) / "notes.txt").write_text("x")
    assert await lc.list_session_ids(USER) == [CONV]


async def test_only_top_level_session_dirs_are_listed_not_their_subtrees(
    mount: Path,
) -> None:
    # Every session dir contains artifacts/ and scratch/. A recursive walk would
    # report those as sibling conversations.
    session = make_session(mount, CONV)
    (session / "artifacts").mkdir()
    (session / "scratch" / "deep").mkdir(parents=True)
    assert await lc.list_session_ids(USER) == [CONV]


async def test_another_users_sessions_are_never_listed(mount: Path) -> None:
    make_session(mount, "mine")
    make_session(mount, "theirs", user=OTHER_USER)
    assert await lc.list_session_ids(USER) == ["mine"]


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory permissions"
)
async def test_an_unreadable_sessions_directory_surfaces_the_os_error(mount: Path) -> None:
    # Pins the contract the watcher sees: unlike sessions_root_inode (which
    # swallows OSError), this call propagates. Adding a blanket except here
    # would turn a broken mount into "the user has no conversations" and the
    # watcher would silently forget every session it was tracking.
    d = sessions_dir(mount)
    make_session(mount, CONV)
    d.chmod(0o000)
    try:
        with pytest.raises(PermissionError):
            await lc.list_session_ids(USER)
    finally:
        d.chmod(stat.S_IRWXU)


# ── sessions_root_inode — the watcher's "new conversation" trigger ───


async def test_the_reported_inode_is_the_sessions_dir_itself(mount: Path) -> None:
    # The watcher compares accesslog inodes against this number to decide a full
    # rescan. Pointing it one level up (the user root) means creating a new
    # conversation never triggers one.
    d = sessions_dir(mount)
    assert await lc.sessions_root_inode(USER) == d.stat().st_ino
    assert await lc.sessions_root_inode(USER) != (mount / "users" / USER).stat().st_ino


async def test_a_missing_sessions_dir_reports_no_inode(mount: Path) -> None:
    (mount / "users" / USER).mkdir(parents=True)
    assert await lc.sessions_root_inode(USER) is None


async def test_no_inode_is_reported_when_the_mount_is_gone(
    mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_dir(mount)
    set_mounted(monkeypatch, False)
    assert await lc.sessions_root_inode(USER) is None


# ── delete_session_dir ───────────────────────────────────────────────


async def test_deleting_a_session_removes_its_whole_tree(mount: Path) -> None:
    session = make_session(mount, CONV)
    (session / "artifacts").mkdir()
    (session / "artifacts" / "out.md").write_text("hi")
    await lc.delete_session_dir(USER, CONV)
    assert not session.exists()


async def test_deleting_one_session_leaves_the_others_alone(mount: Path) -> None:
    # A rmtree anchored one level too high would take the user's whole sessions
    # tree with it.
    make_session(mount, CONV)
    keeper = make_session(mount, "conv-b")
    await lc.delete_session_dir(USER, CONV)
    assert keeper.is_dir()


async def test_deleting_a_session_that_was_never_created_is_a_no_op(mount: Path) -> None:
    sessions_dir(mount)
    await lc.delete_session_dir(USER, "never-existed")
    assert sessions_dir(mount).is_dir()


async def test_a_symlinked_session_path_is_not_followed_into_its_target(mount: Path) -> None:
    # rmtree() on a symlink raises, and a naive fix (unlink the target) would
    # let a planted link delete an unrelated tree on the shared mount.
    victim = mount / "victim"
    victim.mkdir()
    (victim / "important.txt").write_text("keep me")
    (sessions_dir(mount) / "linked").symlink_to(victim, target_is_directory=True)

    await lc.delete_session_dir(USER, "linked")
    assert (victim / "important.txt").exists()


@pytest.mark.parametrize("conv_id", ["../../users", "a/b", "conv..a/../..", ""])
async def test_a_conversation_id_that_could_escape_the_session_root_deletes_nothing(
    mount: Path, conv_id: str
) -> None:
    # delete_session_dir swallows the ValueError from the id validator; if that
    # validation were dropped the rmtree would land outside the user's tree.
    own = sessions_dir(mount)
    other = make_session(mount, "kept", user=OTHER_USER)
    await lc.delete_session_dir(USER, conv_id)
    assert own.is_dir()
    assert other.is_dir()
    assert (mount / "users").is_dir()


async def test_delete_touches_nothing_when_the_mount_is_gone(
    mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the guard this would rmtree the container's local disk path, which
    # is not the data the sandbox sees.
    session = make_session(mount, CONV)
    set_mounted(monkeypatch, False)
    await lc.delete_session_dir(USER, CONV)
    assert session.is_dir()


# ── touch_session_last_active ────────────────────────────────────────


async def test_touching_a_new_session_creates_it_and_stamps_both_timestamps(
    mount: Path,
) -> None:
    await lc.touch_session_last_active(USER, CONV)
    data = json.loads((sessions_dir(mount) / CONV / SESSION_META_FILENAME).read_text())
    assert data["created_at"] == data["last_active"]
    assert data["msg_count"] == 0
    assert data["schema_version"] == 1


async def test_touching_again_keeps_created_at_and_advances_last_active(mount: Path) -> None:
    # created_at is immutable — resetting it on every turn would make every
    # session look brand new to any age-based reporting.
    session = make_session(mount, CONV)
    write_meta(
        session, created_at="2020-01-01T00:00:00+00:00", last_active="2020-01-01T00:00:00+00:00"
    )
    await lc.touch_session_last_active(USER, CONV)

    data = json.loads((session / SESSION_META_FILENAME).read_text())
    assert data["created_at"] == "2020-01-01T00:00:00+00:00"
    assert data["last_active"] > "2020-01-01T00:00:00+00:00"


async def test_touching_preserves_an_existing_message_count(mount: Path) -> None:
    # setdefault, not assignment: a touch must not reset the counter to zero.
    session = make_session(mount, CONV)
    write_meta(session, created_at="2020-01-01T00:00:00+00:00", msg_count=17)
    await lc.touch_session_last_active(USER, CONV)
    assert json.loads((session / SESSION_META_FILENAME).read_text())["msg_count"] == 17


async def test_a_corrupt_meta_file_is_rebuilt_instead_of_raising(mount: Path) -> None:
    # A half-written .meta.json (crash mid-write) must not wedge every
    # subsequent turn for that conversation.
    session = make_session(mount, CONV)
    (session / SESSION_META_FILENAME).write_text("{not json", encoding="utf-8")
    await lc.touch_session_last_active(USER, CONV)

    data = json.loads((session / SESSION_META_FILENAME).read_text())
    assert data["created_at"] == data["last_active"]
    assert data["msg_count"] == 0


async def test_touching_fails_loud_when_the_mount_is_gone(
    mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unlike the read/delete paths, this one must NOT soft-fail: silently
    # skipping the stamp makes a live session look idle to the pruner.
    set_mounted(monkeypatch, False)
    with pytest.raises(JuiceFSUnavailable):
        await lc.touch_session_last_active(USER, CONV)


@pytest.mark.parametrize("conv_id", ["../escape", "a/b", ""])
async def test_touching_rejects_a_conversation_id_that_is_not_one_path_component(
    mount: Path, conv_id: str
) -> None:
    sessions_dir(mount)
    with pytest.raises(ValueError, match="unsafe conversation_id"):
        await lc.touch_session_last_active(USER, conv_id)
    assert list(sessions_dir(mount).iterdir()) == []


# ── chmod_path ───────────────────────────────────────────────────────


async def test_chmod_path_applies_the_mode_to_the_real_file(tmp_path: Path) -> None:
    target = tmp_path / "script.sh"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o600)
    await lc.chmod_path(target, 0o755)
    assert stat.S_IMODE(target.stat().st_mode) == 0o755


# ── list_stale_sessions — what the idle pruner is allowed to delete ──


async def test_a_session_idle_past_the_cutoff_is_reported(mount: Path) -> None:
    aged_session(mount, CONV, days=40)
    assert await lc.list_stale_sessions(30) == [(USER, CONV)]


async def test_a_recently_active_session_is_never_reported(mount: Path) -> None:
    # This is the "we deleted a live user's workspace" bug.
    aged_session(mount, CONV, days=1)
    assert await lc.list_stale_sessions(30) == []


@pytest.mark.parametrize(
    ("offset_seconds", "expected_stale"),
    [(-5, True), (5, False)],
    ids=["just past the cutoff", "just inside the cutoff"],
)
async def test_the_cutoff_is_decided_to_the_second_not_the_day(
    mount: Path, offset_seconds: int, expected_stale: bool
) -> None:
    # Five seconds either side of the cutoff instant flips the verdict. Inverting
    # the comparison prunes every live session; rounding the cutoff to whole days
    # prunes (or spares) a day's worth of them.
    session = make_session(mount, CONV)
    ts = datetime.now(UTC) - timedelta(days=30) + timedelta(seconds=offset_seconds)
    write_meta(session, last_active=ts.isoformat())
    found = await lc.list_stale_sessions(30)
    assert (found == [(USER, CONV)]) is expected_stale


async def test_a_session_with_no_meta_file_is_skipped_not_pruned(mount: Path) -> None:
    # Absence of a timestamp means "unknown", never "ancient" — a session dir
    # created seconds ago has no meta yet.
    make_session(mount, CONV)
    assert await lc.list_stale_sessions(30) == []


@pytest.mark.parametrize("raw", ["not-a-date", "", "2020-13-99", "{}"])
async def test_a_session_with_an_unparseable_timestamp_is_skipped_not_pruned(
    mount: Path, raw: str
) -> None:
    session = make_session(mount, CONV)
    write_meta(session, last_active=raw)
    assert await lc.list_stale_sessions(30) == []


async def test_a_timestamp_without_a_timezone_is_read_as_utc(mount: Path) -> None:
    # Older writes landed naive; comparing them against an aware `now` raises
    # TypeError, which would abort the whole scan rather than skip one session.
    session = make_session(mount, CONV)
    naive = (datetime.now(UTC) - timedelta(days=40)).replace(tzinfo=None)
    write_meta(session, last_active=naive.isoformat())
    assert await lc.list_stale_sessions(30) == [(USER, CONV)]


async def test_stale_sessions_are_reported_sorted_by_user_then_session(mount: Path) -> None:
    # Created in reverse order on purpose: iterdir() hands them back in creation
    # order on most filesystems, so dropping either sort() shows up here.
    aged_session(mount, "beta", days=40, user=OTHER_USER)
    aged_session(mount, "zeta", days=40)
    aged_session(mount, "alpha", days=40)
    assert await lc.list_stale_sessions(30) == [
        (USER, "alpha"),
        (USER, "zeta"),
        (OTHER_USER, "beta"),
    ]


async def test_the_limit_caps_the_batch_within_a_single_user(mount: Path) -> None:
    # The pruner runs in bounded batches; ignoring the limit turns one worker
    # tick into an unbounded delete storm.
    for conv in ("c1", "c2", "c3", "c4"):
        aged_session(mount, conv, days=40)
    assert await lc.list_stale_sessions(30, limit=2) == [(USER, "c1"), (USER, "c2")]


async def test_the_limit_caps_the_batch_across_users(mount: Path) -> None:
    aged_session(mount, "c2", days=40, user=OTHER_USER)
    aged_session(mount, "c3", days=40, user=OTHER_USER)
    aged_session(mount, "c1", days=40)
    assert await lc.list_stale_sessions(30, limit=2) == [(USER, "c1"), (OTHER_USER, "c2")]


async def test_no_limit_returns_every_stale_session(mount: Path) -> None:
    for conv in ("c1", "c2", "c3"):
        aged_session(mount, conv, days=40)
    assert len(await lc.list_stale_sessions(30)) == 3


async def test_loose_files_in_the_users_root_and_sessions_dir_are_skipped(mount: Path) -> None:
    # `_system` files and stray uploads share the users/ root; treating one as a
    # user dir (or a file as a session) crashes the whole pruner tick.
    aged_session(mount, CONV, days=40)
    (mount / "users" / "README.md").write_text("x")
    (sessions_dir(mount) / "stray.txt").write_text("x")
    assert await lc.list_stale_sessions(30) == [(USER, CONV)]


async def test_nothing_is_reported_stale_when_the_mount_is_gone(
    mount: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aged_session(mount, CONV, days=40)
    set_mounted(monkeypatch, False)
    assert await lc.list_stale_sessions(30) == []


async def test_nothing_is_reported_stale_when_no_user_has_a_workspace(mount: Path) -> None:
    assert await lc.list_stale_sessions(30) == []


# ── materialize_user_integrations — the staleness gate ───────────────

SKILLS_MARKER = ".gaia/skills.v"
CONNECTED_MARKER = ".gaia/connected.v"
INSTRUCTIONS_MARKER = ".gaia/instructions.v"


@pytest.fixture
def materializers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Record calls to the two catalog writers — they own their own module.

    Without this the gate is untestable: the real materializers are idempotent,
    so a broken gate that rewrites on every call produces identical bytes on
    disk and looks exactly like a working one.
    """
    calls: list[tuple[str, Any]] = []

    def skills(user_root: Path, connected: set[str]) -> int:
        calls.append(("skills", set(connected)))
        return 0

    def instructions(user_root: Path, payload: dict[str, str]) -> int:
        calls.append(("instructions", dict(payload)))
        return 0

    monkeypatch.setattr(lc, "materialize_skills", skills)
    monkeypatch.setattr(lc, "materialize_instructions", instructions)
    return calls


@pytest.fixture
def instructions_source(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Stand in for the Mongo-backed per-user instructions read."""
    payload: dict[str, str] = {}

    async def get_all(user_id: str) -> dict[str, str]:
        return dict(payload)

    monkeypatch.setattr(
        "app.services.integration_instructions_service.get_all_instructions", get_all
    )
    return payload


async def test_first_materialization_stamps_all_three_signature_markers(
    mount: Path, materializers: list[tuple[str, Any]], instructions_source: dict[str, str]
) -> None:
    await lc.materialize_user_integrations(USER, {"gmail"})
    u_root = mount / "users" / USER
    assert [name for name, _ in materializers] == ["skills", "instructions"]
    assert (u_root / SKILLS_MARKER).read_text() == lc.library_hash()
    assert (u_root / CONNECTED_MARKER).read_text() == "gmail"
    assert (u_root / INSTRUCTIONS_MARKER).exists()


async def test_an_unchanged_signature_does_no_work_on_the_second_call(
    mount: Path, materializers: list[tuple[str, Any]], instructions_source: dict[str, str]
) -> None:
    # Steady-state chat turns must be zero-I/O; a broken gate rewrites the whole
    # catalog on every turn.
    await lc.materialize_user_integrations(USER, {"gmail"})
    materializers.clear()
    await lc.materialize_user_integrations(USER, {"gmail"})
    assert materializers == []


async def test_connecting_an_integration_forces_a_rewrite(
    mount: Path, materializers: list[tuple[str, Any]], instructions_source: dict[str, str]
) -> None:
    # The `.connected` markers the agent prompt reads are written here — a gate
    # that only watched the library hash would leave the new integration
    # invisible to the agent until an unrelated deploy.
    await lc.materialize_user_integrations(USER, {"gmail"})
    materializers.clear()
    await lc.materialize_user_integrations(USER, {"gmail", "linear"})
    assert ("skills", {"gmail", "linear"}) in materializers
    assert (mount / "users" / USER / CONNECTED_MARKER).read_text() == "gmail,linear"


async def test_disconnecting_an_integration_forces_a_rewrite(
    mount: Path, materializers: list[tuple[str, Any]], instructions_source: dict[str, str]
) -> None:
    await lc.materialize_user_integrations(USER, {"gmail", "linear"})
    materializers.clear()
    await lc.materialize_user_integrations(USER, {"gmail"})
    assert ("skills", {"gmail"}) in materializers


async def test_edited_instructions_force_a_rewrite(
    mount: Path, materializers: list[tuple[str, Any]], instructions_source: dict[str, str]
) -> None:
    instructions_source["gmail"] = "always cc legal"
    await lc.materialize_user_integrations(USER, {"gmail"})
    before = (mount / "users" / USER / INSTRUCTIONS_MARKER).read_text()
    materializers.clear()

    instructions_source["gmail"] = "never cc legal"
    await lc.materialize_user_integrations(USER, {"gmail"})
    assert ("instructions", {"gmail": "never cc legal"}) in materializers
    assert (mount / "users" / USER / INSTRUCTIONS_MARKER).read_text() != before


async def test_a_new_skill_library_version_forces_a_rewrite(
    mount: Path,
    materializers: list[tuple[str, Any]],
    instructions_source: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deploy that ships a new skill must reach existing users' workspaces.
    await lc.materialize_user_integrations(USER, {"gmail"})
    materializers.clear()
    monkeypatch.setattr(lc, "library_hash", lambda: "deadbeef")
    await lc.materialize_user_integrations(USER, {"gmail"})
    assert [name for name, _ in materializers] == ["skills", "instructions"]
    assert (mount / "users" / USER / SKILLS_MARKER).read_text() == "deadbeef"


async def test_a_failed_materialization_leaves_the_markers_unstamped(
    mount: Path, instructions_source: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Markers must be stamped AFTER the writers succeed. Stamping first would
    # permanently convince the gate that a half-written catalog is up to date.
    def boom(user_root: Path, connected: set[str]) -> int:
        raise OSError("mount went read-only")

    monkeypatch.setattr(lc, "materialize_skills", boom)
    with pytest.raises(OSError, match="read-only"):
        await lc.materialize_user_integrations(USER, {"gmail"})
    assert not (mount / "users" / USER / SKILLS_MARKER).exists()
    assert not (mount / "users" / USER / CONNECTED_MARKER).exists()


async def test_materialization_writes_nothing_when_the_mount_is_gone(
    mount: Path,
    materializers: list[tuple[str, Any]],
    instructions_source: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_mounted(monkeypatch, False)
    await lc.materialize_user_integrations(USER, {"gmail"})
    assert materializers == []
    assert not (mount / "users" / USER).exists()


# ── provision_user_workspace ─────────────────────────────────────────


@pytest.fixture
def linker(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def link(user_id: str) -> int:
        calls.append(user_id)
        return 0

    monkeypatch.setattr(
        "app.services.storage.system_workspace.link_system_files_into_workspace", link
    )
    return calls


async def test_provisioning_links_system_files_and_materializes_the_catalog(
    mount: Path,
    linker: list[str],
    materializers: list[tuple[str, Any]],
    instructions_source: dict[str, str],
) -> None:
    await lc.provision_user_workspace(USER, {"gmail"})
    assert linker == [USER]
    assert ("skills", {"gmail"}) in materializers


async def test_provisioning_without_a_connected_set_materializes_an_empty_one(
    mount: Path,
    linker: list[str],
    materializers: list[tuple[str, Any]],
    instructions_source: dict[str, str],
) -> None:
    # Registration calls this before any integration exists; a None reaching
    # `sorted()` would crash the signup path.
    await lc.provision_user_workspace(USER)
    assert ("skills", set()) in materializers
    assert (mount / "users" / USER / CONNECTED_MARKER).read_text() == ""


async def test_provisioning_schedules_a_sync_for_every_workspace_area(
    linker: list[str],
    materializers: list[tuple[str, Any]],
    instructions_source: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each registered area is told WHOSE workspace to resync — a None here
    # schedules nothing observable and the projection silently never lands.
    scheduled: list[str | None] = []
    monkeypatch.setattr(
        "app.services.workspace_areas.all_areas",
        lambda: (SimpleNamespace(schedule_sync=scheduled.append),),
    )

    await lc.provision_user_workspace(USER)

    assert scheduled == [USER]
