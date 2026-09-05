"""Layer 1 — JuiceFS mount primitives: containment, paging arithmetic, mount gating.

Every workspace byte a user or an agent ever writes goes through this module, and
``_contained`` / ``ensure_safe_path_id`` are the only thing standing between one
user's conversation and another's tree. So the filesystem is NOT mocked here: the
mount root is a real ``tmp_path``, with real ``..`` segments, real symlinks and
real files, because string-level path logic that is never resolved against a real
FS is exactly how traversal bugs survive a green suite.

The single genuine mock is ``_is_mounted()`` — a FUSE mountpoint cannot be created
in a unit test. Tests that care about the *absence* of the mount leave it real
(a tmpdir is never a mountpoint), which is also how the "an existing empty dir is
not a mount" regression is pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import settings
from app.services.storage.juicefs import (
    JuiceFSUnavailable,
    _contained,
    _host_base_and_rel,
    _is_mounted,
    delete_user_skill,
    delete_user_workspace,
    ensure_safe_path_id,
    ensure_user_skills_dir,
    ensure_user_workspace,
    page_bounds,
    read_user_file,
    read_user_file_bytes,
    resolve_user_file,
    sandbox_session_path,
    session_root,
    to_workspace_relative_path,
    user_owns_regular_file,
    user_skills_path,
    user_workspace_path,
    write_session_file,
    write_session_file_sync,
    write_skill_file,
)

USER = "user-1"
OTHER = "user-2"
CONV = "conv-a"


@pytest.fixture
def mount_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module at a real tmpdir, still reporting itself as unmounted.

    Used by the tests that assert the mount gate fires; `mount` layers the
    "it is mounted" lie on top.
    """
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    return root


@pytest.fixture
def mount(mount_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real tmpdir that also passes the mountpoint check.

    ``Path.is_mount()`` is False for any tmpdir, so without this every helper
    would raise ``JuiceFSUnavailable`` and every "rejects a bad path" assertion
    would pass for the wrong reason.
    """
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    return mount_root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory outside the mount — the target every escape test aims at."""
    d = tmp_path / "outside"
    d.mkdir()
    (d / "secret.txt").write_text("victim data")
    return d


def _session_dir(mount: Path, user: str = USER, conv: str = CONV) -> Path:
    d = mount / "users" / user / "sessions" / conv
    d.mkdir(parents=True, exist_ok=True)
    return d


def _workspace_file(mount: Path, rel: str, data: str, user: str = USER) -> Path:
    p = mount / "users" / user / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data)
    return p


# ── ensure_safe_path_id ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        ".",
        "",
        "a/b",
        "../etc",
        "/abs",
        "a\\b",
        "id with space",
        "ünïcode",
        "a\x00b",
        "x" * 65,
    ],
    ids=[
        "parent dir",
        "current dir",
        "empty",
        "separator",
        "traversal",
        "absolute",
        "backslash",
        "space",
        "unicode",
        "nul byte",
        "65 chars",
    ],
)
def test_an_id_that_could_escape_a_single_path_component_is_rejected(bad: str) -> None:
    # Every one of these, if accepted, becomes a directory name joined straight
    # into `<mount>/users/<uid>/sessions/<id>` — `..` and `/` walk out of the
    # user's tree entirely.
    with pytest.raises(ValueError):
        ensure_safe_path_id(bad)


@pytest.mark.parametrize(
    "good", ["a", "conv-a", "01H_ABC-xyz", "x" * 64], ids=["single", "kebab", "mixed", "64 chars"]
)
def test_a_normal_conversation_id_is_accepted(good: str) -> None:
    # The guard must not be so tight that real UUID/ULID-shaped ids are refused —
    # an over-strict pattern breaks every upload instead of blocking an attack.
    ensure_safe_path_id(good)


def test_the_rejection_message_names_the_field_that_was_bad() -> None:
    # Callers pass label= so the 4xx tells the user which id was wrong; a
    # hardcoded "id" makes conversation_id and integration_id indistinguishable.
    with pytest.raises(ValueError, match="conversation_id"):
        ensure_safe_path_id("../x", label="conversation_id")


# ── _contained ───────────────────────────────────────────────────────


