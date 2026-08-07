"""Shared ``_system`` subtree + per-user symlinks: isolation, hash-gating, linking.

``_system`` is the ONE copy of INDEX.md / the GUIDE.md docs / builtin skill bodies
that every user's workspace points at. Two failure classes matter here and neither
shows up in logs:

  - **isolation** — a link written for user A landing in the shared tree (or in
    user B's tree) corrupts the single copy for everyone, and ``_place_symlink``
    deliberately ``unlink()``s whatever it finds, so the real body is destroyed.
  - **hash-gating** — the signature marker is what makes bootstrap cheap. If it
    short-circuits when it shouldn't, users get stale docs forever; if it fails to
    short-circuit, every bootstrap rewrites the whole library on JuiceFS.

The filesystem IS the thing under test, so ``tmp_path`` is used as a real mount
root rather than mocking ``Path``. Mocked boundaries: the mount-detection
primitives in ``juicefs`` and the ``system_files()`` manifest.

Note on patching: ``system_workspace`` does ``from ...juicefs import _mount_root``,
so it holds its OWN reference — patching ``juicefs._mount_root`` alone does not
reach ``system_subtree_available()``. Both bindings are patched below.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.agents.workspace.system_files import SystemFile
from app.services.storage import system_workspace as sw
from app.services.storage.juicefs import JuiceFSUnavailable
from app.services.storage.system_workspace import (
    SANDBOX_SYSTEM_DIR,
    SYSTEM_SUBDIR,
    _library_signature,
    _link_location,
    _link_target,
    _place_symlink,
    _prune_orphan_system_files,
    _write_system_files,
    ensure_system_subtree,
    link_system_files_into_workspace,
    system_subtree_available,
)

pytestmark = pytest.mark.unit

USER = "u1"
OTHER_USER = "u2"

MANIFEST: list[SystemFile] = [
    SystemFile("INDEX.md", "index body"),
    SystemFile("sessions/GUIDE.md", "sessions body"),
    SystemFile("skills/writing/SKILL.md", "writing skill body"),
]


@pytest.fixture
def mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real directory standing in for the JuiceFS host mount."""
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr("app.services.storage.juicefs._mount_root", lambda: root)
    # is_mount() is False for a tmpdir; without this every helper short-circuits
    # on JuiceFSUnavailable and the guards under test are never reached.
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    monkeypatch.setattr(sw, "_mount_root", lambda: root)
    return root


@pytest.fixture
def manifest(monkeypatch: pytest.MonkeyPatch) -> list[SystemFile]:
    """Pin the system-file library so signatures and link counts are deterministic."""
    files = list(MANIFEST)
    monkeypatch.setattr(sw, "system_files", lambda: files)
    return files


def unmount(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: False)


def age(path: Path) -> None:
    """Backdate mtime so any rewrite of ``path`` becomes observable."""
    os.utime(path, (0, 0))


def untouched(path: Path) -> bool:
    return path.stat().st_mtime == 0


# ── _library_signature ───────────────────────────────────────────────


def test_the_signature_ignores_the_order_files_arrive_in() -> None:
    # system_files() builds its list by iterating load_builtin_skills(); if the
    # signature were order-sensitive, a reordered skill set would look like a
    # content change and rewrite the whole library on every bootstrap.
    forward = _library_signature(MANIFEST)
    assert _library_signature(list(reversed(MANIFEST))) == forward


def test_editing_one_body_changes_the_signature() -> None:
    # This is the entire point of the marker — a doc edit that does not move the
    # signature ships stale INDEX.md/GUIDE.md to every user, permanently.
    edited = [SystemFile(MANIFEST[0].rel_path, "edited"), *MANIFEST[1:]]
    assert _library_signature(edited) != _library_signature(MANIFEST)


def test_a_path_body_boundary_shift_is_not_hashed_as_the_same_library() -> None:
    # Without the NUL separators, ("a", "b") and ("ab", "") both hash "ab" and a
    # real library change is invisible to the gate. Catches a dropped delimiter.
    a = _library_signature([SystemFile("a", "b")])
    b = _library_signature([SystemFile("ab", "")])
    assert a != b


def test_adding_a_file_changes_the_signature() -> None:
    # A newly-added builtin skill must trigger a rewrite, not be swallowed.
    grown = [*MANIFEST, SystemFile("memory/GUIDE.md", "memory body")]
    assert _library_signature(grown) != _library_signature(MANIFEST)


