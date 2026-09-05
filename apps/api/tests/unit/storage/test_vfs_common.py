"""Shared VFS helpers: naming, hash gates, markers, and the write/skip decision.

Every materializer under ``/workspace/`` (gaia-tasks, user-todos, memory,
skills) is built on this module, so a bug here is systemic and invisible: the
hash gates decide whether a user's edit ever reaches disk, and ``matches_text``
decides whether a file is rewritten. Get either wrong and you either serve a
silently stale projection or rewrite the whole tree on every single turn.

Nothing is mocked — these helpers *are* path and I/O logic, so the tests drive
real files under ``tmp_path``. Mocking the filesystem here would delete the only
part worth testing.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.services.storage._vfs_common import (
    READONLY_MODE,
    RW_MODE,
    SHORTID_LEN,
    SLUG_MAX_LEN,
    catalog_signature,
    folder_name,
    hash_bodies_with_meta,
    hash_meta_only,
    matches_text,
    meta_body,
    per_doc_marker_path,
    prune_per_doc_markers,
    read_marker,
    remove_tree,
    short_id,
    slugify,
    updated_at_key,
    write_marker,
    write_readonly_body,
    write_rw_body,
    write_rw_if_changed,
)

DOC_ID = "6512ab34cd56ef7890123456"

not_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses permission bits, so the unreadable cases cannot occur"
)


def mode_of(path: Path) -> int:
    return path.stat().st_mode & 0o777


# ── slugify ──────────────────────────────────────────────────────────


def test_a_title_becomes_a_lowercase_dashed_slug() -> None:
    assert slugify("Ship the Q3 Report!") == "ship-the-q3-report"


def test_a_run_of_punctuation_collapses_to_a_single_dash() -> None:
    # Without collapsing, "a -- b" yields "a---b" and the folder name drifts
    # from the one the previous sync wrote, orphaning the whole task folder.
    assert slugify("a -- b") == "a-b"


@pytest.mark.parametrize(
    "title",
    [None, "", "   ", "---", "!!!", "日本語", "\n\t"],
    ids=["none", "empty", "whitespace", "dashes", "punctuation", "non-ascii", "control"],
)
def test_a_title_with_no_usable_characters_falls_back_to_untitled(title: str | None) -> None:
    # Every fallback here guards a folder named "" or "-<shortid>". A leading
    # dash makes the directory hidden-ish and hostile to shell globs, and an
    # empty slug collides across every untitled task of the same user.
    assert slugify(title) == "untitled"


def test_a_long_title_is_truncated_to_the_slug_limit() -> None:
    # Folder names feed into JuiceFS paths; an unbounded title would blow the
    # per-component name limit and the whole sync would raise for that user.
    assert len(slugify("x" * 200)) == SLUG_MAX_LEN


def test_a_title_truncated_mid_word_does_not_end_in_a_dash() -> None:
    # The 40-char cut lands exactly on the separator here. Keeping it produces
    # "xxx…x--6512ab34" — a double dash the previous sync never wrote, so the
    # old folder is orphaned and the task is duplicated on disk.
    assert slugify("x" * 39 + " tail") == "x" * 39


def test_accented_characters_are_dropped_rather_than_passed_through() -> None:
    # Non-ascii bytes in a path are a portability hazard across the FUSE mount;
    # the slug alphabet is deliberately [a-z0-9-] only.
    assert slugify("Café ☕ Meeting") == "caf-meeting"


# ── short_id / folder_name ───────────────────────────────────────────


def test_a_short_id_is_the_entropy_bearing_TAIL_not_the_timestamp_head() -> None:
    # The head is an ObjectId's 4-byte timestamp: identical for every doc
    # minted in the same second, so two same-second docs with alike titles
    # collapsed into one folder and overwrote each other permanently.
    assert short_id(DOC_ID) == DOC_ID[-SHORTID_LEN:] == "90123456"
    assert short_id(DOC_ID) != DOC_ID[:SHORTID_LEN]


def test_a_doc_id_shorter_than_the_shortid_length_is_used_whole() -> None:
    # A seeded/test doc with a short id must not raise or produce a padded name.
    assert short_id("abc") == "abc"


def test_a_folder_name_joins_the_slug_and_the_short_id() -> None:
    assert folder_name(DOC_ID, "Ship It") == "ship-it-90123456"


def test_two_tasks_sharing_a_title_get_distinct_folders() -> None:
    # This is the entire reason the shortid exists. Drop it and two same-titled
    # tasks project into one folder — the second silently overwrites the first
    # and the user loses a task's canvas.
    a = folder_name("aaaaaaaa1111", "Weekly Review")
    b = folder_name("bbbbbbbb2222", "Weekly Review")
    assert a != b


# ── hash_meta_only ───────────────────────────────────────────────────


def test_a_meta_hash_is_a_sha256_hex_digest() -> None:
    # Catches a helper that returns the payload itself; the digest is written
    # into a marker file and compared as a whole string.
    digest = hash_meta_only({"title": "x"})
    assert len(digest) == 64
    assert int(digest, 16) >= 0


def test_the_same_meta_in_a_different_key_order_hashes_the_same() -> None:
    # Mongo does not promise field order. Without canonical ordering every doc
    # looks changed on every sync and the whole tree is rewritten each turn.
    assert hash_meta_only({"title": "a", "completed": False}) == hash_meta_only(
        {"completed": False, "title": "a"}
    )


def test_a_nested_dict_in_a_different_key_order_hashes_the_same() -> None:
    # Subtasks are nested dicts; canonicalization has to reach them too.
    assert hash_meta_only({"subtasks": [{"id": "1", "title": "t"}]}) == hash_meta_only(
        {"subtasks": [{"title": "t", "id": "1"}]}
    )


def test_a_changed_meta_value_changes_the_hash() -> None:
    # The marker gate is this hash. If it does not move, a completed task keeps
    # showing as open on disk forever.
    assert hash_meta_only({"completed": False}) != hash_meta_only({"completed": True})


def test_a_datetime_in_meta_is_hashed_by_value_rather_than_raising() -> None:
    # meta carries created_at/updated_at/due_date straight from Mongo. A plain
    # json.dumps raises TypeError on these and kills every sync.
    early = hash_meta_only({"updated_at": datetime(2026, 8, 3, 10, 0, tzinfo=UTC)})
    later = hash_meta_only({"updated_at": datetime(2026, 8, 3, 11, 0, tzinfo=UTC)})
    assert early != later


# ── hash_bodies_with_meta ────────────────────────────────────────────


def test_moving_text_between_bodies_changes_the_body_hash() -> None:
    # Concatenation without a separator makes ["ab", ""] and ["a", "b"]
    # identical: the agent moves a line between facet bodies, the hash does
    # not move, and neither file is ever rewritten.
    meta: dict[str, Any] = {"title": "t"}
    assert hash_bodies_with_meta(["ab", ""], meta) != hash_bodies_with_meta(["a", "b"], meta)


def test_the_same_bodies_and_meta_hash_identically() -> None:
    meta: dict[str, Any] = {"title": "t"}
    first = hash_bodies_with_meta(["c", "l"], meta)
    second = hash_bodies_with_meta(["c", "l"], meta)
    assert first == second


def test_the_body_hash_is_the_sha256_of_nul_framed_bodies_and_canonical_meta() -> None:
    # The digest is not internal state — it is written into a marker file that
    # outlives the release, and the framing byte is what keeps ["ab", ""] and
    # ["a", "b"] apart. NUL is the one byte a facet body can never carry, so any
    # other framing is forgeable by the agent's own text; changing it at all
    # invalidates every marker on disk and rewrites every user's tree.
    meta: dict[str, Any] = {"title": "t"}
    expected = hashlib.sha256(
        b"c\x00l\x00" + json.dumps(meta, sort_keys=True).encode("utf-8")
    ).hexdigest()

    assert hash_bodies_with_meta(["c", "l"], meta) == expected


def test_a_metadata_only_edit_still_changes_the_body_hash() -> None:
    # Renaming a task touches neither facet body; if meta is left out of the
    # digest the folder keeps the old title in meta.json indefinitely.
    assert hash_bodies_with_meta(["c", "l"], {"title": "old"}) != hash_bodies_with_meta(
        ["c", "l"], {"title": "new"}
    )


def test_the_body_hash_of_an_empty_task_is_still_stable() -> None:
    first = hash_bodies_with_meta([], {})
    second = hash_bodies_with_meta([], {})
    assert first == second


# ── catalog_signature ────────────────────────────────────────────────


def test_the_catalog_signature_ignores_the_order_docs_arrive_in() -> None:
    # Mongo returns docs in query order. An order-sensitive signature would
    # trigger a full re-materialization on an unrelated reordering.
    assert catalog_signature({"a": "1", "b": "2"}) == catalog_signature({"b": "2", "a": "1"})


def test_one_docs_signature_changing_changes_the_catalog_signature() -> None:
    # This gate short-circuits the entire sync. If it misses a per-doc change,
    # the user edits a task and nothing at all reaches the workspace.
    assert catalog_signature({"a": "1", "b": "2"}) != catalog_signature({"a": "1", "b": "3"})


def test_adding_a_doc_changes_the_catalog_signature() -> None:
    assert catalog_signature({"a": "1"}) != catalog_signature({"a": "1", "b": "2"})


def test_removing_a_doc_changes_the_catalog_signature() -> None:
    # Otherwise a deleted task's folder is never pruned from the workspace.
    assert catalog_signature({"a": "1", "b": "2"}) != catalog_signature({"a": "1"})


def test_an_empty_catalog_has_a_stable_signature() -> None:
    # A user with zero active tasks must still get a comparable marker rather
    # than a crash on the first sync.
    first = catalog_signature({})
    second = catalog_signature({})
    assert first == second
    assert len(first) == 64


# ── read_marker / write_marker ───────────────────────────────────────


def test_a_written_marker_reads_back_as_the_same_value(tmp_path: Path) -> None:
    # The round trip is the gate: writer and reader disagreeing by one
    # character means every sync believes the tree is stale.
    sig = hash_meta_only({"title": "t"})
    marker = tmp_path / ".gaia" / "gaia-tasks.v"
    write_marker(marker, sig)
    assert read_marker(marker) == sig


def test_write_marker_creates_the_missing_marker_directory(tmp_path: Path) -> None:
    # `.gaia/` does not exist before a user's first sync ever runs.
    marker = tmp_path / "deep" / "nested" / ".gaia" / "todos.v"
    write_marker(marker, "sig")
    assert marker.read_text(encoding="utf-8") == "sig"


def test_rewriting_a_marker_leaves_none_of_the_previous_value(tmp_path: Path) -> None:
    # A partial overwrite would leave a longer old digest with a new prefix,
    # which compares unequal forever and re-materializes on every turn.
    marker = tmp_path / "m.v"
    write_marker(marker, "a" * 64)
    write_marker(marker, "short")
    assert marker.read_text(encoding="utf-8") == "short"


def test_a_marker_with_a_trailing_newline_still_equals_the_bare_signature(
    tmp_path: Path,
) -> None:
    # Anything that touches the file through an editor or shell adds a newline.
    # Comparing it raw would permanently invalidate the gate for that user.
    marker = tmp_path / "m.v"
    marker.write_text("deadbeef\n", encoding="utf-8")
    assert read_marker(marker) == "deadbeef"


def test_a_missing_marker_reads_as_none(tmp_path: Path) -> None:
    assert read_marker(tmp_path / "never-written.v") is None


def test_an_empty_marker_file_reads_as_none_rather_than_empty_string(tmp_path: Path) -> None:
    # A truncated marker (crash mid-write) must read as "no marker" so the next
    # sync rebuilds, not as a value that could equal an empty signature.
    marker = tmp_path / "m.v"
    marker.write_text("", encoding="utf-8")
    assert read_marker(marker) is None


def test_a_whitespace_only_marker_reads_as_none(tmp_path: Path) -> None:
    marker = tmp_path / "m.v"
    marker.write_text("  \n ", encoding="utf-8")
    assert read_marker(marker) is None


def test_a_marker_holding_invalid_utf8_reads_as_none_instead_of_raising(tmp_path: Path) -> None:
    # Corruption on the FUSE mount must degrade to "rebuild it", not raise out
    # of the sync and wedge the user's workspace on every subsequent turn.
    marker = tmp_path / "m.v"
    marker.write_bytes(b"\xff\xfe\x00garbage")
    assert read_marker(marker) is None


def test_a_directory_where_a_marker_belongs_reads_as_none_instead_of_raising(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "m.v"
    marker.mkdir()
    assert read_marker(marker) is None


@not_root
def test_an_unreadable_marker_reads_as_none_instead_of_raising(tmp_path: Path) -> None:
    marker = tmp_path / "m.v"
    marker.write_text("sig", encoding="utf-8")
    marker.chmod(0o000)
    try:
        assert read_marker(marker) is None
    finally:
        marker.chmod(RW_MODE)


def test_a_broken_symlink_marker_reads_as_none(tmp_path: Path) -> None:
    marker = tmp_path / "m.v"
    marker.symlink_to(tmp_path / "gone")
    assert read_marker(marker) is None


# ── per_doc_marker_path / prune_per_doc_markers ──────────────────────


def test_a_per_doc_marker_is_named_for_its_doc_id(tmp_path: Path) -> None:
    assert per_doc_marker_path(tmp_path, DOC_ID) == tmp_path / f"{DOC_ID}.v"


def test_pruning_removes_the_marker_of_a_doc_that_left_the_active_set(tmp_path: Path) -> None:
    # A stale marker makes a resurrected doc id look already-materialized, so
    # its folder is never written back.
    write_marker(per_doc_marker_path(tmp_path, "gone"), "sig")
    prune_per_doc_markers(tmp_path, {"kept"})
    assert not (tmp_path / "gone.v").exists()


def test_pruning_keeps_the_markers_of_active_docs(tmp_path: Path) -> None:
    # Inverting this condition deletes every live marker each sync, which
    # rewrites every task body on every turn — the exact churn the gate exists
    # to prevent.
    write_marker(per_doc_marker_path(tmp_path, "kept"), "sig")
    prune_per_doc_markers(tmp_path, {"kept"})
    assert (tmp_path / "kept.v").read_text(encoding="utf-8") == "sig"


def test_a_marker_written_through_the_path_helper_is_prunable_by_its_id(tmp_path: Path) -> None:
    # The writer and the pruner have to agree on the filename; if they drift,
    # `.gaia/` grows a marker per doc forever and nothing is ever reclaimed.
    write_marker(per_doc_marker_path(tmp_path, DOC_ID), "sig")
    prune_per_doc_markers(tmp_path, set())
    assert list(tmp_path.iterdir()) == []


def test_pruning_a_directory_that_does_not_exist_yet_is_a_no_op(tmp_path: Path) -> None:
    # Runs before the first materialization has created `.gaia/gaia-tasks/`.
    prune_per_doc_markers(tmp_path / "absent", {"a"})


def test_pruning_leaves_files_that_are_not_markers_alone(tmp_path: Path) -> None:
    # The marker dir sits under `.gaia/`; widening the suffix check would delete
    # sibling state belonging to other materializers.
    other = tmp_path / "notes.json"
    other.write_text("{}", encoding="utf-8")
    prune_per_doc_markers(tmp_path, set())
    assert other.exists()


def test_pruning_leaves_subdirectories_alone(tmp_path: Path) -> None:
    nested = tmp_path / "nested.v"
    nested.mkdir()
    prune_per_doc_markers(tmp_path, set())
    assert nested.is_dir()


# ── remove_tree ──────────────────────────────────────────────────────


def test_a_folder_of_read_only_bodies_is_fully_removed(tmp_path: Path) -> None:
    # Every folder remove_tree is aimed at is full of 0444 bodies. If removal
    # does not go all the way through, a renamed task leaves its old folder
    # behind forever and the workspace accumulates a duplicate copy of every
    # task the user ever renamed.
    folder = tmp_path / "ship-it-6512ab34"
    folder.mkdir()
    write_readonly_body(folder / "canvas.md", "body")
    write_readonly_body(folder / "meta.json", "{}")
    remove_tree(folder)
    assert not folder.exists()


def test_read_only_bodies_nested_several_levels_deep_are_removed(tmp_path: Path) -> None:
    deep = tmp_path / "tree" / "a" / "b"
    deep.mkdir(parents=True)
    write_readonly_body(deep / "log.md", "x")
    remove_tree(tmp_path / "tree")
    assert not (tmp_path / "tree").exists()


def test_removing_a_path_that_does_not_exist_is_a_no_op(tmp_path: Path) -> None:
    remove_tree(tmp_path / "absent")


def test_a_plain_file_is_left_completely_untouched_by_remove_tree(tmp_path: Path) -> None:
    # remove_tree must not even reach shutil.rmtree for a non-directory.
    # Without the is_dir() guard the rmtree failure is routed into the onerror
    # hook, which chmods the path to 0644 on its way to swallowing the error —
    # so a projected 0444 body that landed where a folder was expected silently
    # becomes agent-writable and can be edited out of sync with Mongo.
    stray = tmp_path / "canvas.md"
    write_readonly_body(stray, "body")
    remove_tree(stray)
    assert stray.read_text(encoding="utf-8") == "body"
    assert mode_of(stray) == READONLY_MODE


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: remove_tree on a symlink-to-directory silently chmods the TARGET to 0644, "
        "stripping its execute bit and making the real directory untraversable. "
        "shutil.rmtree refuses the symlink, _force_remove then chmods the path (which "
        "follows the link) and swallows the OSError. _remove_stale_folders reaches this "
        "via child.is_dir(), which follows symlinks. Fix: skip symlinks in remove_tree, "
        "and have _force_remove use 0o755 for directories."
    ),
)
def test_removing_a_symlinked_folder_does_not_break_the_targets_permissions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "memory"
    target.mkdir()
    (target / "facts.md").write_text("kept", encoding="utf-8")
    before = mode_of(target)
    link = tmp_path / "gaia-tasks" / "stray"
    link.parent.mkdir()
    link.symlink_to(target, target_is_directory=True)
    try:
        remove_tree(link)
        assert mode_of(target) == before
        assert (target / "facts.md").read_text(encoding="utf-8") == "kept"
    finally:
        target.chmod(0o755)


# ── matches_text ─────────────────────────────────────────────────────


def test_a_file_holding_exactly_the_expected_text_matches(tmp_path: Path) -> None:
    target = tmp_path / "GUIDE.md"
    target.write_text("# Guide\n", encoding="utf-8")
    assert matches_text(target, "# Guide\n") is True


def test_a_file_holding_different_text_does_not_match(tmp_path: Path) -> None:
    target = tmp_path / "GUIDE.md"
    target.write_text("old", encoding="utf-8")
    assert matches_text(target, "new") is False


def test_a_file_that_does_not_exist_yet_does_not_match(tmp_path: Path) -> None:
    # The first sync depends on this: a missing file has to be reported as
    # "needs writing" rather than raising out of the materializer.
    assert matches_text(tmp_path / "absent.md", "anything") is False


def test_a_missing_trailing_newline_counts_as_a_difference(tmp_path: Path) -> None:
    # A strip()-based comparison would call these equal and leave the file
    # without the newline the projection promises.
    target = tmp_path / "a.md"
    target.write_text("body", encoding="utf-8")
    assert matches_text(target, "body\n") is False


def test_an_empty_file_matches_empty_expected_content(tmp_path: Path) -> None:
    # A falsy-content shortcut here would rewrite every legitimately empty
    # projected body (an unstarted task's log.md) on every single sync.
    target = tmp_path / "log.md"
    target.write_text("", encoding="utf-8")
    assert matches_text(target, "") is True


def test_an_empty_file_does_not_match_non_empty_content(tmp_path: Path) -> None:
    target = tmp_path / "log.md"
    target.write_text("", encoding="utf-8")
    assert matches_text(target, "body") is False


def test_a_file_with_undecodable_bytes_does_not_match(tmp_path: Path) -> None:
    # Corrupted bytes must be rewritten, not raised on — a decode error escaping
    # here wedges the sync for that user until the file is deleted by hand.
    target = tmp_path / "a.md"
    target.write_bytes(b"\xff\xfe\x00")
    assert matches_text(target, "clean") is False


def test_a_directory_where_a_file_belongs_does_not_match(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    target.mkdir()
    assert matches_text(target, "body") is False


@not_root
def test_an_unreadable_file_does_not_match_instead_of_raising(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    target.write_text("body", encoding="utf-8")
    target.chmod(0o000)
    try:
        assert matches_text(target, "body") is False
    finally:
        target.chmod(RW_MODE)


def test_a_symlink_counts_as_matching_even_when_its_target_differs(tmp_path: Path) -> None:
    # System files are de-duplicated as symlinks into the read-only `_system`
    # mount. Treating them as stale replaces the link with a real file and
    # silently un-shares every skill in the user's workspace.
    real = tmp_path / "_system" / "SKILL.md"
    real.parent.mkdir()
    real.write_text("shared body", encoding="utf-8")
    link = tmp_path / "skills" / "SKILL.md"
    link.parent.mkdir()
    link.symlink_to(real)
    assert matches_text(link, "completely different") is True


def test_a_symlink_whose_target_is_absent_still_counts_as_matching(tmp_path: Path) -> None:
    # The `_system` mount does not resolve host-side; the symlink check has to
    # come before any read, or every system file is clobbered on every sync.
    link = tmp_path / "SKILL.md"
    link.symlink_to(tmp_path / "_system" / "SKILL.md")
    assert matches_text(link, "body") is True


def test_a_large_body_is_compared_in_full(tmp_path: Path) -> None:
    # Guards a prefix/chunked comparison: an edit past the first chunk of a long
    # canvas.md would never be written back.
    body = "line of task canvas text\n" * 40_000
    target = tmp_path / "canvas.md"
    target.write_text(body, encoding="utf-8")
    assert matches_text(target, body) is True
    assert matches_text(target, body[:-2] + "X\n") is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: matches_text reads with universal-newline translation, so content "
        "containing CRLF never compares equal to the file that was just written from "
        "it. Every sync rewrites the file and reports it as changed — an unbounded "
        "rewrite loop over the FUSE mount, plus an inflated 'written' count. Reachable "
        "with user/LLM-authored content via memory/projection.py:114 and "
        "storage/sessions/skills.py:72. The mirror image is just as wrong: a file whose "
        "bytes are CRLF is reported as matching LF content and is never normalized. "
        "Fix: compare bytes, or read with newline=''."
    ),
)
def test_content_with_windows_line_endings_is_not_rewritten_on_every_sync(
    tmp_path: Path,
) -> None:
    body = "first line\r\nsecond line\r\n"
    target = tmp_path / "note.md"
    assert write_rw_if_changed(target, body) is True
    assert write_rw_if_changed(target, body) is False


# ── write_readonly_body ──────────────────────────────────────────────


def test_a_projected_body_is_written_read_only(tmp_path: Path) -> None:
    # 0444 is what makes a raw `Edit` from the agent fail loudly instead of
    # silently desyncing the projection from Mongo.
    target = tmp_path / "canvas.md"
    write_readonly_body(target, "body")
    assert target.read_text(encoding="utf-8") == "body"
    assert mode_of(target) == READONLY_MODE


def test_an_edited_task_overwrites_its_own_read_only_body(tmp_path: Path) -> None:
    # Opening a 0444 file for writing raises PermissionError even for its owner,
    # so without the unlink-first step the *second* sync of any task raises and
    # no edit ever reaches the workspace again.
    target = tmp_path / "canvas.md"
    write_readonly_body(target, "original")
    write_readonly_body(target, "edited")
    assert target.read_text(encoding="utf-8") == "edited"
    assert mode_of(target) == READONLY_MODE


def test_a_shortened_body_leaves_none_of_the_previous_content(tmp_path: Path) -> None:
    target = tmp_path / "log.md"
    write_readonly_body(target, "a long first log entry")
    write_readonly_body(target, "short")
    assert target.read_text(encoding="utf-8") == "short"


# ── write_rw_if_changed ──────────────────────────────────────────────


def test_a_missing_file_is_written_and_reported_as_changed(tmp_path: Path) -> None:
    target = tmp_path / "GUIDE.md"
    assert write_rw_if_changed(target, "# Guide\n") is True
    assert target.read_text(encoding="utf-8") == "# Guide\n"
    assert mode_of(target) == RW_MODE


def test_an_unchanged_file_is_not_touched_and_is_reported_as_skipped(tmp_path: Path) -> None:
    # The 0444 mode is the proof, not decoration: if the guard is dropped the
    # write raises PermissionError instead of quietly returning False.
    target = tmp_path / "GUIDE.md"
    target.write_text("# Guide\n", encoding="utf-8")
    target.chmod(READONLY_MODE)
    try:
        assert write_rw_if_changed(target, "# Guide\n") is False
        assert mode_of(target) == READONLY_MODE
    finally:
        target.chmod(RW_MODE)


def test_a_changed_file_is_rewritten_and_reported_as_changed(tmp_path: Path) -> None:
    # An inverted guard here freezes GUIDE.md at whatever the first sync wrote,
    # so the agent keeps reading instructions from a released-ago version.
    target = tmp_path / "GUIDE.md"
    target.write_text("# Old guide\n", encoding="utf-8")
    assert write_rw_if_changed(target, "# New guide\n") is True
    assert target.read_text(encoding="utf-8") == "# New guide\n"


def test_rewriting_with_shorter_content_leaves_no_residue(tmp_path: Path) -> None:
    target = tmp_path / "GUIDE.md"
    target.write_text("# A much longer guide body\n", encoding="utf-8")
    write_rw_if_changed(target, "# Short\n")
    assert target.read_text(encoding="utf-8") == "# Short\n"


def test_a_rewritten_file_is_left_author_writable(tmp_path: Path) -> None:
    # GUIDE/index are deliberately writable; leaving them 0444 would make the
    # next rewrite raise instead of succeeding.
    target = tmp_path / "GUIDE.md"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o600)
    write_rw_if_changed(target, "new")
    assert mode_of(target) == RW_MODE


# ── write_rw_body ────────────────────────────────────────────────────


def test_the_index_is_written_even_when_its_content_is_unchanged(tmp_path: Path) -> None:
    # index.md is deliberately unconditional. Proven by writing over a file
    # whose mtime we then compare — the content must land regardless.
    target = tmp_path / "index.md"
    write_rw_body(target, "same")
    write_rw_body(target, "same")
    assert target.read_text(encoding="utf-8") == "same"
    assert mode_of(target) == RW_MODE


def test_a_shorter_index_replaces_the_longer_previous_one(tmp_path: Path) -> None:
    # Deleting the last task must not leave its line dangling in index.md.
    target = tmp_path / "index.md"
    write_rw_body(target, "- [OPEN] task-a\n- [OPEN] task-b\n")
    write_rw_body(target, "- [OPEN] task-a\n")
    assert target.read_text(encoding="utf-8") == "- [OPEN] task-a\n"


def test_the_index_is_left_author_writable(tmp_path: Path) -> None:
    target = tmp_path / "index.md"
    target.write_text("x", encoding="utf-8")
    target.chmod(0o600)
    write_rw_body(target, "y")
    assert mode_of(target) == RW_MODE


# ── meta_body ────────────────────────────────────────────────────────


def test_meta_is_serialized_as_json_that_round_trips(tmp_path: Path) -> None:
    meta: dict[str, Any] = {"title": "Ship it", "completed": False, "labels": ["a", "b"]}
    assert json.loads(meta_body(meta)) == meta


def test_meta_keys_are_written_in_a_stable_order() -> None:
    # meta.json is read by the agent and diffed by the user; unstable ordering
    # makes every sync look like a content change in the workspace.
    body = meta_body({"title": "t", "completed": False, "priority": "high"})
    keys = [line.split('"')[1] for line in body.splitlines() if line.startswith("  ")]
    assert keys == sorted(keys)


def test_meta_ends_with_exactly_one_newline() -> None:
    # A POSIX text file needs the terminator; json.dumps does not add one.
    body = meta_body({"title": "t"})
    assert body.endswith("}\n")
    assert not body.endswith("\n\n")


def test_meta_is_indented_for_human_reading() -> None:
    assert "\n  " in meta_body({"title": "t"})


def test_a_datetime_in_meta_is_serialized_rather_than_raising() -> None:
    # due_date/created_at come straight off the Mongo document; a bare
    # json.dumps raises TypeError and the whole materialization dies.
    body = meta_body({"due_date": datetime(2026, 8, 3, 10, 0, tzinfo=UTC)})
    assert "2026-08-03" in json.loads(body)["due_date"]


# ── updated_at_key ───────────────────────────────────────────────────


def test_a_datetime_sorts_by_its_isoformat() -> None:
    assert updated_at_key({"updated_at": datetime(2026, 8, 3, 10, 30)}) == "2026-08-03T10:30:00"


def test_an_already_stringified_timestamp_passes_through(tmp_path: Path) -> None:
    assert updated_at_key({"updated_at": "2026-08-03T10:30:00"}) == "2026-08-03T10:30:00"


def test_a_doc_never_updated_since_creation_sorts_by_its_creation_time() -> None:
    # Freshly created tasks have no updated_at; without the fallback they all
    # collapse to "" and sink to the bottom of index.md the moment they matter
    # most.
    assert updated_at_key({"created_at": datetime(2026, 8, 3, 9, 0)}) == "2026-08-03T09:00:00"


def test_a_null_updated_at_falls_back_to_the_creation_time() -> None:
    # Mongo stores the field as null rather than omitting it.
    meta: dict[str, Any] = {"updated_at": None, "created_at": datetime(2026, 8, 3, 9, 0)}
    assert updated_at_key(meta) == "2026-08-03T09:00:00"


def test_a_doc_with_no_timestamps_at_all_sorts_without_raising() -> None:
    # One malformed doc must not take down the whole index render.
    assert updated_at_key({}) == ""


def test_updated_at_wins_over_created_at() -> None:
    meta: dict[str, Any] = {
        "updated_at": datetime(2026, 8, 3, 12, 0),
        "created_at": datetime(2026, 1, 1, 0, 0),
    }
    assert updated_at_key(meta) == "2026-08-03T12:00:00"


def test_a_datetime_and_a_string_timestamp_sort_in_true_chronological_order() -> None:
    # index.md mixes both shapes (Mongo datetimes and already-stringified
    # timestamps) in one sort. str(datetime) yields a space instead of "T",
    # which sorts below every ISO string on the same date — the newest task
    # would be listed last.
    docs: list[dict[str, Any]] = [
        {"updated_at": datetime(2026, 8, 3, 12, 0)},
        {"updated_at": "2026-08-03T11:00:00"},
    ]
    newest_first = sorted(docs, key=updated_at_key, reverse=True)
    assert newest_first[0]["updated_at"] == datetime(2026, 8, 3, 12, 0)