def test_a_parent_directory_traversal_is_refused_rather_than_resolved(mount: Path) -> None:
    # The canonical attack: `sessions/<conv>/../../<victim>/...`.
    base = mount / "users" / USER
    base.mkdir(parents=True)
    with pytest.raises(ValueError, match="escapes"):
        _contained(base, f"../{OTHER}/secret.txt")


def test_an_absolute_path_is_refused_even_though_join_silently_discards_the_base(
    mount: Path,
) -> None:
    # pathlib's `base / "/etc/passwd"` evaluates to "/etc/passwd" — the base
    # vanishes. Containment is the only thing that notices.
    base = mount / "users" / USER
    base.mkdir(parents=True)
    with pytest.raises(ValueError, match="escapes"):
        _contained(base, "/etc/passwd")


def test_a_symlink_pointing_out_of_the_root_is_refused(mount: Path, outside: Path) -> None:
    # An agent can create symlinks inside its own workspace; following one must
    # not turn into an arbitrary host read.
    base = mount / "users" / USER
    base.mkdir(parents=True)
    (base / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        _contained(base, "escape/secret.txt")


def test_a_sibling_directory_sharing_the_roots_name_prefix_is_refused(mount: Path) -> None:
    # Kills the "startswith(str(base))" shape of containment: `/users/alice-evil`
    # is a string-prefix match for `/users/alice` but a different user's tree.
    users = mount / "users"
    (users / "alice").mkdir(parents=True)
    (users / "alice-evil").mkdir(parents=True)
    with pytest.raises(ValueError, match="escapes"):
        _contained(users / "alice", "../alice-evil/x.txt")


def test_a_nested_path_that_stays_inside_resolves_to_the_real_target(mount: Path) -> None:
    base = mount / "users" / USER
    base.mkdir(parents=True)
    assert _contained(base, "sessions/c1/artifacts/report.md") == (
        base / "sessions/c1/artifacts/report.md"
    )


def test_interior_dot_dot_segments_that_land_back_inside_are_allowed(mount: Path) -> None:
    # Normalization, not rejection: `a/../b` is a legitimate (if ugly) in-root
    # path and must not be treated as an escape.
    base = mount / "users" / USER
    base.mkdir(parents=True)
    assert _contained(base, "sessions/../notes.md") == base / "notes.md"


def test_the_error_names_the_root_it_failed_to_stay_inside(mount: Path) -> None:
    base = mount / "users" / USER
    base.mkdir(parents=True)
    with pytest.raises(ValueError, match="skill root"):
        _contained(base, "../x", root_label="skill root")


# ── path builders ────────────────────────────────────────────────────


def test_the_skills_tree_is_a_sibling_of_the_users_tree_not_a_child(mount: Path) -> None:
    # /skills/<uid> is a separate JuiceFS subtree mounted read-only at
    # /workspace/skills. Nesting it under /users/<uid> would make the sandbox's
    # overlay point at nothing.
    assert user_skills_path(USER) == mount / "skills" / USER
    assert user_workspace_path(USER) == mount / "users" / USER


def test_a_session_directory_is_scoped_under_the_owning_user(mount: Path) -> None:
    assert session_root(USER, CONV) == mount / "users" / USER / "sessions" / CONV


def test_a_traversal_conversation_id_cannot_produce_a_session_directory(mount: Path) -> None:
    # Without the guard this returns `<mount>/users/<uid>/sessions/../../<other>`,
    # which every caller then mkdirs and writes into.
    with pytest.raises(ValueError):
        session_root(USER, f"../../{OTHER}")


def test_the_sandbox_session_path_is_workspace_relative_not_host_absolute() -> None:
    # This string is handed to the model and to the sandbox; leaking the host
    # mount root would make every tool call reference an unreachable path.
    assert sandbox_session_path(CONV) == f"/workspace/sessions/{CONV}"


@pytest.mark.parametrize(
    ("given", "want"),
    [
        ("/workspace/sessions/c/x.pdf", "sessions/c/x.pdf"),
        ("/uploads/deck.pdf", "uploads/deck.pdf"),
        ("sessions/c/x.pdf", "sessions/c/x.pdf"),
        ("  /workspace/a.txt  ", "a.txt"),
    ],
)
def test_to_workspace_relative_path_strips_sandbox_prefix(given: str, want: str) -> None:
    # Agents hand us sandbox-visible paths; resolvers take workspace-relative ones.
    # A surviving leading "/" would discard the base in `base / rel` and escape
    # containment, so stripping it is load-bearing, not cosmetic.
    assert to_workspace_relative_path(given) == want


# ── mount gating ─────────────────────────────────────────────────────


async def test_an_existing_but_unmounted_directory_still_fails_loud(mount_root: Path) -> None:
    # The Dockerfile pre-creates an empty /mnt/jfs. If the mount check ever
    # degrades to is_dir(), every write silently lands on container-local disk
    # and is invisible to the sandbox — data loss with no error anywhere.
    assert mount_root.is_dir()
    assert _is_mounted() is False
    with pytest.raises(JuiceFSUnavailable):
        await ensure_user_workspace(USER)


async def test_a_write_without_a_mount_raises_instead_of_writing_locally(
    mount_root: Path,
) -> None:
    with pytest.raises(JuiceFSUnavailable):
        await write_session_file(USER, CONV, "a.txt", "hello")


async def test_a_read_without_a_mount_raises_instead_of_reporting_a_missing_file(
    mount_root: Path,
) -> None:
    # JuiceFSUnavailable and FileNotFoundError mean opposite things to callers:
    # one is "switch to the dockered API", the other is "the file is gone".
    with pytest.raises(JuiceFSUnavailable):
        await read_user_file(USER, "notes.md")


def test_the_unavailable_error_names_the_configured_mount_path(mount_root: Path) -> None:
    with pytest.raises(JuiceFSUnavailable, match=str(mount_root)):
        write_session_file_sync(USER, CONV, "a.txt", "hello")


# ── ensure_user_workspace / ensure_user_skills_dir ───────────────────


async def test_a_new_workspace_gets_its_internal_gaia_directory(mount: Path) -> None:
    # `.gaia` holds the VFS projections (todos, memory, tasks). Without it the
    # first sync writes into a non-existent parent and the whole turn fails.
    path = await ensure_user_workspace(USER)
    assert path == mount / "users" / USER
    assert (path / ".gaia").is_dir()


async def test_bootstrapping_an_existing_workspace_leaves_its_files_alone(mount: Path) -> None:
    # ensure_* runs on every session; a non-idempotent implementation would
    # wipe the user's files on their second message.
    first = await ensure_user_workspace(USER)
    (first / "keep.txt").write_text("mine")
    again = await ensure_user_workspace(USER)
    assert again == first
    assert (first / "keep.txt").read_text() == "mine"


async def test_the_skills_directory_is_created_in_the_skills_subtree(mount: Path) -> None:
    path = await ensure_user_skills_dir(USER)
    assert path == mount / "skills" / USER
    assert path.is_dir()
    assert not (mount / "users" / USER / "skills").exists()


# ── write_skill_file ─────────────────────────────────────────────────


async def test_a_skill_file_lands_under_the_owning_users_skill_directory(mount: Path) -> None:
    path = await write_skill_file(USER, "my-skill", "SKILL.md", "# body")
    assert path == mount / "skills" / USER / "my-skill" / "SKILL.md"
    assert path.read_text() == "# body"


async def test_a_nested_skill_file_creates_its_intermediate_directories(mount: Path) -> None:
    path = await write_skill_file(USER, "my-skill", "references/deep/notes.md", "x")
    assert path.read_text() == "x"


async def test_a_traversing_skill_asset_path_cannot_write_outside_the_skill_root(
    mount: Path,
) -> None:
    # Asset paths come from a third-party GitHub repo listing; `../../` in one
    # entry would let a published skill overwrite another user's files.
    (mount / "skills" / OTHER).mkdir(parents=True)
    with pytest.raises(ValueError, match="skill root"):
        await write_skill_file(USER, "my-skill", f"../../{OTHER}/pwned.md", "owned")
    assert not (mount / "skills" / OTHER / "pwned.md").exists()


async def test_a_symlinked_skill_asset_path_cannot_write_outside_the_skill_root(
    mount: Path, outside: Path
) -> None:
    skill_root = mount / "skills" / USER / "my-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="skill root"):
        await write_skill_file(USER, "my-skill", "escape/pwned.md", "owned")
    assert not (outside / "pwned.md").exists()


async def test_reinstalling_a_skill_replaces_the_body_rather_than_appending(mount: Path) -> None:
    # Skill upgrades rewrite SKILL.md in place; append mode would concatenate
    # two versions and the agent would read a self-contradicting instruction set.
    await write_skill_file(USER, "my-skill", "SKILL.md", "old body which is long")
    path = await write_skill_file(USER, "my-skill", "SKILL.md", "new")
    assert path.read_text() == "new"


async def test_non_ascii_skill_content_round_trips_as_utf8(mount: Path) -> None:
    body = "héllo — naïve ✓ 日本語"
    path = await write_skill_file(USER, "my-skill", "SKILL.md", body)
    assert path.read_bytes() == body.encode("utf-8")


async def test_binary_skill_content_is_written_verbatim(mount: Path) -> None:
    blob = b"\x89PNG\r\n\x1a\n\x00\xff"
    path = await write_skill_file(USER, "my-skill", "logo.png", blob)
    assert path.read_bytes() == blob


# ── write_session_file ───────────────────────────────────────────────


def test_a_session_write_returns_both_the_host_path_and_the_sandbox_path(mount: Path) -> None:
    host, sandbox = write_session_file_sync(USER, CONV, "user-uploaded/a.txt", "hi")
    assert host == mount / "users" / USER / "sessions" / CONV / "user-uploaded/a.txt"
    assert sandbox == f"/workspace/sessions/{CONV}/user-uploaded/a.txt"
    assert host.read_text() == "hi"


def test_a_traversing_upload_path_cannot_write_outside_the_session(mount: Path) -> None:
    # An uploaded filename reaches this as `relative_path`; `../../../.gaia/...`
    # would let a chat attachment overwrite the user's VFS projections.
    _session_dir(mount)
    with pytest.raises(ValueError, match="session root"):
        write_session_file_sync(USER, CONV, "../../../../etc/pwned", "owned")


def test_an_absolute_upload_path_cannot_write_outside_the_session(
    mount: Path, outside: Path
) -> None:
    _session_dir(mount)
    with pytest.raises(ValueError, match="session root"):
        write_session_file_sync(USER, CONV, str(outside / "pwned.txt"), "owned")
    assert not (outside / "pwned.txt").exists()


def test_a_traversing_conversation_id_is_rejected_before_anything_is_written(
    mount: Path,
) -> None:
    with pytest.raises(ValueError, match="conversation_id"):
        write_session_file_sync(USER, f"../../{OTHER}", "a.txt", "owned")
    assert not (mount / "users" / OTHER).exists()


def test_rewriting_a_session_file_truncates_the_previous_contents(mount: Path) -> None:
    write_session_file_sync(USER, CONV, "a.txt", "a much longer first version")
    host, _ = write_session_file_sync(USER, CONV, "a.txt", "short")
    assert host.read_text() == "short"


async def test_the_async_wrapper_writes_the_same_bytes_as_the_sync_core(mount: Path) -> None:
    host, sandbox = await write_session_file(USER, CONV, "a.txt", b"\x00\x01binary")
    assert host.read_bytes() == b"\x00\x01binary"
    assert sandbox == f"/workspace/sessions/{CONV}/a.txt"


# ── page_bounds ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("offset", "limit", "expected"),
    [
        (0, 2000, (1, 2000)),
        (1, 2000, (1, 2000)),
        (2, 1, (2, 2)),
        (3, 5, (3, 7)),
        (0, 1, (1, 1)),
        (0, 0, (1, 1)),
        (5, 0, (5, 5)),
        (0, -10, (1, 1)),
        (-4, 10, (1, 10)),
    ],
    ids=[
        "offset 0 means line 1",
        "offset 1 also means line 1",
        "limit 1 is a single line",
        "mid-file window",
        "first line only",
        "limit 0 clamps to one line",
        "limit 0 keeps the offset",
        "negative limit clamps to one line",
        "negative offset clamps to line 1",
    ],
)
def test_the_paged_line_range_is_one_indexed_and_inclusive_on_both_ends(
    offset: int, limit: int, expected: tuple[int, int]
) -> None:
    # Every read path (memory, JuiceFS, sandbox) slices with this. An off-by-one
    # here silently drops the first or last line of every file the agent reads.
    assert page_bounds(offset, limit) == expected