def test_the_signature_is_a_32_char_hex_marker() -> None:
    # The marker is compared as text; a truncation change would silently widen
    # collisions between libraries.
    sig = _library_signature(MANIFEST)
    assert len(sig) == 32
    assert set(sig) <= set("0123456789abcdef")


# ── _write_system_files ──────────────────────────────────────────────


def test_writing_creates_missing_parent_directories(tmp_path: Path) -> None:
    # "sessions/GUIDE.md" and "skills/writing/SKILL.md" are nested; without
    # parents=True the first bootstrap dies on FileNotFoundError.
    _write_system_files(tmp_path, MANIFEST)

    assert (tmp_path / "INDEX.md").read_text() == "index body"
    assert (tmp_path / "sessions/GUIDE.md").read_text() == "sessions body"
    assert (tmp_path / "skills/writing/SKILL.md").read_text() == "writing skill body"


def test_a_body_that_drifted_on_disk_is_rewritten(tmp_path: Path) -> None:
    # A partially-written or externally-clobbered body must be repaired once the
    # writer runs, otherwise the shared copy serves corrupt content to everyone.
    stale = tmp_path / "INDEX.md"
    stale.write_text("corrupted")

    _write_system_files(tmp_path, MANIFEST)

    assert stale.read_text() == "index body"


def test_an_already_correct_body_is_not_rewritten(tmp_path: Path) -> None:
    # Steady state must do zero writes — this runs on every bootstrap against
    # JuiceFS. An inverted compare turns it into a full library rewrite each boot.
    _write_system_files(tmp_path, MANIFEST)
    target = tmp_path / "INDEX.md"
    age(target)

    _write_system_files(tmp_path, MANIFEST)

    assert untouched(target), "an unchanged body was rewritten"


# ── _prune_orphan_system_files ───────────────────────────────────────


def test_a_file_no_longer_in_the_manifest_is_deleted(tmp_path: Path) -> None:
    # A builtin skill that gets removed must stop being readable in-sandbox;
    # otherwise deleted docs linger in the shared tree forever.
    _write_system_files(tmp_path, MANIFEST)
    orphan = tmp_path / "skills" / "retired" / "SKILL.md"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("removed skill")

    _prune_orphan_system_files(tmp_path, MANIFEST)

    assert not orphan.exists()


def test_pruning_keeps_every_file_the_manifest_still_lists(tmp_path: Path) -> None:
    # An over-eager prune wipes the live library — the symlinks all still point
    # at it, so every user's docs go missing at once.
    _write_system_files(tmp_path, MANIFEST)

    _prune_orphan_system_files(tmp_path, MANIFEST)

    for f in MANIFEST:
        assert (tmp_path / f.rel_path).read_text() == f.body


def test_pruning_spares_the_hash_marker(tmp_path: Path) -> None:
    # The marker is not in the manifest. Deleting it mid-run would leave the
    # subtree unversioned and force a full rewrite on the next bootstrap.
    _write_system_files(tmp_path, MANIFEST)
    marker = tmp_path / ".gaia_system.v"
    marker.write_text("deadbeef")

    _prune_orphan_system_files(tmp_path, MANIFEST)

    assert marker.read_text() == "deadbeef"


def test_pruning_removes_an_orphan_beside_a_kept_file(tmp_path: Path) -> None:
    # Orphan detection is per-file, not per-directory: a stale body sharing a
    # directory with a live one must still go.
    _write_system_files(tmp_path, MANIFEST)
    orphan = tmp_path / "sessions" / "OLD.md"
    orphan.write_text("stale")

    _prune_orphan_system_files(tmp_path, MANIFEST)

    assert not orphan.exists()
    assert (tmp_path / "sessions/GUIDE.md").read_text() == "sessions body"


# ── ensure_system_subtree ────────────────────────────────────────────


