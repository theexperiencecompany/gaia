"""Gaia-tasks VFS projection: staleness, naming, hash gating, legacy cleanup.

MongoDB is the truth; ``/workspace/gaia-tasks/`` is a derived copy the agent
reads as if it were the truth. Two failure classes matter and neither shows up
in a log line: a projection that outlives its Mongo document (the agent acts on
a task the user deleted) and a projection that writes outside the tree it owns
(one user's data landing in another's, or a sibling projection getting wiped).

``tmp_path`` is the real mount root — every path, mode bit and rmtree here is
genuine filesystem behavior. Nothing is mocked except one deliberate mid-write
failure injection; these functions take a ``Path`` and touch no network or DB.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.services.storage import gaia_tasks_vfs as gtv
from app.services.storage._vfs_common import remove_tree
from app.services.storage.gaia_tasks_vfs import (
    GaiaTaskProjection,
    cleanup_legacy_todos_dir,
    gaia_tasks_marker_path,
    materialize_gaia_tasks,
    per_doc_signature,
    read_gaia_tasks_marker,
    write_gaia_tasks_marker,
)
from app.services.storage.user_todos_vfs import materialize_user_todos

GUIDE = "# How to use gaia-tasks\n"

# Real ObjectId hex. The first 8 chars are the 4-byte creation *timestamp*, so
# ids minted in different seconds differ there and ids minted in the same second
# do not — both cases are exercised below.
ID_A = "6a70ad010000000000000001"
ID_B = "6a70ad020000000000000002"
SAME_SECOND_A = "6a70ad554e0de79bddbe0001"
SAME_SECOND_B = "6a70ad554e0de79bddbe0002"


def task(
    doc_id: str,
    title: str | None = "Ship the release",
    *,
    deliverable: str = "# deliverable\n",
    notes: str = "# notes\n",
    log: str = "- did a thing\n",
    artifacts: list[dict[str, Any]] | None = None,
    **meta: Any,
) -> GaiaTaskProjection:
    return {
        "id": doc_id,
        "deliverable": deliverable,
        "notes": notes,
        "log": log,
        "artifacts": artifacts or [],
        "meta": {"title": title, **meta},
    }


def folders(root: Path) -> set[str]:
    tasks_root = root / gtv.GAIA_TASKS_DIRNAME
    return {p.name for p in tasks_root.iterdir() if p.is_dir()}


def markers(root: Path) -> set[str]:
    per_doc = gtv.gaia_tasks_per_doc_dir(root)
    return {p.name for p in per_doc.iterdir()} if per_doc.is_dir() else set()


def index_items(root: Path) -> list[str]:
    text = (root / gtv.GAIA_TASKS_DIRNAME / "index.md").read_text()
    return [line for line in text.splitlines() if line.startswith("- [")]


# ── cleanup_legacy_todos_dir ─────────────────────────────────────────


def seed_legacy_projection(root: Path) -> None:
    (root / gtv.LEGACY_TODOS_DIRNAME / "old-task-abc12345").mkdir(parents=True)
    (root / gtv.LEGACY_TODOS_DIRNAME / "index.md").write_text("stale\n")
    (root / gtv.LEGACY_TODOS_PER_DOC_MARKER_DIR).mkdir(parents=True)
    (root / gtv.LEGACY_TODOS_PER_DOC_MARKER_DIR / f"{ID_A}.v").write_text("sig\n")
    (root / gtv.LEGACY_TODOS_MARKER).parent.mkdir(parents=True, exist_ok=True)
    (root / gtv.LEGACY_TODOS_MARKER).write_text("catalog-sig\n")


def test_the_previous_releases_todos_projection_is_removed_when_its_marker_is_present(
    tmp_path: Path,
) -> None:
    # Left behind, the old tree keeps serving the agent a todo list that Mongo
    # stopped updating the moment this release shipped.
    seed_legacy_projection(tmp_path)

    assert cleanup_legacy_todos_dir(tmp_path) is True
    assert not (tmp_path / gtv.LEGACY_TODOS_DIRNAME).exists()
    assert not (tmp_path / gtv.LEGACY_TODOS_PER_DOC_MARKER_DIR).exists()
    assert not (tmp_path / gtv.LEGACY_TODOS_MARKER).exists()


def test_a_todos_dir_without_the_legacy_marker_is_left_untouched(tmp_path: Path) -> None:
    # In this release `/todos/` belongs to the user-todos materializer. Deleting
    # it on marker-less detection would erase the user's live todo list.
    (tmp_path / gtv.LEGACY_TODOS_DIRNAME).mkdir(parents=True)
    (tmp_path / gtv.LEGACY_TODOS_DIRNAME / "index.md").write_text("current\n")

    assert cleanup_legacy_todos_dir(tmp_path) is False
    assert (tmp_path / gtv.LEGACY_TODOS_DIRNAME / "index.md").read_text() == "current\n"


def test_running_the_legacy_cleanup_twice_reports_nothing_left_to_do(tmp_path: Path) -> None:
    # It runs on every single sync; a second pass must be a cheap no-op rather
    # than re-reporting a migration that already happened.
    seed_legacy_projection(tmp_path)
    cleanup_legacy_todos_dir(tmp_path)

    assert cleanup_legacy_todos_dir(tmp_path) is False


def test_the_legacy_cleanup_reports_nothing_on_a_brand_new_workspace(tmp_path: Path) -> None:
    assert cleanup_legacy_todos_dir(tmp_path) is False


def test_syncing_gaia_tasks_does_not_delete_the_users_live_todos_projection(
    tmp_path: Path,
) -> None:
    # Migrating user: `.gaia/todos.v` is still on disk from the prior release,
    # but `/todos/` now holds the *new* user-todos projection because a plain
    # todo was written first (the two syncs are scheduled independently, from
    # todo_service and tracked_todo_service, in no fixed order). The legacy
    # cleanup keys off the marker alone and takes the live tree with it.
    (tmp_path / gtv.LEGACY_TODOS_MARKER).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / gtv.LEGACY_TODOS_MARKER).write_text("prior-release-sig\n")
    materialize_user_todos(tmp_path, [{"id": ID_B, "meta": {"title": "Buy milk"}}], "todo guide")
    assert (tmp_path / "todos" / "buy-milk-00000002" / "meta.json").exists()

    materialize_gaia_tasks(tmp_path, [task(ID_A)], GUIDE)

    assert (tmp_path / "todos" / "buy-milk-00000002" / "meta.json").exists()


# ── materialize: layout and content ──────────────────────────────────


def test_a_task_is_projected_as_facet_bodies_and_meta_in_a_slug_shortid_folder(
    tmp_path: Path,
) -> None:
    materialize_gaia_tasks(
        tmp_path,
        [task(ID_A, "Ship the release", deliverable="D", notes="N", log="L")],
        GUIDE,
    )

    folder = tmp_path / gtv.GAIA_TASKS_DIRNAME / "ship-the-release-00000001"
    assert folder.is_dir()
    assert folder.joinpath("deliverable.md").read_text() == "D"
    assert folder.joinpath("notes.md").read_text() == "N"
    assert folder.joinpath("log.md").read_text() == "L"
    assert '"title": "Ship the release"' in folder.joinpath("meta.json").read_text()


def test_a_task_with_artifacts_projects_one_readonly_file_per_artifact(
    tmp_path: Path,
) -> None:
    # Artifacts are part of the facet model: each lands as its own 0444 body so
    # the agent can read them directly from the tree.
    docs = [
        task(
            ID_A,
            "Research",
            artifacts=[
                {"name": "notes summary", "content": "found nothing"},
                {"name": "raw dump", "content": "…"},
            ],
        )
    ]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    folder = tmp_path / gtv.GAIA_TASKS_DIRNAME / "research-00000001"
    assert folder.joinpath("artifacts", "notes-summary.md").read_text() == "found nothing"
    assert folder.joinpath("artifacts", "raw-dump.md").read_text() == "…"
    assert folder.joinpath("artifacts", "notes-summary.md").stat().st_mode & 0o777 == 0o444


def test_a_removed_artifact_never_lingers_in_its_folder(tmp_path: Path) -> None:
    # The artifacts subtree is rebuilt from scratch on every folder rewrite, so
    # a renamed or removed artifact cannot stay behind and mislead the agent.
    docs = [task(ID_A, "Research", artifacts=[{"name": "temp", "content": "x"}])]
    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    docs = [task(ID_A, "Research", artifacts=[])]
    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    folder = tmp_path / gtv.GAIA_TASKS_DIRNAME / "research-00000001"
    assert not (folder / "artifacts").exists()


def test_an_artifact_with_empty_content_projects_an_empty_file_not_a_placeholder(
    tmp_path: Path,
) -> None:
    # An artifact gets named before it is filled, so an empty body is a normal
    # state. Anything substituted for it is text the agent reads back as the
    # artifact's real content.
    docs = [task(ID_A, "Research", artifacts=[{"name": "draft", "content": ""}])]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    assert (
        tmp_path / gtv.GAIA_TASKS_DIRNAME / "research-00000001" / "artifacts" / "draft.md"
    ).read_text() == ""


def test_an_artifacts_dir_that_could_not_be_removed_does_not_abort_the_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_force_remove` swallows OSError, so a failed rmtree on the network mount
    # leaves the artifacts dir standing. Rebuilding the subtree has to survive
    # that: the alternative is a task whose whole folder stops syncing because
    # one directory refused to go.
    materialize_gaia_tasks(
        tmp_path, [task(ID_A, "Research", artifacts=[{"name": "first", "content": "v1"}])], GUIDE
    )
    monkeypatch.setattr(gtv, "remove_tree", lambda path: None)

    materialize_gaia_tasks(
        tmp_path, [task(ID_A, "Research", artifacts=[{"name": "second", "content": "v2"}])], GUIDE
    )

    assert (
        tmp_path / gtv.GAIA_TASKS_DIRNAME / "research-00000001" / "artifacts" / "second.md"
    ).read_text() == "v2"


def test_projected_bodies_are_read_only_so_a_raw_edit_cannot_silently_desync_them(
    tmp_path: Path,
) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A)], GUIDE)

    folder = tmp_path / gtv.GAIA_TASKS_DIRNAME / "ship-the-release-00000001"
    for name in ("deliverable.md", "notes.md", "log.md", "meta.json"):
        assert folder.joinpath(name).stat().st_mode & 0o777 == 0o444, name


def test_the_guide_and_index_are_writable_because_every_sync_rewrites_them(
    tmp_path: Path,
) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A)], GUIDE)

    tasks_root = tmp_path / gtv.GAIA_TASKS_DIRNAME
    assert tasks_root.joinpath("GUIDE.md").read_text() == GUIDE
    assert tasks_root.joinpath("GUIDE.md").stat().st_mode & 0o777 == 0o644
    assert tasks_root.joinpath("index.md").stat().st_mode & 0o777 == 0o644


def test_an_edited_guide_is_restored_from_the_shipped_copy_on_the_next_sync(
    tmp_path: Path,
) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A)], GUIDE)
    (tmp_path / gtv.GAIA_TASKS_DIRNAME / "GUIDE.md").write_text("agent scribbled here\n")

    materialize_gaia_tasks(tmp_path, [task(ID_A)], GUIDE)

    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "GUIDE.md").read_text() == GUIDE


def test_a_user_with_no_gaia_tasks_still_gets_a_tree_saying_so(tmp_path: Path) -> None:
    written = materialize_gaia_tasks(tmp_path, [], GUIDE)

    assert written == 0
    assert folders(tmp_path) == set()
    assert "No active gaia-tasks." in (tmp_path / gtv.GAIA_TASKS_DIRNAME / "index.md").read_text()


# ── staleness: Mongo is the truth ────────────────────────────────────


def test_a_task_deleted_in_mongo_loses_its_folder_on_the_next_sync(tmp_path: Path) -> None:
    # The whole point of the projection: the agent must not keep reading a task
    # the user closed. A stale folder here is invisible until it acts on it.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha"), task(ID_B, "Beta")], GUIDE)

    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    assert folders(tmp_path) == {"alpha-00000001"}


def test_a_task_deleted_in_mongo_also_loses_its_per_doc_marker(tmp_path: Path) -> None:
    # A surviving marker outlives its folder, so if the id ever comes back the
    # hash gate says "unchanged" and the body is never re-materialized.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha"), task(ID_B, "Beta")], GUIDE)

    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    assert markers(tmp_path) == {f"{ID_A}.v"}


def test_deleting_every_task_empties_the_tree_without_taking_the_guide_with_it(
    tmp_path: Path,
) -> None:
    # The stale-folder sweep walks the tasks root, where GUIDE.md and index.md
    # also live; it must discriminate by directory, not just by name.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    materialize_gaia_tasks(tmp_path, [], GUIDE)

    assert folders(tmp_path) == set()
    assert markers(tmp_path) == set()
    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "GUIDE.md").read_text() == GUIDE
    assert index_items(tmp_path) == []


def test_a_stale_folder_is_removed_even_though_its_bodies_are_read_only(
    tmp_path: Path,
) -> None:
    # Projected bodies are 0444; a plain rmtree that cannot chmod-and-retry
    # leaves the deleted task's folder behind forever.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)
    assert (
        tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "deliverable.md"
    ).stat().st_mode & 0o777 == 0o444

    materialize_gaia_tasks(tmp_path, [], GUIDE)

    assert not (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001").exists()


def test_a_renamed_task_does_not_leave_a_second_folder_under_its_old_slug(
    tmp_path: Path,
) -> None:
    # Rename changes the folder name, so the write lands in a new directory and
    # the old one is only gone if the sweep actually runs.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Old name")], GUIDE)

    materialize_gaia_tasks(tmp_path, [task(ID_A, "New name")], GUIDE)

    assert folders(tmp_path) == {"new-name-00000001"}
    assert len(index_items(tmp_path)) == 1


def test_a_renamed_task_keeps_exactly_one_marker(tmp_path: Path) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Old name")], GUIDE)

    materialize_gaia_tasks(tmp_path, [task(ID_A, "New name")], GUIDE)

    assert markers(tmp_path) == {f"{ID_A}.v"}


@pytest.mark.parametrize(
    ("title_a", "title_b"),
    [
        ("Follow up with Alex", "Follow up with Alex"),
        (
            "Draft the quarterly board update deck for review by leadership",
            "Draft the quarterly board update deck for review by finance",
        ),
    ],
    ids=["identical titles", "titles sharing a 40-char prefix"],
)
def test_two_tasks_created_in_the_same_second_with_the_same_slug_get_separate_folders(
    tmp_path: Path, title_a: str, title_b: str
) -> None:
    # The "shortid" is an ObjectId's 4-byte timestamp prefix, so it carries zero
    # entropy between docs minted in the same second (a bulk create). Two such
    # tasks whose titles slugify alike — identical, or agreeing on the first 40
    # characters — collapse into one folder: the second body overwrites the
    # first, index.md points both of its entries at that one path, and both
    # markers get stamped so no later sync ever repairs it.
    docs = [task(SAME_SECOND_A, title_a), task(SAME_SECOND_B, title_b)]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    assert len(folders(tmp_path)) == 2


# ── hash gating: rewrite only what changed ───────────────────────────


def test_re_running_a_sync_with_unchanged_tasks_rewrites_nothing(tmp_path: Path) -> None:
    # Steady-state turns must do zero body I/O; without the gate every agent
    # turn rewrites the whole tree on a network filesystem.
    docs = [task(ID_A, "Alpha"), task(ID_B, "Beta")]
    assert materialize_gaia_tasks(tmp_path, docs, GUIDE) == 2

    assert materialize_gaia_tasks(tmp_path, docs, GUIDE) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deliverable", "# rewritten\n"),
        ("notes", "# rewritten\n"),
        ("log", "- newer entry\n"),
    ],
)
def test_editing_only_one_facet_still_rewrites_the_body(
    tmp_path: Path, field: str, value: str
) -> None:
    # The folder name is unchanged by a body edit, so the hash gate is the only
    # thing that can notice — if it hashes the wrong fields the agent reads its
    # own stale notes back forever.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    written = materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha", **{field: value})], GUIDE)

    assert written == 1
    filename = f"{field}.md"
    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / filename).read_text() == value


def test_changing_only_the_artifacts_still_rewrites_the_body(tmp_path: Path) -> None:
    # Artifacts are part of the per-doc signature; a content change in one must
    # not be hidden by the hash gate.
    docs = [task(ID_A, "Alpha", artifacts=[{"name": "a", "content": "v1"}])]
    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    docs = [task(ID_A, "Alpha", artifacts=[{"name": "a", "content": "v2"}])]
    written = materialize_gaia_tasks(tmp_path, docs, GUIDE)

    assert written == 1
    assert (
        tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "artifacts" / "a.md"
    ).read_text() == "v2"


def test_completing_a_task_rewrites_its_meta_even_though_nothing_else_changed(
    tmp_path: Path,
) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha", completed=False)], GUIDE)

    written = materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha", completed=True)], GUIDE)

    assert written == 1
    meta = (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "meta.json").read_text()
    assert '"completed": true' in meta


def test_a_folder_deleted_off_disk_is_rebuilt_even_though_its_marker_still_matches(
    tmp_path: Path,
) -> None:
    # Anything can eat the folder — a failed sync, a JuiceFS hiccup, the legacy
    # cleanup. The marker alone must not be trusted as proof the body is there.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)
    remove_tree(tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001")

    written = materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    assert written == 1
    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "deliverable.md").exists()


def test_a_task_that_fails_mid_write_is_not_stamped_as_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # log.md fails after the earlier facets landed. Stamping the marker before
    # the body is fully on disk would freeze a half-written task in place — the
    # gate would report it clean on every subsequent sync.
    real_write = gtv.write_readonly_body

    def flaky(target: Path, content: str) -> None:
        if target.name == "log.md":
            raise OSError("ENOSPC")
        real_write(target, content)

    monkeypatch.setattr(gtv, "write_readonly_body", flaky)
    with pytest.raises(OSError, match="ENOSPC"):
        materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)
    assert markers(tmp_path) == set()

    monkeypatch.setattr(gtv, "write_readonly_body", real_write)
    assert materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE) == 1
    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "log.md").exists()


def test_the_signature_reflects_every_facet_and_the_meta(tmp_path: Path) -> None:
    base = task(ID_A, "Alpha", deliverable="D", notes="N", log="L")

    assert per_doc_signature(base) != per_doc_signature(
        task(ID_A, "Alpha", deliverable="D2", notes="N", log="L")
    )
    assert per_doc_signature(base) != per_doc_signature(
        task(ID_A, "Alpha", deliverable="D", notes="N2", log="L")
    )
    assert per_doc_signature(base) != per_doc_signature(
        task(ID_A, "Alpha", deliverable="D", notes="N", log="L2")
    )
    assert per_doc_signature(base) != per_doc_signature(
        task(ID_A, "Alpha", deliverable="D", notes="N", log="L", completed=True)
    )
    assert per_doc_signature(base) == per_doc_signature(
        task(ID_A, "Alpha", deliverable="D", notes="N", log="L")
    )


def test_reordering_an_artifacts_keys_is_not_a_change_worth_rewriting_the_folder_for(
    tmp_path: Path,
) -> None:
    # The signature is what keeps a steady-state sync at zero I/O. Hashing the
    # artifacts as written rather than canonically makes a document whose fields
    # come back in another order look edited, and every folder is rewritten on
    # the network mount on every turn.
    ordered = task(ID_A, "Alpha", artifacts=[{"name": "a", "content": "v1", "kind": "markdown"}])
    reordered = task(ID_A, "Alpha", artifacts=[{"kind": "markdown", "content": "v1", "name": "a"}])
    assert materialize_gaia_tasks(tmp_path, [ordered], GUIDE) == 1

    assert materialize_gaia_tasks(tmp_path, [reordered], GUIDE) == 0
    assert per_doc_signature(ordered) == per_doc_signature(reordered)


def test_an_artifact_value_json_cannot_encode_natively_is_hashed_not_raised_on(
    tmp_path: Path,
) -> None:
    # ``artifacts`` is ``list[dict[str, Any]]`` and the sibling meta payload
    # already carries datetimes. The hash gate has to be total: raising here
    # fails the user's whole projection, not one artifact.
    docs = [
        task(
            ID_A,
            "Alpha",
            artifacts=[{"name": "a", "content": "v", "generated_at": datetime(2026, 1, 1)}],
        )
    ]

    assert materialize_gaia_tasks(tmp_path, docs, GUIDE) == 1
    assert (
        tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001" / "artifacts" / "a.md"
    ).read_text() == "v"


# ── hostile titles: user-supplied, straight into a path ──────────────


def test_a_title_full_of_slashes_cannot_nest_the_task_under_new_directories(
    tmp_path: Path,
) -> None:
    # Titles come from the user. A path separator surviving into the folder name
    # scatters the projection across directories the sweep never revisits.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "reports/2026/q3")], GUIDE)

    assert folders(tmp_path) == {"reports-2026-q3-00000001"}


@pytest.mark.parametrize("title", ["../../etc/passwd", "..", "./.."])
def test_a_traversal_title_stays_inside_the_tasks_root(tmp_path: Path, title: str) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, title)], GUIDE)

    tasks_root = tmp_path / gtv.GAIA_TASKS_DIRNAME
    (folder,) = [p for p in tasks_root.iterdir() if p.is_dir()]
    assert folder.resolve().parent == tasks_root.resolve()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("🎉🎉🎉", "untitled-00000001"),
        ("   ", "untitled-00000001"),
        ("", "untitled-00000001"),
        ("Café — naïve résumé", "caf-na-ve-r-sum-00000001"),
    ],
)
def test_a_title_with_no_usable_ascii_still_yields_a_stable_folder_name(
    tmp_path: Path, title: str, expected: str
) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, title)], GUIDE)

    assert folders(tmp_path) == {expected}


def test_an_absurdly_long_title_is_truncated_to_a_bounded_folder_name(tmp_path: Path) -> None:
    # Most filesystems cap a path component at 255 bytes; an untruncated title
    # would fail the mkdir outright.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "supercalifragilistic " * 60)], GUIDE)

    (name,) = folders(tmp_path)
    assert len(name) == len("-00000001") + 40
    assert name.endswith("-00000001")


def test_a_title_that_is_missing_entirely_is_projected_rather_than_skipped(
    tmp_path: Path,
) -> None:
    written = materialize_gaia_tasks(tmp_path, [task(ID_A, None)], GUIDE)

    assert written == 1
    assert folders(tmp_path) == {"untitled-00000001"}
    assert "(untitled)" in index_items(tmp_path)[0]


# ── index.md ─────────────────────────────────────────────────────────


def test_the_index_lists_the_most_recently_updated_task_first(tmp_path: Path) -> None:
    # This is the agent's entry point into the tree; wrong order buries the task
    # the user just touched under months of finished ones.
    docs = [
        task(ID_A, "Older", updated_at="2026-01-01T00:00:00"),
        task(ID_B, "Newer", updated_at="2026-06-01T00:00:00"),
    ]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    items = index_items(tmp_path)
    assert "Newer" in items[0]
    assert "Older" in items[1]


def test_a_task_with_no_updated_at_is_ordered_by_when_it_was_created(tmp_path: Path) -> None:
    docs = [
        task(ID_A, "Created early", created_at="2026-01-01T00:00:00"),
        task(ID_B, "Created late", created_at="2026-06-01T00:00:00"),
    ]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    assert "Created late" in index_items(tmp_path)[0]


def test_a_task_with_no_timestamps_at_all_is_still_listed(tmp_path: Path) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Timeless")], GUIDE)

    assert len(index_items(tmp_path)) == 1
    assert "Timeless" in index_items(tmp_path)[0]


def test_a_completed_task_is_marked_done_and_an_open_one_is_not(tmp_path: Path) -> None:
    docs = [task(ID_A, "Done one", completed=True), task(ID_B, "Open one", completed=False)]

    materialize_gaia_tasks(tmp_path, docs, GUIDE)

    by_title = {"Done one": "", "Open one": ""}
    for item in index_items(tmp_path):
        for title in by_title:
            if item.endswith(f"{title}  _(updated —)_"):
                by_title[title] = item
    assert by_title["Done one"].startswith("- [DONE]")
    assert by_title["Open one"].startswith("- [OPEN]")


def test_a_multi_line_title_cannot_break_the_index_into_extra_rows(tmp_path: Path) -> None:
    # A newline reaching index.md turns one task into two bogus list entries and
    # corrupts the agent's read of everything after it.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "line one\nline two")], GUIDE)

    text = (tmp_path / gtv.GAIA_TASKS_DIRNAME / "index.md").read_text()
    assert len(index_items(tmp_path)) == 1
    assert "line one line two" in text


def test_the_index_drops_a_task_the_same_sync_that_drops_its_folder(tmp_path: Path) -> None:
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha"), task(ID_B, "Beta")], GUIDE)

    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    items = index_items(tmp_path)
    assert len(items) == 1
    assert "Beta" not in items[0]


def test_the_index_names_the_folder_the_agent_has_to_open(tmp_path: Path) -> None:
    # A listed folder name that does not exist on disk sends the agent to a
    # dead path — the index is the only map it has.
    materialize_gaia_tasks(tmp_path, [task(ID_A, "Alpha")], GUIDE)

    (item,) = index_items(tmp_path)
    assert "`alpha-00000001`" in item
    assert (tmp_path / gtv.GAIA_TASKS_DIRNAME / "alpha-00000001").is_dir()


# ── catalog marker accessors ─────────────────────────────────────────


def test_the_catalog_marker_reads_back_what_was_written(tmp_path: Path) -> None:
    write_gaia_tasks_marker(tmp_path, "deadbeef")

    assert read_gaia_tasks_marker(tmp_path) == "deadbeef"
    assert gaia_tasks_marker_path(tmp_path) == tmp_path / ".gaia/gaia-tasks.v"


def test_an_unsynced_workspace_reports_no_catalog_marker(tmp_path: Path) -> None:
    # A missing marker must read as "never synced", not as a match against
    # whatever the caller compares it to.
    assert read_gaia_tasks_marker(tmp_path) is None


def test_the_catalog_marker_lives_outside_the_tree_the_sweep_prunes(tmp_path: Path) -> None:
    write_gaia_tasks_marker(tmp_path, "deadbeef")

    materialize_gaia_tasks(tmp_path, [], GUIDE)

    assert read_gaia_tasks_marker(tmp_path) == "deadbeef"