# ── read_user_file ───────────────────────────────────────────────────


async def test_a_whole_file_is_returned_with_its_newlines_stripped(mount: Path) -> None:
    _workspace_file(mount, "notes.md", "one\ntwo\nthree\n")
    lines, total = await read_user_file(USER, "notes.md")
    assert lines == ["one", "two", "three"]
    assert total == 3


async def test_a_final_line_without_a_trailing_newline_is_still_counted(mount: Path) -> None:
    _workspace_file(mount, "notes.md", "one\ntwo")
    lines, total = await read_user_file(USER, "notes.md")
    assert lines == ["one", "two"]
    assert total == 2


async def test_an_empty_file_reads_as_zero_lines(mount: Path) -> None:
    _workspace_file(mount, "empty.md", "")
    assert await read_user_file(USER, "empty.md") == ([], 0)


async def test_a_paged_read_returns_exactly_the_requested_window(mount: Path) -> None:
    _workspace_file(mount, "n.md", "".join(f"l{i}\n" for i in range(1, 11)))
    lines, total = await read_user_file(USER, "n.md", offset=3, limit=2)
    assert lines == ["l3", "l4"]
    # The total is the whole file, not the page — the UI shows "3-4 of 10".
    assert total == 10


async def test_a_page_starting_past_the_end_returns_nothing_but_the_real_total(
    mount: Path,
) -> None:
    _workspace_file(mount, "n.md", "a\nb\n")
    lines, total = await read_user_file(USER, "n.md", offset=99, limit=10)
    assert lines == []
    assert total == 2