async def test_an_unmounted_host_reports_the_subtree_as_not_written(
    mount: Path, manifest: list[SystemFile], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Native dev has no /mnt/jfs. Returning True there would make callers believe
    # the shared copy exists and skip the per-user fallback entirely.
    unmount(monkeypatch)

    assert await ensure_system_subtree() is False
    assert not (mount / SYSTEM_SUBDIR).exists()


async def test_the_first_bootstrap_writes_the_library_and_stamps_the_signature(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # The marker must record the signature of what was actually written — a
    # mismatch makes every later bootstrap rewrite the whole library.
    assert await ensure_system_subtree() is True

    root = mount / SYSTEM_SUBDIR
    for f in MANIFEST:
        assert (root / f.rel_path).read_text() == f.body
    assert (root / ".gaia_system.v").read_text() == _library_signature(MANIFEST)


async def test_a_second_bootstrap_touches_nothing(mount: Path, manifest: list[SystemFile]) -> None:
    # "Safe to call on every bootstrap" is a JuiceFS I/O claim. If the marker
    # compare is inverted, every worker start rewrites the full library.
    await ensure_system_subtree()
    root = mount / SYSTEM_SUBDIR
    for f in MANIFEST:
        age(root / f.rel_path)
    age(root / ".gaia_system.v")

    assert await ensure_system_subtree() is True

    assert all(untouched(root / f.rel_path) for f in MANIFEST)
    assert untouched(root / ".gaia_system.v")


async def test_a_marker_with_trailing_whitespace_still_counts_as_current(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # A marker round-tripped through an editor or a shell `echo` gains a newline.
    # Without the strip() it never matches and the library is rewritten forever.
    # Asserted on the MARKER, not the bodies: an unchanged library rewrites its
    # bodies to identical content, so only the marker losing its newline reveals
    # that the gate missed.
    await ensure_system_subtree()
    root = mount / SYSTEM_SUBDIR
    marker = root / ".gaia_system.v"
    marker.write_text(f"{_library_signature(MANIFEST)}\n")

    assert await ensure_system_subtree() is True

    assert marker.read_text().endswith("\n"), "trailing newline defeated the hash gate"


async def test_a_changed_manifest_rewrites_bodies_and_drops_the_removed_file(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # The signature moving is the ONLY thing that repairs the shared tree. If the
    # gate short-circuits on a changed library, edited docs never reach users.
    await ensure_system_subtree()
    root = mount / SYSTEM_SUBDIR
    manifest[:] = [SystemFile("INDEX.md", "v2 index"), MANIFEST[1]]

    assert await ensure_system_subtree() is True

    assert (root / "INDEX.md").read_text() == "v2 index"
    assert not (root / "skills/writing/SKILL.md").exists()
    assert (root / ".gaia_system.v").read_text() == _library_signature(manifest)


async def test_a_body_corrupted_under_a_matching_marker_is_left_alone(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # Documents the deliberate trade: the marker is trusted, so content drift is
    # NOT self-healing. If this ever flips, the "zero I/O steady state" promise
    # in the docstring is gone.
    await ensure_system_subtree()
    corrupted = mount / SYSTEM_SUBDIR / "INDEX.md"
    corrupted.write_text("corrupted")

    assert await ensure_system_subtree() is True

    assert corrupted.read_text() == "corrupted"


async def test_a_regular_file_squatting_on_the_system_path_degrades_to_false(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # JuiceFS I/O faults must not crash the worker — the OSError handler has to
    # swallow-and-report, and it must report False so callers fall back to copies.
    (mount / SYSTEM_SUBDIR).write_text("not a directory")

    assert await ensure_system_subtree() is False


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
async def test_an_unwritable_mount_root_degrades_to_false(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # A read-only JuiceFS mount (storage backend unreachable) raises
    # PermissionError, an OSError — the bootstrap must report failure, not raise.
    mount.chmod(0o500)
    try:
        assert await ensure_system_subtree() is False
    finally:
        mount.chmod(0o700)


async def test_concurrent_bootstraps_all_succeed_on_one_subtree(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # Every worker process runs this at startup. Without exist_ok the losers of
    # the mkdir race raise FileExistsError and their bootstrap reports failure.
    results = await asyncio.gather(*(ensure_system_subtree() for _ in range(5)))

    assert results == [True] * 5
    root = mount / SYSTEM_SUBDIR
    assert (root / ".gaia_system.v").read_text() == _library_signature(MANIFEST)
    assert (root / "INDEX.md").read_text() == "index body"


# ── system_subtree_available ─────────────────────────────────────────


def test_the_subtree_is_available_once_it_exists_as_a_directory(mount: Path) -> None:
    (mount / SYSTEM_SUBDIR).mkdir()
    assert system_subtree_available() is True


def test_a_missing_subtree_is_not_available(mount: Path) -> None:
    assert system_subtree_available() is False


def test_a_regular_file_named_system_is_not_a_usable_subtree(mount: Path) -> None:
    # An exists() check here would report a squatting file as a working subtree,
    # and every link attempt would then blow up inside the linking thread.
    (mount / SYSTEM_SUBDIR).write_text("nope")
    assert system_subtree_available() is False


def test_an_exploding_mount_lookup_reports_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Misconfigured settings must not take down bootstrap — the caller only needs
    # to know it should fall back to per-user copies.
    def boom() -> Path:
        raise RuntimeError("JUICEFS_HOST_MOUNT_PATH unset")

    monkeypatch.setattr(sw, "_mount_root", boom)
    assert system_subtree_available() is False


# ── _link_target / _link_location ────────────────────────────────────


def test_the_link_target_is_the_in_sandbox_path_not_a_host_path() -> None:
    # These symlinks are read by bash INSIDE the sandbox. A host path
    # (/mnt/jfs/_system/...) does not exist there and every cat/grep breaks.
    assert _link_target("sessions/GUIDE.md") == f"{SANDBOX_SYSTEM_DIR}/sessions/GUIDE.md"
    assert _link_target("sessions/GUIDE.md").startswith("/workspace/")


def test_a_skill_body_links_into_the_skills_overlay_subtree(mount: Path) -> None:
    # /workspace/skills is a SEPARATE JuiceFS subtree (/skills/<uid>). Placing the
    # link under users/<uid>/skills instead puts it where nothing ever reads it.
    assert _link_location(USER, "skills/writing/SKILL.md") == (
        mount / "skills" / USER / "writing" / "SKILL.md"
    )


def test_a_non_skill_doc_links_under_the_users_subtree(mount: Path) -> None:
    assert _link_location(USER, "sessions/GUIDE.md") == (
        mount / "users" / USER / "sessions" / "GUIDE.md"
    )


# ── _place_symlink ───────────────────────────────────────────────────


def test_placing_a_link_where_nothing_exists_creates_it(tmp_path: Path) -> None:
    link = tmp_path / "nested" / "INDEX.md"

    assert _place_symlink(link, f"{SANDBOX_SYSTEM_DIR}/INDEX.md") is True

    assert link.is_symlink()
    assert link.readlink() == Path(f"{SANDBOX_SYSTEM_DIR}/INDEX.md")


def test_an_already_correct_link_is_reported_as_unchanged(tmp_path: Path) -> None:
    # These links are deliberately DANGLING on the host (/workspace does not
    # exist there), so exists() is False for them. Checking exists() before
    # is_symlink() would unlink-and-recreate every link on every provisioning
    # pass and report spurious churn.
    target = f"{SANDBOX_SYSTEM_DIR}/INDEX.md"
    link = tmp_path / "INDEX.md"
    _place_symlink(link, target)

    assert _place_symlink(link, target) is False
    assert link.readlink() == Path(target)


def test_a_link_pointing_somewhere_stale_is_repointed(tmp_path: Path) -> None:
    # A renamed skill leaves links aimed at the old path; they must be retargeted,
    # not left dangling at a path that no longer exists in the sandbox.
    link = tmp_path / "SKILL.md"
    link.symlink_to(f"{SANDBOX_SYSTEM_DIR}/skills/old-name/SKILL.md")

    new_target = f"{SANDBOX_SYSTEM_DIR}/skills/writing/SKILL.md"
    assert _place_symlink(link, new_target) is True
    assert link.readlink() == Path(new_target)


def test_a_real_per_user_copy_is_replaced_by_the_link(tmp_path: Path) -> None:
    # This is the whole migration: pre-symlink materializers wrote real copies.
    # Leaving them in place means the de-duplication never happens and edits to
    # the shared docs never reach that user.
    link = tmp_path / "INDEX.md"
    link.write_text("old per-user copy")

    target = f"{SANDBOX_SYSTEM_DIR}/INDEX.md"
    assert _place_symlink(link, target) is True
    assert link.is_symlink()
    assert link.readlink() == Path(target)


# ── link_system_files_into_workspace ─────────────────────────────────


async def test_no_links_are_written_when_the_shared_subtree_is_missing(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # Without the shared copy the symlinks would dangle inside the sandbox too.
    # Returning 0 is what makes the copy-writers take over.
    assert await link_system_files_into_workspace(USER) == 0
    assert not (mount / "users").exists()


async def test_every_system_file_gets_a_link_in_the_users_workspace(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # A dropped link means that doc is invisible to in-sandbox bash for that user.
    await ensure_system_subtree()

    assert await link_system_files_into_workspace(USER) == len(MANIFEST)

    assert (mount / "users" / USER / "INDEX.md").is_symlink()
    assert (mount / "users" / USER / "sessions" / "GUIDE.md").is_symlink()
    assert (mount / "skills" / USER / "writing" / "SKILL.md").is_symlink()


async def test_relinking_an_already_linked_workspace_changes_nothing(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # provision_user_workspace runs on registration, every integration toggle and
    # every startup. A non-zero steady-state count means it churns JuiceFS —
    # and, because the links dangle host-side, it is the easiest thing to get wrong.
    await ensure_system_subtree()
    await link_system_files_into_workspace(USER)

    assert await link_system_files_into_workspace(USER) == 0


async def test_linking_a_user_never_writes_into_the_shared_tree(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # The isolation invariant. _place_symlink unlinks whatever it finds, so a
    # link mistakenly aimed at _system destroys the single shared body for EVERY
    # user — and the hash marker then blocks ensure_system_subtree from repairing it.
    await ensure_system_subtree()

    await link_system_files_into_workspace(USER)

    system_root = mount / SYSTEM_SUBDIR
    for f in MANIFEST:
        body = system_root / f.rel_path
        assert not body.is_symlink(), f"shared body {f.rel_path} was replaced by a link"
        assert body.read_text() == f.body
    assert not (system_root / "users").exists()


async def test_one_users_links_never_appear_in_another_users_tree(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # Cross-user leakage: the per-user path is built from user_id, and a base that
    # ignored it would give every user a view of one shared workspace.
    await ensure_system_subtree()

    await link_system_files_into_workspace(USER)

    assert not (mount / "users" / OTHER_USER).exists()
    assert not (mount / "skills" / OTHER_USER).exists()


async def test_a_vanished_mount_under_an_existing_subtree_fails_loud(
    mount: Path, manifest: list[SystemFile], monkeypatch: pytest.MonkeyPatch
) -> None:
    # system_subtree_available() only stats a directory — it does NOT check the
    # mount. If the mount drops after that check, the linker must raise rather
    # than return 0, which would look like a successful no-op provisioning.
    await ensure_system_subtree()
    unmount(monkeypatch)

    with pytest.raises(JuiceFSUnavailable):
        await link_system_files_into_workspace(USER)


# ── user_id containment ──────────────────────────────────────────────


async def test_a_traversing_user_id_cannot_overwrite_the_shared_system_tree(
    mount: Path, manifest: list[SystemFile]
) -> None:
    # `_place_symlink` unlinks whatever it finds before linking, so a user_id
    # that escapes /users/<uid> does not merely write somewhere odd — it DESTROYS
    # the single shared copy every other user's workspace points at, and the hash
    # marker then blocks ensure_system_subtree from ever repairing it.
    await ensure_system_subtree()
    victim = mount / SYSTEM_SUBDIR / "INDEX.md"
    assert victim.read_text() == "index body"

    with pytest.raises(ValueError, match="user_id"):
        await link_system_files_into_workspace(f"../{SYSTEM_SUBDIR}")

    assert not victim.is_symlink(), "the shared INDEX.md was replaced by a symlink"
    assert victim.read_text() == "index body"


async def test_a_traversing_user_id_cannot_reach_another_users_tree(
    mount: Path, manifest: list[SystemFile]
) -> None:
    await ensure_system_subtree()
    theirs = mount / "users" / OTHER_USER
    (theirs / "sessions").mkdir(parents=True)
    (theirs / "INDEX.md").write_text("their own copy")

    with pytest.raises(ValueError, match="user_id"):
        await link_system_files_into_workspace(f"../users/{OTHER_USER}")

    assert (theirs / "INDEX.md").read_text() == "their own copy"


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "../x", "/etc", "u\x00", "x" * 300])
async def test_an_unsafe_user_id_is_refused_before_any_write(
    mount: Path, manifest: list[SystemFile], bad: str
) -> None:
    await ensure_system_subtree()
    before = sorted(p.relative_to(mount).as_posix() for p in mount.rglob("*"))

    with pytest.raises(ValueError, match="user_id"):
        await link_system_files_into_workspace(bad)

    assert sorted(p.relative_to(mount).as_posix() for p in mount.rglob("*")) == before
