"""SKILL.md catalog materialization: markers, skill dirs, connected flags, instructions.

This module is what the agent actually reads at inference time. A wrong write here
is invisible in logs: a skill body that never lands means the agent silently loses
a capability, a stale `.connected` marker means it claims an integration the user
disconnected, and a prune that is too eager deletes the system-file symlinks the
linker owns. All of those are caught here.

The functions take a `user_root: Path` — there is no mount lookup inside them — so
`tmp_path` IS the boundary and the real filesystem logic (`matches_text`,
`rglob` pruning, `ensure_safe_path_id`) runs unmocked. The only stub is the
in-memory skill registry (`skills_by_subagent`), which reads the repo's builtin
SKILL.md library off disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.workspace.skill_loader import BuiltinSkill
from app.agents.workspace.system_docs import INTEGRATIONS_GUIDE_MD
from app.constants.skills import EXECUTOR_SUBAGENT_ID, SKILL_BODY_FILENAME
from app.services.storage.sessions import skills as mod
from app.services.storage.sessions.skills import (
    _write_connected_marker,
    _write_skill_dir,
    materialize_instructions,
    materialize_skills,
    read_skills_marker,
    read_text_or_none,
    write_skills_marker,
)

INSTR_REL = ("integrations", "slack", "agent", "instructions.md")


def make_skill(
    slug: str,
    body: str = "# how to slack\n",
    resources: tuple[tuple[str, str], ...] = (),
    subagent_id: str = "slack",
) -> BuiltinSkill:
    return BuiltinSkill(
        slug=slug,
        name=slug,
        description="",
        target=f"{subagent_id}_agent",
        subagent_id=subagent_id,
        body=body,
        resources=resources,
    )


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[BuiltinSkill]]:
    """Drive materialize_skills from an in-test catalog.

    The real ``skills_by_subagent`` walks the repo's builtin SKILL.md library, so
    every assertion would otherwise depend on whichever skills happen to be
    checked in today.
    """
    table: dict[str, list[BuiltinSkill]] = {}
    monkeypatch.setattr(mod, "skills_by_subagent", lambda: table)
    return table


def skill_body(root: Path, iid: str, slug: str) -> Path:
    return root / "integrations" / iid / "agent" / "skills" / slug / SKILL_BODY_FILENAME


# ── read_text_or_none ────────────────────────────────────────────────


def test_a_marker_that_was_never_written_reads_as_none(tmp_path: Path) -> None:
    assert read_text_or_none(tmp_path / ".gaia" / "connected.v") is None


def test_an_empty_marker_reads_as_an_empty_string_rather_than_none(tmp_path: Path) -> None:
    # Load-bearing asymmetry with read_skills_marker: the connected-set signature
    # for a user with zero connected integrations IS "". If this collapsed "" to
    # None the staleness gate would never match, and every session bootstrap
    # would re-materialize the whole catalog for every unconnected user.
    marker = tmp_path / "connected.v"
    marker.write_text("", encoding="utf-8")
    assert read_text_or_none(marker) == ""


def test_a_marker_is_returned_verbatim_without_stripping(tmp_path: Path) -> None:
    # The gate compares this byte-for-byte against ",".join(sorted(connected)).
    # Stripping here (as read_skills_marker does) would make the two readers
    # interchangeable and hide which one a caller actually needs.
    marker = tmp_path / "connected.v"
    marker.write_text(" gmail,slack \n", encoding="utf-8")
    assert read_text_or_none(marker) == " gmail,slack \n"


def test_a_directory_where_a_marker_belongs_reads_as_none_instead_of_raising(
    tmp_path: Path,
) -> None:
    # exists() is True for a directory, so only the OSError handler stops an
    # IsADirectoryError from aborting the whole workspace bootstrap.
    (tmp_path / "connected.v").mkdir()
    assert read_text_or_none(tmp_path / "connected.v") is None


def test_a_marker_holding_undecodable_bytes_reads_as_none(tmp_path: Path) -> None:
    marker = tmp_path / "connected.v"
    marker.write_bytes(b"\xff\xfe\x00\x80")
    assert read_text_or_none(marker) is None


# ── read_skills_marker / write_skills_marker ─────────────────────────


def test_a_workspace_with_no_gaia_dir_has_no_skills_marker(tmp_path: Path) -> None:
    assert read_skills_marker(tmp_path) is None


def test_the_library_hash_round_trips_through_the_gaia_skills_marker(tmp_path: Path) -> None:
    # The literal path is asserted on purpose: changing SKILLS_HASH_MARKER
    # orphans every marker already on disk and forces a full re-materialize for
    # every existing user on the next deploy.
    write_skills_marker(tmp_path, "abc123def456")
    assert (tmp_path / ".gaia" / "skills.v").read_text(encoding="utf-8") == "abc123def456"
    assert read_skills_marker(tmp_path) == "abc123def456"


def test_a_trailing_newline_in_the_marker_still_matches_the_library_hash(tmp_path: Path) -> None:
    # An editor (or a shell `echo >`) leaves a newline. Without the strip the
    # gate would never match and the catalog would be rewritten every bootstrap.
    marker = tmp_path / ".gaia" / "skills.v"
    marker.parent.mkdir(parents=True)
    marker.write_text("abc123def456\n", encoding="utf-8")
    assert read_skills_marker(tmp_path) == "abc123def456"


@pytest.mark.parametrize("blank", ["", "   ", "\n\n", "\t \n"])
def test_a_blank_skills_marker_reads_as_none_so_the_catalog_is_rebuilt(
    tmp_path: Path, blank: str
) -> None:
    # A truncated marker (interrupted write) must read as "no marker", not as a
    # hash of "" that could accidentally equal a caller's expected value.
    marker = tmp_path / ".gaia" / "skills.v"
    marker.parent.mkdir(parents=True)
    marker.write_text(blank, encoding="utf-8")
    assert read_skills_marker(tmp_path) is None


def test_a_skills_marker_holding_undecodable_bytes_reads_as_none(tmp_path: Path) -> None:
    marker = tmp_path / ".gaia" / "skills.v"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"\xff\xfe\x00")
    assert read_skills_marker(tmp_path) is None


def test_stamping_the_marker_creates_the_gaia_dir_when_it_is_missing(tmp_path: Path) -> None:
    # First-ever provisioning has no .gaia dir; without the mkdir the stamp
    # raises FileNotFoundError and the whole materialization aborts after
    # having already written the catalog.
    write_skills_marker(tmp_path, "v1")
    assert (tmp_path / ".gaia").is_dir()


def test_restamping_replaces_the_previous_hash_rather_than_appending(tmp_path: Path) -> None:
    write_skills_marker(tmp_path, "a" * 32)
    write_skills_marker(tmp_path, "b" * 4)
    assert read_skills_marker(tmp_path) == "bbbb"


def test_a_unicode_marker_value_survives_the_round_trip(tmp_path: Path) -> None:
    write_skills_marker(tmp_path, "héllo-☕")
    assert read_skills_marker(tmp_path) == "héllo-☕"


# ── _write_skill_dir ─────────────────────────────────────────────────


def test_writing_a_skill_lands_its_body_and_counts_one_write(tmp_path: Path) -> None:
    written = _write_skill_dir(tmp_path / "researching", make_skill("researching", body="B\n"))
    assert written == 1
    assert (tmp_path / "researching" / SKILL_BODY_FILENAME).read_text() == "B\n"


def test_resyncing_an_unchanged_skill_does_zero_io(tmp_path: Path) -> None:
    # Steady state is every session bootstrap for every user. A materializer that
    # rewrites unconditionally turns a no-op into N writes per user per turn on a
    # shared JuiceFS mount.
    skill = make_skill("researching", resources=(("reference.md", "R"),))
    _write_skill_dir(tmp_path / "researching", skill)
    assert _write_skill_dir(tmp_path / "researching", skill) == 0


def test_a_skill_body_edited_on_disk_is_restored_from_the_registry(tmp_path: Path) -> None:
    # The registry is the source of truth; an agent `Edit` on the projection must
    # not survive the next sync or the two silently diverge.
    skill = make_skill("researching", body="canonical\n")
    _write_skill_dir(tmp_path / "researching", skill)
    (tmp_path / "researching" / SKILL_BODY_FILENAME).write_text("tampered")

    assert _write_skill_dir(tmp_path / "researching", skill) == 1
    assert (tmp_path / "researching" / SKILL_BODY_FILENAME).read_text() == "canonical\n"


def test_bundled_resources_land_at_their_nested_paths_and_are_counted(tmp_path: Path) -> None:
    # Multi-file skills break entirely if only the body is written — the SKILL.md
    # tells the agent to read templates/report.md and the read 404s.
    skill = make_skill(
        "researching",
        resources=(("reference.md", "REF"), ("templates/report.md", "TPL")),
    )
    written = _write_skill_dir(tmp_path / "researching", skill)

    assert written == 3
    assert (tmp_path / "researching" / "reference.md").read_text() == "REF"
    assert (tmp_path / "researching" / "templates" / "report.md").read_text() == "TPL"


def test_a_resource_that_left_the_manifest_is_pruned(tmp_path: Path) -> None:
    # A renamed template must not outlive the deploy that renamed it, or the
    # agent reads a stale copy that no longer matches the SKILL.md instructions.
    _write_skill_dir(tmp_path / "r", make_skill("r", resources=(("old.md", "X"),)))
    _write_skill_dir(tmp_path / "r", make_skill("r", resources=(("new.md", "X"),)))

    assert not (tmp_path / "r" / "old.md").exists()
    assert (tmp_path / "r" / "new.md").read_text() == "X"


def test_a_nested_resource_still_in_the_manifest_survives_the_prune(tmp_path: Path) -> None:
    # The prune key is the POSIX path relative to the skill dir, not the
    # basename. Comparing basenames would delete templates/report.md on every
    # single sync and then rewrite it — an infinite churn loop on the mount.
    skill = make_skill("r", resources=(("templates/report.md", "TPL"),))
    _write_skill_dir(tmp_path / "r", skill)
    _write_skill_dir(tmp_path / "r", skill)

    assert (tmp_path / "r" / "templates" / "report.md").read_text() == "TPL"


def test_a_stray_file_dropped_into_a_skill_dir_is_removed(tmp_path: Path) -> None:
    _write_skill_dir(tmp_path / "r", make_skill("r"))
    (tmp_path / "r" / "junk.txt").write_text("agent scratch")
    _write_skill_dir(tmp_path / "r", make_skill("r"))

    assert not (tmp_path / "r" / "junk.txt").exists()


def test_a_symlinked_resource_is_never_unlinked_by_the_prune(tmp_path: Path) -> None:
    # link_system_files_into_workspace owns these symlinks: they point into the
    # shared _system subtree and de-duplicate one copy per user. Pruning them
    # here would delete the real projection and leave the skill unreadable.
    shared = tmp_path / "shared.md"
    shared.write_text("shared body")
    slug_dir = tmp_path / "r"
    _write_skill_dir(slug_dir, make_skill("r"))
    (slug_dir / "linked.md").symlink_to(shared)

    _write_skill_dir(slug_dir, make_skill("r"))
    assert (slug_dir / "linked.md").is_symlink()


def test_a_symlinked_body_is_left_in_place_rather_than_replaced_with_a_real_file(
    tmp_path: Path,
) -> None:
    # Same de-duplication contract for skill.md itself: matches_text treats a
    # symlink as "already correct". Replacing it with a real copy per user is a
    # silent storage blow-up on a shared mount.
    shared = tmp_path / "shared.md"
    shared.write_text("totally different body")
    slug_dir = tmp_path / "r"
    slug_dir.mkdir()
    (slug_dir / SKILL_BODY_FILENAME).symlink_to(shared)

    assert _write_skill_dir(slug_dir, make_skill("r", body="registry body\n")) == 0
    assert (slug_dir / SKILL_BODY_FILENAME).is_symlink()


def test_a_subdirectory_in_a_skill_dir_is_not_unlinked_as_a_stray_file(tmp_path: Path) -> None:
    # rglob yields directories too; unlink() on one raises IsADirectoryError and
    # takes down the whole bootstrap for that user.
    _write_skill_dir(tmp_path / "r", make_skill("r"))
    (tmp_path / "r" / "assets").mkdir()

    _write_skill_dir(tmp_path / "r", make_skill("r"))
    assert (tmp_path / "r" / "assets").is_dir()


def test_a_skill_with_an_empty_body_still_produces_a_readable_file(tmp_path: Path) -> None:
    # A SKILL.md that is nothing but frontmatter parses to an empty body. It must
    # still materialize, or the catalog advertises a skill whose file is missing.
    _write_skill_dir(tmp_path / "r", make_skill("r", body=""))
    assert (tmp_path / "r" / SKILL_BODY_FILENAME).read_text() == ""


# ── _write_connected_marker ──────────────────────────────────────────


def test_connecting_an_integration_drops_the_connected_marker(tmp_path: Path) -> None:
    tmp_path.joinpath("agent").mkdir()
    _write_connected_marker(tmp_path / "agent", connected=True)
    assert (tmp_path / "agent" / ".connected").is_file()


def test_disconnecting_an_integration_removes_a_previously_dropped_marker(tmp_path: Path) -> None:
    # Without the removal the agent's single-stat check keeps reporting an
    # integration the user has revoked, so it plans tool calls that will 401.
    agent = tmp_path / "agent"
    agent.mkdir()
    _write_connected_marker(agent, connected=True)
    _write_connected_marker(agent, connected=False)
    assert not (agent / ".connected").exists()


def test_removing_a_marker_that_was_never_dropped_does_not_raise(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    agent.mkdir()
    _write_connected_marker(agent, connected=False)
    assert not (agent / ".connected").exists()


# ── materialize_skills ───────────────────────────────────────────────


def test_the_integrations_guide_is_written_but_not_counted_as_a_skill_write(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    # The return value feeds "did the library change?" metrics; folding the
    # always-present GUIDE into it would report a change on every sync.
    assert materialize_skills(tmp_path, set()) == 0
    assert (tmp_path / "integrations" / "GUIDE.md").read_text() == INTEGRATIONS_GUIDE_MD


def test_a_corrupted_integrations_guide_is_restored_on_the_next_sync(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    materialize_skills(tmp_path, set())
    (tmp_path / "integrations" / "GUIDE.md").write_text("agent overwrote this")

    materialize_skills(tmp_path, set())
    assert (tmp_path / "integrations" / "GUIDE.md").read_text() == INTEGRATIONS_GUIDE_MD


def test_each_integrations_skills_land_under_its_own_agent_skills_dir(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    # This exact path is what system_files/discovery tell the agent to read; a
    # different nesting means every `read` of a skill body 404s.
    registry["slack"] = [make_skill("triage", body="T\n")]
    registry["gmail"] = [make_skill("drafting", body="D\n", subagent_id="gmail")]

    materialize_skills(tmp_path, set())
    assert skill_body(tmp_path, "slack", "triage").read_text() == "T\n"
    assert skill_body(tmp_path, "gmail", "drafting").read_text() == "D\n"


def test_executor_skills_are_kept_out_of_the_integrations_tree(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    # General skills belong in the /skills/<uid> overlay the sandbox mounts at
    # /workspace/skills. Writing them under integrations/executor/ puts them
    # somewhere nothing ever reads.
    registry[EXECUTOR_SUBAGENT_ID] = [make_skill("create-artifacts")]
    registry["slack"] = [make_skill("triage")]

    materialize_skills(tmp_path, set())
    assert not (tmp_path / "integrations" / EXECUTOR_SUBAGENT_ID).exists()
    assert skill_body(tmp_path, "slack", "triage").is_file()


def test_an_integration_that_owns_no_skills_gets_no_directory(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    # An empty agent/skills/ dir advertises an integration with nothing to read
    # and, worse, would collect a .connected marker in a tree the agent scans.
    registry["slack"] = []

    materialize_skills(tmp_path, {"slack"})
    assert not (tmp_path / "integrations" / "slack").exists()


def test_only_connected_integrations_get_the_connected_marker(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    registry["slack"] = [make_skill("triage")]
    registry["gmail"] = [make_skill("drafting", subagent_id="gmail")]

    materialize_skills(tmp_path, {"slack"})
    assert (tmp_path / "integrations" / "slack" / "agent" / ".connected").is_file()
    assert not (tmp_path / "integrations" / "gmail" / "agent" / ".connected").exists()


def test_disconnecting_an_integration_clears_its_marker_on_the_next_sync(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    registry["slack"] = [make_skill("triage")]
    materialize_skills(tmp_path, {"slack"})

    materialize_skills(tmp_path, set())
    assert not (tmp_path / "integrations" / "slack" / "agent" / ".connected").exists()


def test_the_return_count_is_every_file_written_across_every_integration(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    registry["slack"] = [
        make_skill("triage", resources=(("reference.md", "R"),)),
        make_skill("digest"),
    ]
    registry["gmail"] = [make_skill("drafting", subagent_id="gmail")]

    assert materialize_skills(tmp_path, set()) == 4


def test_a_second_sync_of_an_unchanged_library_writes_nothing(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    registry["slack"] = [make_skill("triage", resources=(("reference.md", "R"),))]
    materialize_skills(tmp_path, {"slack"})

    assert materialize_skills(tmp_path, {"slack"}) == 0


def test_a_changed_skill_body_is_rewritten_on_the_next_sync(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    registry["slack"] = [make_skill("triage", body="v1\n")]
    materialize_skills(tmp_path, set())

    registry["slack"] = [make_skill("triage", body="v2\n")]
    assert materialize_skills(tmp_path, set()) == 1
    assert skill_body(tmp_path, "slack", "triage").read_text() == "v2\n"


# ── materialize_instructions ─────────────────────────────────────────


def test_an_instruction_lands_beside_the_integrations_skills(tmp_path: Path) -> None:
    assert materialize_instructions(tmp_path, {"slack": "focus #eng"}) == 1
    assert tmp_path.joinpath(*INSTR_REL).read_text() == "focus #eng"


def test_resyncing_identical_instructions_neither_rewrites_nor_prunes(tmp_path: Path) -> None:
    # Both halves matter: the write must be skipped (steady state is zero I/O)
    # AND the stale sweep must leave a still-current projection alone.
    materialize_instructions(tmp_path, {"slack": "focus #eng"})

    assert materialize_instructions(tmp_path, {"slack": "focus #eng"}) == 0
    assert tmp_path.joinpath(*INSTR_REL).read_text() == "focus #eng"


def test_edited_instructions_replace_the_previous_projection(tmp_path: Path) -> None:
    materialize_instructions(tmp_path, {"slack": "v1"})

    assert materialize_instructions(tmp_path, {"slack": "v2"}) == 1
    assert tmp_path.joinpath(*INSTR_REL).read_text() == "v2"


def test_a_cleared_instruction_has_its_stale_projection_removed(tmp_path: Path) -> None:
    # Mongo is the source of truth. A projection that outlives its record keeps
    # feeding the subagent guidance the user deliberately deleted.
    materialize_instructions(tmp_path, {"slack": "v1", "gmail": "g1"})

    assert materialize_instructions(tmp_path, {"gmail": "g1"}) == 0
    assert not tmp_path.joinpath(*INSTR_REL).exists()
    assert (tmp_path / "integrations" / "gmail" / "agent" / "instructions.md").read_text() == "g1"


def test_the_stale_sweep_never_touches_skill_bodies_or_connected_markers(
    tmp_path: Path, registry: dict[str, list[BuiltinSkill]]
) -> None:
    # The sweep globs */agent — one careless widening (*/agent/**) would wipe the
    # materialized catalog every time a user clears one instruction.
    registry["slack"] = [make_skill("triage")]
    materialize_skills(tmp_path, {"slack"})
    materialize_instructions(tmp_path, {"slack": "v1"})

    materialize_instructions(tmp_path, {})
    assert skill_body(tmp_path, "slack", "triage").is_file()
    assert (tmp_path / "integrations" / "slack" / "agent" / ".connected").is_file()
    assert not tmp_path.joinpath(*INSTR_REL).exists()


def test_an_empty_instruction_body_produces_no_projection(tmp_path: Path) -> None:
    assert materialize_instructions(tmp_path, {"slack": ""}) == 0
    assert not tmp_path.joinpath(*INSTR_REL).exists()


@pytest.mark.parametrize(
    "evil",
    [
        "",
        ".",
        "slack/../../evil",
        "..\\evil",
        "slack\nevil",
        "sl ack",
        "café",
        "/etc/passwd",
        "x" * 65,
        "slack;rm",
    ],
)
def test_a_crafted_integration_id_writes_nothing_anywhere(tmp_path: Path, evil: str) -> None:
    # integration ids reach here from Mongo documents an agent tool can write.
    # A single unsafe component escapes the user's root and lands on another
    # tenant's tree on the shared mount.
    root = tmp_path / "u1"
    root.mkdir()
    sibling = tmp_path / "victim"
    sibling.mkdir()

    assert materialize_instructions(root, {evil: "payload"}) == 0
    assert list(tmp_path.rglob("instructions.md")) == []
    assert list(sibling.iterdir()) == []


def test_an_integration_id_of_exactly_sixty_four_characters_is_accepted(tmp_path: Path) -> None:
    # The boundary of the safe-id pattern: 64 in, 65 out. Tightening it silently
    # drops legitimate long integration ids from every user's workspace.
    iid = "a" * 64
    assert materialize_instructions(tmp_path, {iid: "ok"}) == 1
    assert (tmp_path / "integrations" / iid / "agent" / "instructions.md").read_text() == "ok"


def test_an_unsafe_id_does_not_stop_the_remaining_instructions_from_syncing(
    tmp_path: Path,
) -> None:
    # The unsafe entry comes FIRST here: a guard that raises or breaks instead of
    # continuing would silently drop every instruction after it.
    written = materialize_instructions(tmp_path, {"../../evil": "bad", "slack": "good"})

    assert written == 1
    assert tmp_path.joinpath(*INSTR_REL).read_text() == "good"


def test_unicode_instructions_survive_the_round_trip(tmp_path: Path) -> None:
    # A non-UTF-8 write would mangle the body AND make matches_text fail forever,
    # rewriting the file on every single sync.
    body = "réunion ☕\n日本語のメモ\n"
    assert materialize_instructions(tmp_path, {"slack": body}) == 1
    assert tmp_path.joinpath(*INSTR_REL).read_text(encoding="utf-8") == body
    assert materialize_instructions(tmp_path, {"slack": body}) == 0


def test_syncing_into_a_workspace_with_no_integrations_tree_is_a_no_op(tmp_path: Path) -> None:
    assert materialize_instructions(tmp_path, {}) == 0
    assert list(tmp_path.iterdir()) == []