async def test_a_page_that_runs_off_the_end_returns_the_remaining_lines(mount: Path) -> None:
    _workspace_file(mount, "n.md", "a\nb\nc\n")
    lines, _ = await read_user_file(USER, "n.md", offset=2, limit=100)
    assert lines == ["b", "c"]


async def test_undecodable_bytes_are_replaced_rather_than_killing_the_read(mount: Path) -> None:
    # Agents write latin-1 CSVs and truncated UTF-8 all the time; a strict decode
    # turns a readable file into an unhandled UnicodeDecodeError mid-tool-call.
    p = mount / "users" / USER / "bad.txt"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"caf\xe9\n")
    lines, total = await read_user_file(USER, "bad.txt")
    assert total == 1
    assert lines[0].startswith("caf")


async def test_a_missing_file_is_reported_as_missing_not_as_an_empty_file(mount: Path) -> None:
    (mount / "users" / USER).mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        await read_user_file(USER, "nope.md")


async def test_a_directory_is_not_readable_as_a_file(mount: Path) -> None:
    (mount / "users" / USER / "sessions").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        await read_user_file(USER, "sessions")


async def test_a_model_supplied_traversal_cannot_read_another_users_file(mount: Path) -> None:
    # The read tool passes the model's path straight through. This is the check
    # that keeps a hallucinated `../../user-2/...` from succeeding.
    _workspace_file(mount, "secret.md", "victim data", user=OTHER)
    with pytest.raises(ValueError, match="workspace root"):
        await read_user_file(USER, f"../{OTHER}/secret.md")


