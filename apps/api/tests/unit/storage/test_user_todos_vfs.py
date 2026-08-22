"""User-todos VFS projection: staleness, the lighter body, index glyphs.

This is the todo list the user sees in the UI, projected to
``/workspace/todos/`` so the agent can read "what's on their plate" as files.
Mongo is the truth; anything that survives here after Mongo moved on makes the
agent act on a todo the user already dealt with.

It shares its shape with the gaia-tasks materializer but deliberately projects
less (meta only, no canvas/log) and renders a different index line, so the
divergences are what get attacked here alongside the staleness contract.

``tmp_path`` is the real mount root — paths, mode bits and rmtree are genuine.
Nothing is mocked except one deliberate mid-write failure injection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services.storage import user_todos_vfs as utv
from app.services.storage._vfs_common import remove_tree
from app.services.storage.gaia_tasks_vfs import LEGACY_TODOS_MARKER, gaia_tasks_marker_path
from app.services.storage.user_todos_vfs import (
    UserTodoProjection,
    materialize_user_todos,
    per_doc_signature,
    read_user_todos_marker,
    user_todos_marker_path,
    write_user_todos_marker,
)

GUIDE = "# Your todo list\n"

ID_A = "6a70ad010000000000000001"
ID_B = "6a70ad020000000000000002"


def todo(doc_id: str, title: str | None = "Buy milk", **meta: Any) -> UserTodoProjection:
    return {"id": doc_id, "meta": {"title": title, **meta}}


def folders(root: Path) -> set[str]:
    return {p.name for p in (root / utv.USER_TODOS_DIRNAME).iterdir() if p.is_dir()}


def markers(root: Path) -> set[str]:
    per_doc = utv.user_todos_per_doc_dir(root)
    return {p.name for p in per_doc.iterdir()} if per_doc.is_dir() else set()


def index_items(root: Path) -> list[str]:
    text = (root / utv.USER_TODOS_DIRNAME / "index.md").read_text()
    return [line for line in text.splitlines() if line.startswith("- [")]


# ── layout: deliberately lighter than gaia-tasks ─────────────────────


def test_a_todo_is_projected_as_meta_only_in_a_slug_shortid_folder(tmp_path: Path) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk", priority="low")], GUIDE)

    folder = tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001"
    assert sorted(p.name for p in folder.iterdir()) == ["meta.json"]
    assert '"title": "Buy milk"' in folder.joinpath("meta.json").read_text()


def test_the_projected_meta_is_read_only_so_a_raw_edit_cannot_desync_it(tmp_path: Path) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    meta = tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001" / "meta.json"
    assert meta.stat().st_mode & 0o777 == 0o444


def test_every_field_the_projection_carries_survives_the_round_trip_to_disk(
    tmp_path: Path,
) -> None:
    # meta.json is the whole payload here — a dropped field is a field the agent
    # simply cannot see, with nothing else on disk to recover it from.
    materialize_user_todos(
        tmp_path,
        [todo(ID_A, "Buy milk", description="2%", due_date="2026-08-09", subtasks=[])],
        GUIDE,
    )

    body = (tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001" / "meta.json").read_text()
    assert '"description": "2%"' in body
    assert '"due_date": "2026-08-09"' in body


def test_the_guide_and_index_are_writable_because_every_sync_rewrites_them(
    tmp_path: Path,
) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    todos_root = tmp_path / utv.USER_TODOS_DIRNAME
    assert todos_root.joinpath("GUIDE.md").read_text() == GUIDE
    assert todos_root.joinpath("GUIDE.md").stat().st_mode & 0o777 == 0o644
    assert todos_root.joinpath("index.md").stat().st_mode & 0o777 == 0o644


def test_a_user_with_no_todos_still_gets_a_tree_saying_so(tmp_path: Path) -> None:
    written = materialize_user_todos(tmp_path, [], GUIDE)

    assert written == 0
    assert folders(tmp_path) == set()
    assert "No active user todos." in (tmp_path / utv.USER_TODOS_DIRNAME / "index.md").read_text()


def test_syncing_user_todos_does_not_resurrect_the_previous_releases_marker(
    tmp_path: Path,
) -> None:
    # `/todos/` is the same path the prior release used, and the gaia-tasks
    # materializer deletes that tree whenever `.gaia/todos.v` is present. This
    # materializer must never write that marker or it would arm that deletion
    # against its own output.
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    assert not (tmp_path / LEGACY_TODOS_MARKER).exists()
    assert markers(tmp_path) == {f"{ID_A}.v"}


# ── staleness: Mongo is the truth ────────────────────────────────────


def test_a_todo_deleted_in_mongo_loses_its_folder_on_the_next_sync(tmp_path: Path) -> None:
    # A todo the user ticked off and removed must stop existing for the agent,
    # or it keeps nagging about work that is done.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk"), todo(ID_B, "Call mum")], GUIDE)

    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    assert folders(tmp_path) == {"buy-milk-00000001"}
    assert len(index_items(tmp_path)) == 1


def test_a_todo_deleted_in_mongo_also_loses_its_per_doc_marker(tmp_path: Path) -> None:
    # A marker outliving its folder makes the hash gate claim "unchanged" if the
    # id ever returns, and the body never gets written again.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk"), todo(ID_B, "Call mum")], GUIDE)

    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    assert markers(tmp_path) == {f"{ID_A}.v"}


def test_clearing_the_whole_list_empties_the_tree_without_taking_the_guide_with_it(
    tmp_path: Path,
) -> None:
    # The stale-folder sweep walks the todos root, where GUIDE.md and index.md
    # also live; it must discriminate by directory, not just by name.
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    materialize_user_todos(tmp_path, [], GUIDE)

    assert folders(tmp_path) == set()
    assert markers(tmp_path) == set()
    assert (tmp_path / utv.USER_TODOS_DIRNAME / "GUIDE.md").read_text() == GUIDE


def test_a_stale_folder_is_removed_even_though_its_meta_is_read_only(tmp_path: Path) -> None:
    # Projected bodies are 0444; a plain rmtree with no chmod-and-retry would
    # leave the deleted todo's folder behind forever.
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    materialize_user_todos(tmp_path, [], GUIDE)

    assert not (tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001").exists()


def test_a_renamed_todo_does_not_leave_a_second_folder_under_its_old_slug(
    tmp_path: Path,
) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    materialize_user_todos(tmp_path, [todo(ID_A, "Buy oat milk")], GUIDE)

    assert folders(tmp_path) == {"buy-oat-milk-00000001"}
    assert markers(tmp_path) == {f"{ID_A}.v"}


# ── hash gating: rewrite only what changed ───────────────────────────


def test_re_running_a_sync_with_unchanged_todos_rewrites_nothing(tmp_path: Path) -> None:
    # Every todo write schedules a sync; without the gate a busy list rewrites
    # the entire tree on a network filesystem on every keystroke.
    docs = [todo(ID_A, "Buy milk"), todo(ID_B, "Call mum")]
    assert materialize_user_todos(tmp_path, docs, GUIDE) == 2

    assert materialize_user_todos(tmp_path, docs, GUIDE) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("completed", True), ("priority", "high"), ("due_date", "2026-09-01")],
)
def test_editing_a_single_meta_field_rewrites_the_body(
    tmp_path: Path, field: str, value: Any
) -> None:
    # The folder name does not change when only meta does, so the hash gate is
    # the only thing that can notice — a gate over the wrong fields freezes the
    # todo in its old state permanently.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    written = materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk", **{field: value})], GUIDE)

    assert written == 1
    body = (tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001" / "meta.json").read_text()
    assert f'"{field}"' in body


def test_a_folder_deleted_off_disk_is_rebuilt_even_though_its_marker_still_matches(
    tmp_path: Path,
) -> None:
    # The marker alone must not be trusted as proof the body is on disk.
    materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)
    remove_tree(tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001")

    written = materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)

    assert written == 1
    assert (tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001" / "meta.json").exists()


def test_a_todo_that_fails_mid_write_is_not_stamped_as_synced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stamping the marker before the body lands would freeze a missing todo in
    # place — the gate would report it clean on every subsequent sync.
    real_write = utv.write_readonly_body

    def flaky(target: Path, content: str) -> None:
        raise OSError("ENOSPC")

    monkeypatch.setattr(utv, "write_readonly_body", flaky)
    with pytest.raises(OSError, match="ENOSPC"):
        materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE)
    assert markers(tmp_path) == set()

    monkeypatch.setattr(utv, "write_readonly_body", real_write)
    assert materialize_user_todos(tmp_path, [todo(ID_A)], GUIDE) == 1


def test_the_signature_moves_with_the_meta_and_is_stable_when_it_does_not() -> None:
    base = todo(ID_A, "Buy milk", completed=False)

    assert per_doc_signature(base) != per_doc_signature(todo(ID_A, "Buy milk", completed=True))
    assert per_doc_signature(base) == per_doc_signature(todo(ID_A, "Buy milk", completed=False))


def test_a_reordered_meta_dict_is_not_treated_as_a_change() -> None:
    # Mongo does not promise key order. Hashing the raw dict order would rewrite
    # every todo on every sync and make the gate pointless.
    a: UserTodoProjection = {"id": ID_A, "meta": {"title": "Buy milk", "completed": False}}
    b: UserTodoProjection = {"id": ID_A, "meta": {"completed": False, "title": "Buy milk"}}

    assert per_doc_signature(a) == per_doc_signature(b)


# ── hostile titles: user-typed, straight into a path ─────────────────


def test_a_title_full_of_slashes_cannot_nest_the_todo_under_new_directories(
    tmp_path: Path,
) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, "groceries/dairy/milk")], GUIDE)

    assert folders(tmp_path) == {"groceries-dairy-milk-00000001"}


@pytest.mark.parametrize("title", ["../../etc/passwd", "..", "./.."])
def test_a_traversal_title_stays_inside_the_todos_root(tmp_path: Path, title: str) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, title)], GUIDE)

    todos_root = tmp_path / utv.USER_TODOS_DIRNAME
    (folder,) = [p for p in todos_root.iterdir() if p.is_dir()]
    assert folder.resolve().parent == todos_root.resolve()


@pytest.mark.parametrize("title", ["🥛🥛", "   ", "", None])
def test_a_title_with_no_usable_ascii_still_yields_a_usable_folder(
    tmp_path: Path, title: str | None
) -> None:
    written = materialize_user_todos(tmp_path, [todo(ID_A, title)], GUIDE)

    assert written == 1
    assert folders(tmp_path) == {"untitled-00000001"}


def test_an_absurdly_long_title_is_truncated_to_a_bounded_folder_name(tmp_path: Path) -> None:
    # Most filesystems cap a path component at 255 bytes; an untruncated title
    # would fail the mkdir outright.
    materialize_user_todos(tmp_path, [todo(ID_A, "remember to " * 80)], GUIDE)

    (name,) = folders(tmp_path)
    assert len(name) == len("-00000001") + 40


def test_a_multi_line_title_cannot_break_the_index_into_extra_rows(tmp_path: Path) -> None:
    # A newline reaching index.md turns one todo into two bogus rows and
    # corrupts the agent's read of every row after it.
    materialize_user_todos(tmp_path, [todo(ID_A, "call the\nplumber")], GUIDE)

    assert len(index_items(tmp_path)) == 1
    assert "call the plumber" in index_items(tmp_path)[0]


# ── index.md: the "what's on your plate" view ────────────────────────


def test_the_index_lists_the_most_recently_updated_todo_first(tmp_path: Path) -> None:
    docs = [
        todo(ID_A, "Older", updated_at="2026-01-01T00:00:00"),
        todo(ID_B, "Newer", updated_at="2026-06-01T00:00:00"),
    ]

    materialize_user_todos(tmp_path, docs, GUIDE)

    items = index_items(tmp_path)
    assert "Newer" in items[0]
    assert "Older" in items[1]


def test_a_todo_with_no_updated_at_is_ordered_by_when_it_was_created(tmp_path: Path) -> None:
    docs = [
        todo(ID_A, "Created early", created_at="2026-01-01T00:00:00"),
        todo(ID_B, "Created late", created_at="2026-06-01T00:00:00"),
    ]

    materialize_user_todos(tmp_path, docs, GUIDE)

    assert "Created late" in index_items(tmp_path)[0]


@pytest.mark.parametrize(
    ("meta", "glyph"),
    [
        ({"completed": True}, "DONE"),
        ({"completed": True, "priority": "high"}, "DONE"),
        ({"priority": "high"}, "!!  "),
        ({"priority": "low"}, "OPEN"),
        ({}, "OPEN"),
    ],
    ids=["done", "done beats urgent", "urgent", "low", "no priority"],
)
def test_the_index_glyph_says_done_before_it_says_urgent(
    tmp_path: Path, meta: dict[str, Any], glyph: str
) -> None:
    # A finished high-priority todo flagged `!!` reads as outstanding urgent
    # work — the agent would chase something the user already closed.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk", **meta)], GUIDE)

    (item,) = index_items(tmp_path)
    assert item.startswith(f"- [{glyph}]")


def test_a_due_date_is_carried_into_the_index_line(tmp_path: Path) -> None:
    # This view exists so the agent can spot what is due without opening every
    # meta.json; a dropped due date makes it miss deadlines.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk", due_date="2026-08-09")], GUIDE)

    assert "due=2026-08-09" in index_items(tmp_path)[0]


def test_a_todo_with_no_due_date_gets_no_empty_due_suffix(tmp_path: Path) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    assert "due=" not in index_items(tmp_path)[0]


def test_a_todo_with_no_title_is_listed_as_untitled_rather_than_dropped(tmp_path: Path) -> None:
    materialize_user_todos(tmp_path, [todo(ID_A, None)], GUIDE)

    assert "(untitled)" in index_items(tmp_path)[0]


def test_the_index_names_the_folder_the_agent_has_to_open(tmp_path: Path) -> None:
    # A listed folder name that does not exist on disk sends the agent to a dead
    # path — the index is the only map it has.
    materialize_user_todos(tmp_path, [todo(ID_A, "Buy milk")], GUIDE)

    (item,) = index_items(tmp_path)
    assert "`buy-milk-00000001`" in item
    assert (tmp_path / utv.USER_TODOS_DIRNAME / "buy-milk-00000001").is_dir()


# ── catalog marker accessors ─────────────────────────────────────────


def test_the_catalog_marker_reads_back_what_was_written(tmp_path: Path) -> None:
    write_user_todos_marker(tmp_path, "deadbeef")

    assert read_user_todos_marker(tmp_path) == "deadbeef"
    assert user_todos_marker_path(tmp_path) == tmp_path / ".gaia/user-todos.v"


def test_an_unsynced_workspace_reports_no_catalog_marker(tmp_path: Path) -> None:
    # A missing marker must read as "never synced", not as a match against
    # whatever the caller compares it to.
    assert read_user_todos_marker(tmp_path) is None


def test_the_user_todos_marker_does_not_collide_with_the_gaia_tasks_one(
    tmp_path: Path,
) -> None:
    # Both projections stamp markers under `.gaia/`. Sharing a path would make
    # one sync's signature satisfy the other's gate and skip a real update.
    assert user_todos_marker_path(tmp_path) != gaia_tasks_marker_path(tmp_path)
    assert utv.user_todos_per_doc_dir(tmp_path) != tmp_path / ".gaia/gaia-tasks"