async def test_a_symlink_planted_in_the_workspace_cannot_read_the_host(
    mount: Path, outside: Path
) -> None:
    base = mount / "users" / USER
    base.mkdir(parents=True)
    (base / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="workspace root"):
        await read_user_file(USER, "escape/secret.txt")


async def test_a_skills_path_reads_from_the_skills_subtree_not_the_user_tree(
    mount: Path,
) -> None:
    # /workspace/skills is an overlay of /skills/<uid>. Routing it under
    # /users/<uid> makes every installed skill read as missing.
    p = mount / "skills" / USER / "my-skill" / "SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text("skill body")
    lines, _ = await read_user_file(USER, "skills/my-skill/SKILL.md")
    assert lines == ["skill body"]


async def test_a_directory_merely_starting_with_skills_stays_in_the_user_tree(
    mount: Path,
) -> None:
    # Prefix-matching on "skills" instead of "skills/" misroutes any user
    # directory whose name starts with those six characters.
    _workspace_file(mount, "skillset/plan.md", "user file")
    lines, _ = await read_user_file(USER, "skillset/plan.md")
    assert lines == ["user file"]


async def test_a_skills_path_cannot_traverse_back_out_of_the_skills_subtree(
    mount: Path,
) -> None:
    (mount / "skills" / OTHER).mkdir(parents=True)
    (mount / "skills" / OTHER / "secret.md").write_text("victim skill")
    with pytest.raises(ValueError, match="workspace root"):
        await read_user_file(USER, f"skills/../{OTHER}/secret.md")


def test_the_skills_prefix_maps_to_the_skills_root_with_the_prefix_stripped(mount: Path) -> None:
    base, rel = _host_base_and_rel(USER, "skills/my-skill/SKILL.md")
    assert base == mount / "skills" / USER
    assert rel == "my-skill/SKILL.md"


def test_the_bare_skills_path_maps_to_the_skills_root_itself(mount: Path) -> None:
    # `skills` alone must not slice to "my-skill"-style garbage via the
    # len("skills/") offset.
    base, rel = _host_base_and_rel(USER, "skills")
    assert base == mount / "skills" / USER
    assert rel == ""


# ── read_user_file_bytes ─────────────────────────────────────────────


async def test_binary_content_is_returned_byte_for_byte(mount: Path) -> None:
    p = mount / "users" / USER / "img.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n\xff\x00")
    assert (
        await read_user_file_bytes(USER, "img.png", max_bytes=100) == b"\x89PNG\r\n\x1a\n\xff\x00"
    )


async def test_a_file_exactly_at_the_byte_limit_is_still_allowed(mount: Path) -> None:
    # Off-by-one on the cap rejects a file the caller explicitly sized for.
    _workspace_file(mount, "x.bin", "a" * 10)
    assert await read_user_file_bytes(USER, "x.bin", max_bytes=10) == b"a" * 10


async def test_a_file_one_byte_over_the_limit_is_rejected(mount: Path) -> None:
    # The cap exists so an oversized image never reaches the LLM payload; a
    # short read would truncate it into a corrupt image instead of erroring.
    _workspace_file(mount, "x.bin", "a" * 11)
    with pytest.raises(ValueError, match="10-byte limit"):
        await read_user_file_bytes(USER, "x.bin", max_bytes=10)


async def test_an_empty_file_is_readable_even_with_a_zero_byte_limit(mount: Path) -> None:
    _workspace_file(mount, "x.bin", "")
    assert await read_user_file_bytes(USER, "x.bin", max_bytes=0) == b""


async def test_a_binary_read_cannot_traverse_out_of_the_user_tree(mount: Path) -> None:
    _workspace_file(mount, "secret.png", "victim", user=OTHER)
    with pytest.raises(ValueError, match="workspace root"):
        await read_user_file_bytes(USER, f"../{OTHER}/secret.png", max_bytes=100)


async def test_a_missing_binary_file_raises_not_found(mount: Path) -> None:
    (mount / "users" / USER).mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        await read_user_file_bytes(USER, "nope.png", max_bytes=100)


# ── resolve_user_file ────────────────────────────────────────────────


async def test_resolving_a_real_file_returns_its_host_path(mount: Path) -> None:
    p = _workspace_file(mount, "sessions/c1/scratch/data.json", "{}")
    assert await resolve_user_file(USER, "sessions/c1/scratch/data.json") == p


async def test_resolving_refuses_a_path_that_escapes_the_user_tree(mount: Path) -> None:
    # This path is handed to grep/jq as a shell argument — an escape here is a
    # direct host-file read, not just a workspace read.
    _workspace_file(mount, "secret.json", "{}", user=OTHER)
    with pytest.raises(ValueError, match="workspace root"):
        await resolve_user_file(USER, f"../{OTHER}/secret.json")


async def test_resolving_a_directory_raises_not_found(mount: Path) -> None:
    (mount / "users" / USER / "sessions").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        await resolve_user_file(USER, "sessions")


async def test_a_symlinked_mount_root_still_resolves_files_inside_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deployments mount JuiceFS behind a symlinked path. `_contained` resolves
    # the target, so the base must be resolved too or every legitimate read
    # inside a symlinked root raises "escapes the workspace root".
    real = tmp_path / "real_mount"
    real.mkdir()
    link = tmp_path / "link_mount"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(link))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)

    p = real / "users" / USER / "notes.md"
    p.parent.mkdir(parents=True)
    p.write_text("ok")
    assert await resolve_user_file(USER, "notes.md") == p


# ── user_owns_regular_file ───────────────────────────────────────────


async def test_a_real_user_file_counts_as_an_override_of_the_system_copy(mount: Path) -> None:
    _workspace_file(mount, "INDEX.md", "mine")
    assert await user_owns_regular_file(USER, "INDEX.md") is True


async def test_a_symlinked_system_projection_does_not_count_as_a_user_override(
    mount: Path,
) -> None:
    # The system workspace de-duplicates built-in docs as symlinks. Treating one
    # as a user override makes the read tool skip the in-memory body and serve
    # the projection instead.
    base = mount / "users" / USER
    base.mkdir(parents=True)
    real = mount / "system" / "GUIDE.md"
    real.parent.mkdir(parents=True)
    real.write_text("system doc")
    (base / "GUIDE.md").symlink_to(real)
    assert await user_owns_regular_file(USER, "GUIDE.md") is False


async def test_a_missing_file_is_not_an_override(mount: Path) -> None:
    (mount / "users" / USER).mkdir(parents=True)
    assert await user_owns_regular_file(USER, "INDEX.md") is False


async def test_a_directory_is_not_an_override(mount: Path) -> None:
    (mount / "users" / USER / "notes").mkdir(parents=True)
    assert await user_owns_regular_file(USER, "notes") is False


async def test_without_a_mount_the_override_check_reports_false_instead_of_raising(
    mount_root: Path,
) -> None:
    # Native dev has no mount; this must degrade to "use the in-memory copy"
    # rather than propagating JuiceFSUnavailable out of the read tool.
    (mount_root / "users" / USER).mkdir(parents=True)
    (mount_root / "users" / USER / "INDEX.md").write_text("mine")
    assert await user_owns_regular_file(USER, "INDEX.md") is False


# ── delete_user_workspace / delete_user_skill ────────────────────────


async def test_account_deletion_removes_both_the_workspace_and_the_skills_tree(
    mount: Path,
) -> None:
    # GDPR erasure: skills live in a separate subtree, so deleting only /users
    # leaves the user's installed skill bodies on disk forever.
    _workspace_file(mount, "sessions/c1/artifacts/a.md", "data")
    (mount / "skills" / USER / "my-skill").mkdir(parents=True)
    (mount / "skills" / USER / "my-skill" / "SKILL.md").write_text("body")

    await delete_user_workspace(USER)

    assert not (mount / "users" / USER).exists()
    assert not (mount / "skills" / USER).exists()


async def test_deleting_one_users_workspace_leaves_every_other_user_intact(mount: Path) -> None:
    _workspace_file(mount, "notes.md", "mine")
    _workspace_file(mount, "notes.md", "theirs", user=OTHER)
    await delete_user_workspace(USER)
    assert (mount / "users" / OTHER / "notes.md").read_text() == "theirs"


async def test_deleting_a_workspace_that_was_never_created_is_a_no_op(mount: Path) -> None:
    await delete_user_workspace(USER)
    assert not (mount / "users" / USER).exists()


async def test_without_a_mount_deletion_is_skipped_rather_than_hitting_local_disk(
    mount_root: Path,
) -> None:
    # An unmounted root means the container's own disk is sitting at that path.
    # rmtree-ing it would delete whatever else lives there.
    (mount_root / "users" / USER).mkdir(parents=True)
    (mount_root / "users" / USER / "notes.md").write_text("local")
    await delete_user_workspace(USER)
    assert (mount_root / "users" / USER / "notes.md").read_text() == "local"


async def test_uninstalling_a_skill_removes_only_that_skill(mount: Path) -> None:
    for name in ("keep-me", "remove-me"):
        d = mount / "skills" / USER / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(name)

    await delete_user_skill(USER, "remove-me")

    assert not (mount / "skills" / USER / "remove-me").exists()
    assert (mount / "skills" / USER / "keep-me" / "SKILL.md").read_text() == "keep-me"


async def test_uninstalling_a_skill_that_is_not_on_disk_is_a_no_op(mount: Path) -> None:
    # Mongo and JuiceFS can disagree after a partial install; the uninstall must
    # still clear the record rather than blowing up.
    (mount / "skills" / USER).mkdir(parents=True)
    await delete_user_skill(USER, "never-installed")
    assert (mount / "skills" / USER).is_dir()


async def test_without_a_mount_a_skill_uninstall_touches_nothing(mount_root: Path) -> None:
    d = mount_root / "skills" / USER / "my-skill"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("body")
    await delete_user_skill(USER, "my-skill")
    assert (d / "SKILL.md").read_text() == "body"
