"""Workspace provisioning composed end to end, against a real filesystem.

``provision_user_workspace`` is what a user's ``/workspace`` actually *is*: the
system-file symlinks, the SKILL.md catalog, the ``.connected`` markers the
prompt stats, and the instructions projection. It is run on registration, on
every integration connect/disconnect, and on startup for every stale user —
and nothing else re-runs it, so whatever it leaves on disk is what the agent
sees until the next such event.

The unit tier covers each writer in isolation with the others stubbed. What it
cannot cover is the composition, and the composition is where the interesting
failures are: the linker writes symlinks and the materializer then walks the
same directories with a pruner, one module computes a path and another writes
to it, and a three-marker gate decides whether any of it runs at all. Those
three modules only ever meet here.

**The trap this file exists to avoid.** ``materialize_user_integrations`` and
``delete_session_dir`` open with ``if not _is_mounted(): return``. A test that
calls ``provision_user_workspace`` without a mount runs no materializer, writes
no file, raises nothing, and passes — asserting nothing at all. Every test below
runs against ``mount``, which points the module at a real tmpdir *and* patches
``_is_mounted``, and every assertion is on a file that either is or is not on
disk. ``TestWithoutAMount`` pins the vacuous case explicitly so it stays a
deliberate no-op rather than a silent one.

No FUSE, no docker, no Mongo: the only stub is the per-user instructions read
(``get_all_instructions``), which is the single Mongo touch on this path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.workspace.skill_loader import library_hash, skills_by_subagent
from app.agents.workspace.system_files import system_files
from app.config.settings import settings
from app.services.storage.sessions import lifecycle as lc
from app.services.storage.sessions.skills import materialize_skills
from app.services.storage.system_workspace import (
    SANDBOX_SYSTEM_DIR,
    SYSTEM_SUBDIR,
    ensure_system_subtree,
)

pytestmark = pytest.mark.e2e

USER = "user-1"
OTHER = "user-2"

SKILLS_MARKER = ".gaia/skills.v"
CONNECTED_MARKER = ".gaia/connected.v"
INSTRUCTIONS_MARKER = ".gaia/instructions.v"

# An integration that really ships skills — asserting `.connected` on an id with
# no skills would pass against a materializer that never ran, since the loop it
# lives in is keyed on the skill registry.
INTEGRATION = "gmail"
OTHER_INTEGRATION = "linear"


@pytest.fixture
def mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real tmpdir that also answers the mountpoint check.

    ``Path.is_mount()`` is False for every tmpdir, and the two entry points here
    silently return when it is — so without this patch the whole file would
    assert on a workspace nothing ever wrote to.

    Both namespaces, and this is not belt-and-braces: ``lifecycle`` imported
    ``_is_mounted`` by value, while ``system_workspace`` reaches ``_require_mount``
    which reads the ``juicefs`` module global. Patching only ``juicefs`` leaves
    the materializer gate live — the first draft of this file did exactly that
    and 16 tests reported on files no writer had ever been reached to create.
    """
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    monkeypatch.setattr(lc, "_is_mounted", lambda: True)
    return root


@pytest.fixture
def unmounted_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The same real tmpdir, honestly reporting itself as not a mountpoint."""
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    return root


@pytest.fixture
def instructions(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Stands in for the Mongo-backed per-user instructions read.

    Mutate the returned dict to model the user editing their instructions
    between provisioning runs.
    """
    payload: dict[str, str] = {}

    async def get_all(user_id: str) -> dict[str, str]:
        return dict(payload)

    monkeypatch.setattr(
        "app.services.integration_instructions_service.get_all_instructions", get_all
    )
    return payload


@pytest.fixture
async def bootstrapped(mount: Path, instructions: dict[str, str]) -> Path:
    """The shared ``_system`` subtree, written exactly as startup writes it.

    ``init_system_subtree`` runs before any user is provisioned; without it
    ``link_system_files_into_workspace`` short-circuits and the whole symlink
    layer is skipped (see ``TestWithoutTheSharedSubtree``).
    """
    await ensure_system_subtree()
    return mount


def user_tree(mount: Path, user: str = USER) -> Path:
    return mount / "users" / user


def children(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir())


def agent_dir(mount: Path, iid: str = INTEGRATION, user: str = USER) -> Path:
    return user_tree(mount, user) / "integrations" / iid / "agent"


def connected_marker(mount: Path, iid: str = INTEGRATION, user: str = USER) -> Path:
    return agent_dir(mount, iid, user) / ".connected"


def instructions_file(mount: Path, iid: str = INTEGRATION, user: str = USER) -> Path:
    return agent_dir(mount, iid, user) / "instructions.md"


def link_location(mount: Path, rel_path: str, user: str = USER) -> Path:
    """Where a system file's per-user pointer must land.

    Mirrors the ``skills/`` overlay split by hand rather than importing
    ``_host_base_and_rel``: the point is to check the routing, and reusing the
    routing function would only prove it agrees with itself.
    """
    if rel_path == "skills" or rel_path.startswith("skills/"):
        return mount / "skills" / user / rel_path[len("skills/") :]
    return user_tree(mount, user) / rel_path


def real_files(root: Path) -> set[str]:
    """Every non-symlink regular file under ``root``, root-relative."""
    if not root.exists():
        return set()
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


class TestTheProvisionedTree:
    """What is actually on disk after the call registration makes."""

    async def test_provisioning_creates_the_user_workspace(self, bootstrapped: Path):
        await lc.provision_user_workspace(USER)

        assert user_tree(bootstrapped).is_dir()

    async def test_every_system_file_gets_a_pointer_in_the_users_tree(self, bootstrapped: Path):
        """The load-bearing agreement. ``system_files()`` decides what the read
        tool serves from memory and what the prompt names; ``_link_location``
        decides where the pointer lands. They are computed in different modules,
        and a disagreement means in-sandbox ``cat``/``ls``/``grep`` find nothing
        at a path the agent was told to use — with no error anywhere."""
        await lc.provision_user_workspace(USER)

        missing = [
            f.rel_path
            for f in system_files()
            if not link_location(bootstrapped, f.rel_path).is_symlink()
        ]

        assert missing == [], f"no symlink placed for: {missing[:5]}"

    async def test_each_pointer_aims_at_a_file_that_exists_in_the_shared_subtree(
        self, bootstrapped: Path
    ):
        """A symlink into ``_system`` is only useful if ``_system`` holds that
        exact path. The link writer and the subtree writer derive their paths
        independently, so a prefix drift leaves 63 dangling links that resolve
        to nothing inside the sandbox too."""
        await lc.provision_user_workspace(USER)

        dangling = []
        for f in system_files():
            target = link_location(bootstrapped, f.rel_path).readlink().as_posix()
            assert target.startswith(f"{SANDBOX_SYSTEM_DIR}/"), target
            rel_in_subtree = target[len(SANDBOX_SYSTEM_DIR) + 1 :]
            if not (bootstrapped / SYSTEM_SUBDIR / rel_in_subtree).is_file():
                dangling.append(target)

        assert dangling == [], f"points into _system at paths that do not exist: {dangling[:5]}"

    async def test_the_pointer_target_is_the_in_sandbox_path_not_a_host_path(
        self, bootstrapped: Path
    ):
        """Deliberately broken host-side: the target is resolved inside the
        sandbox, where ``mount_juicefs.sh`` bind-mounts ``/_system`` at
        ``/workspace/.system``. A host-absolute target would resolve for the API
        process and for nothing the agent runs."""
        link = link_location(bootstrapped, "INDEX.md")

        await lc.provision_user_workspace(USER)

        assert link.readlink().as_posix() == "/workspace/.system/INDEX.md"
        assert not link.resolve().exists()

    async def test_the_executor_skills_land_in_the_skills_overlay_not_the_user_tree(
        self, bootstrapped: Path
    ):
        """``/workspace/skills`` is a separate JuiceFS subtree (``/skills/<uid>``)
        mounted over the user tree. An executor skill written under
        ``users/<uid>/skills`` lands in the shadowed copy and is invisible."""
        await lc.provision_user_workspace(USER)

        assert (bootstrapped / "skills" / USER / "create-artifacts" / "skill.md").is_symlink()
        assert not (user_tree(bootstrapped) / "skills").exists()

    async def test_an_integration_skill_lands_under_its_integration(self, bootstrapped: Path):
        await lc.provision_user_workspace(USER)

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()

    async def test_a_multi_file_skills_bundled_resources_are_all_placed(self, bootstrapped: Path):
        """A skill whose SKILL.md points at ``reference.md`` / ``scripts/`` is
        broken, not degraded, when only the body is materialized — the agent
        reads an instruction to open a file that is not there.

        This asserts the *linker's* output: once ``_system`` exists every one of
        these is a symlink, and ``_write_skill_dir``'s pruner skips symlinks
        entirely. The materializer's own copies are pinned in
        ``TestTheFallbackCopiesSurviveTheirOwnPruner`` below, which is the half
        that can actually regress.
        """
        skill_dir = user_tree(bootstrapped) / "integrations/docgen/agent/skills/create-docx"

        await lc.provision_user_workspace(USER)

        assert (skill_dir / "skill.md").is_symlink()
        assert (skill_dir / "reference.md").is_symlink()
        assert (skill_dir / "scripts" / "build.sh").is_symlink()

    async def test_provisioning_stamps_all_three_staleness_markers(self, bootstrapped: Path):
        """These three files are the entire gate. An unstamped marker means the
        full catalog is rewritten on every integration change forever."""
        await lc.provision_user_workspace(USER, {INTEGRATION})
        root = user_tree(bootstrapped)

        assert (root / SKILLS_MARKER).read_text() == library_hash()
        assert (root / CONNECTED_MARKER).read_text() == INTEGRATION
        assert (root / INSTRUCTIONS_MARKER).is_file()

    async def test_the_catalog_covers_every_integration_that_ships_skills(self, bootstrapped: Path):
        """Not just the connected ones: the catalog is what tells the agent an
        integration *could* be used. Materializing only connected integrations
        would make an unconnected one un-discoverable and un-suggestable."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        expected = {iid for iid, skills in skills_by_subagent().items() if iid != "executor"}
        present = {
            p.name for p in (user_tree(bootstrapped) / "integrations").iterdir() if p.is_dir()
        }

        assert expected <= present, f"missing from the catalog: {expected - present}"


class TestTheFallbackCopiesSurviveTheirOwnPruner:
    """``_write_skill_dir`` writes a skill's resources and then, in the same
    pass, walks the directory deleting anything not in the manifest.

    This is the one path in provisioning that *deletes* files it has no second
    copy of, and it has been wrong before: the pruner compared ``existing.name``
    against a manifest holding skill-relative keys like ``templates/report.mjs``,
    so every nested resource was unlinked microseconds after being written. The
    skill body survived, which is why it looked fine — the agent got a SKILL.md
    telling it to open ``templates/`` files that were no longer there.

    Nothing above catches it. Once the shared ``_system`` subtree exists the
    linker has replaced all of these with symlinks, and the pruner skips
    symlinks, so the bug is invisible in the bootstrapped fixture. These call the
    materializer directly, on a bare directory, which is exactly the state it
    runs in before the linker (and the state it stays in when ``_system`` is
    unavailable).
    """

    #: A real multi-file builtin: a body, a flat resource, and two nested ones.
    SKILL_DIR = "integrations/docgen/agent/skills/create-docx"
    NESTED = ("scripts/build.sh", "templates/report.mjs")

    def test_nested_resources_survive_the_pass_that_wrote_them(self, tmp_path: Path):
        materialize_skills(tmp_path, set())
        skill_dir = tmp_path / self.SKILL_DIR

        missing = [rel for rel in self.NESTED if not (skill_dir / rel).is_file()]

        assert missing == [], f"written and then pruned in the same pass: {missing}"

    def test_the_nested_resource_holds_the_shipped_content(self, tmp_path: Path):
        """Existence is not enough — an empty or truncated file satisfies
        ``is_file()`` and still breaks the script the skill tells the agent to
        run."""
        materialize_skills(tmp_path, set())
        skill = next(s for s in skills_by_subagent()["docgen"] if s.slug == "create-docx")
        expected = dict(skill.resources)["templates/report.mjs"]

        body = (tmp_path / self.SKILL_DIR / "templates/report.mjs").read_text()

        assert body == expected

    def test_a_resource_that_left_the_manifest_is_removed(self, tmp_path: Path):
        """The control. Without it, deleting the pruner outright would leave
        every test above green — and a renamed template would outlive the
        registry change forever, shadowed by a stale copy."""
        materialize_skills(tmp_path, set())
        stale = tmp_path / self.SKILL_DIR / "templates" / "retired.mjs"
        stale.write_text("a template that was renamed two releases ago")

        materialize_skills(tmp_path, set())

        assert not stale.exists()

    def test_a_second_pass_rewrites_nothing_and_deletes_nothing(self, tmp_path: Path):
        """Provisioning re-runs on every integration connect/disconnect. A pass
        that churns files each time defeats the ``matches_text`` de-duplication
        and, worse, means the prune is deciding something new every run."""
        materialize_skills(tmp_path, set())
        before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}

        written = materialize_skills(tmp_path, set())
        after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}

        assert written == 0
        assert after == before


class TestDeDuplication:
    """One copy of every system body on the whole mount, not one per user.

    This is the entire reason ``_system`` exists. ``matches_text`` returning True
    for a symlink is what keeps the copy-writers from clobbering the pointers —
    lose that and every user silently gets 63 full copies back.
    """

    async def test_no_system_body_is_copied_into_the_users_tree(self, bootstrapped: Path):
        """The precise regression: a materializer that overwrites the symlink
        with a real copy. Nothing errors — storage just grows per user and the
        shared subtree stops being the source of truth for that file."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        system_rel = {f.rel_path for f in system_files()}
        copied = [rel for rel in real_files(user_tree(bootstrapped)) if rel in system_rel]

        assert copied == [], f"materialized a per-user copy over the symlink: {copied[:5]}"

    async def test_the_only_real_files_in_the_users_tree_are_the_per_user_ones(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Whitelist rather than blacklist: a new writer that starts dropping
        per-user copies somewhere unexpected shows up here even if its path is
        not in the system manifest."""
        instructions[INTEGRATION] = "always cc legal"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert real_files(user_tree(bootstrapped)) == {
            SKILLS_MARKER,
            CONNECTED_MARKER,
            INSTRUCTIONS_MARKER,
            f"integrations/{INTEGRATION}/agent/.connected",
            f"integrations/{INTEGRATION}/agent/instructions.md",
        }

    async def test_two_users_share_a_single_copy_of_every_system_body(self, bootstrapped: Path):
        await lc.provision_user_workspace(USER)
        await lc.provision_user_workspace(OTHER)

        for user in (USER, OTHER):
            assert link_location(bootstrapped, "INDEX.md", user).is_symlink()
        assert (bootstrapped / SYSTEM_SUBDIR / "INDEX.md").is_file()


class TestTheStalenessGate:
    """``_materialize_if_stale`` skips the whole catalog rewrite when all three
    signatures match. Both directions are load-bearing and fail silently:

    * skips too much → the user connects an integration and the agent is never
      told about it, because ``.connected`` was never written;
    * skips too little → every provisioning rewrites the full 63-file catalog.

    The probe is ``.connected``: it is written by ``materialize_skills`` (behind
    the gate) and, unlike the system files, is *not* re-created by the linker
    that runs before the gate. So deleting it and re-provisioning asks exactly
    one question — did the materializer run?
    """

    async def test_re_provisioning_with_nothing_changed_does_no_work(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        await lc.provision_user_workspace(USER, {INTEGRATION})
        probe = connected_marker(bootstrapped)
        assert probe.is_file()
        probe.unlink()

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not probe.exists(), "the catalog was rewritten even though nothing changed"

    async def test_connecting_an_integration_rewrites_the_catalog(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The headline symptom of a gate that only watches the library hash:
        the user connects Linear, the agent is never told, and nothing changes
        until an unrelated deploy ships a new skill."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        await lc.provision_user_workspace(USER, {INTEGRATION, OTHER_INTEGRATION})

        assert connected_marker(bootstrapped, OTHER_INTEGRATION).is_file()
        assert (
            user_tree(bootstrapped) / CONNECTED_MARKER
        ).read_text() == f"{INTEGRATION},{OTHER_INTEGRATION}"

    async def test_disconnecting_an_integration_clears_its_marker(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """A marker left behind keeps advertising a tool the user revoked; the
        agent then attempts it and fails at the API instead of routing around it."""
        await lc.provision_user_workspace(USER, {INTEGRATION, OTHER_INTEGRATION})
        assert connected_marker(bootstrapped, OTHER_INTEGRATION).is_file()

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not connected_marker(bootstrapped, OTHER_INTEGRATION).exists()
        assert connected_marker(bootstrapped, INTEGRATION).is_file()

    async def test_a_user_with_no_integrations_still_gets_the_full_catalog(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The registration path — provisioning runs before any integration
        exists. The catalog must still be there (it is what the agent reads to
        know what it *could* connect), with no ``.connected`` claiming otherwise."""
        await lc.provision_user_workspace(USER)

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()
        assert (user_tree(bootstrapped) / CONNECTED_MARKER).read_text() == ""
        assert list(user_tree(bootstrapped).rglob(".connected")) == []

    async def test_edited_instructions_rewrite_the_catalog(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Third signature. The user saves new instructions in the UI; if this
        is not gated on, the projection the subagent reads keeps serving the
        old text indefinitely."""
        instructions[INTEGRATION] = "always cc legal"
        await lc.provision_user_workspace(USER, {INTEGRATION})

        instructions[INTEGRATION] = "never cc legal"
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert instructions_file(bootstrapped).read_text() == "never cc legal"

    async def test_a_deploy_that_ships_a_new_skill_library_rewrites_the_catalog(
        self, bootstrapped: Path, instructions: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ):
        """The startup resync path. Existing users' workspaces must pick up a
        newly shipped builtin skill without a connect/disconnect to trigger it."""
        await lc.provision_user_workspace(USER, {INTEGRATION})
        probe = connected_marker(bootstrapped)
        probe.unlink()

        monkeypatch.setattr(lc, "library_hash", lambda: "0" * 32)
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert probe.is_file()
        assert (user_tree(bootstrapped) / SKILLS_MARKER).read_text() == "0" * 32

    async def test_a_workspace_that_never_provisioned_is_not_treated_as_current(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """All three markers absent must read as "stale", not as "all None,
        nothing to do" — otherwise a brand-new user gets an empty catalog."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert connected_marker(bootstrapped).is_file()

    async def test_a_half_written_catalog_is_never_stamped_as_current(
        self, bootstrapped: Path, instructions: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ):
        """Markers are stamped after the writers, so a mount that goes read-only
        mid-rewrite leaves the gate saying "stale" and the next run repairs it.
        Stamping first would wedge a partial catalog as permanently current."""

        def boom(user_root: Path, connected: set[str]) -> int:
            raise OSError("mount went read-only")

        monkeypatch.setattr(lc, "materialize_skills", boom)

        with pytest.raises(OSError, match="read-only"):
            await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not (user_tree(bootstrapped) / SKILLS_MARKER).exists()
        assert not (user_tree(bootstrapped) / CONNECTED_MARKER).exists()


class TestInstructionsProjection:
    """``integrations/<id>/agent/instructions.md`` is a read-only projection of
    Mongo. Mongo is the truth, so a file that outlives its row is the agent
    following an instruction the user believes they deleted."""

    async def test_saved_instructions_appear_beside_the_integrations_skills(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        instructions[INTEGRATION] = "always cc legal@example.com"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert instructions_file(bootstrapped).read_text() == "always cc legal@example.com"

    async def test_cleared_instructions_are_pruned_from_disk(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The one the plan calls out. The user deletes their instructions; if
        the projection survives, the subagent keeps obeying them and there is no
        UI anywhere that would reveal it."""
        instructions[INTEGRATION] = "always cc legal@example.com"
        await lc.provision_user_workspace(USER, {INTEGRATION})
        assert instructions_file(bootstrapped).is_file()

        instructions.clear()
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not instructions_file(bootstrapped).exists()

    async def test_pruning_one_integration_leaves_the_others_instructions_alone(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The prune walks every ``*/agent`` directory, so an over-broad
        condition silently wipes instructions the user never touched."""
        instructions.update({INTEGRATION: "cc legal", OTHER_INTEGRATION: "tag the sprint"})
        await lc.provision_user_workspace(USER, set())

        del instructions[INTEGRATION]
        await lc.provision_user_workspace(USER, set())

        assert not instructions_file(bootstrapped).exists()
        assert instructions_file(bootstrapped, OTHER_INTEGRATION).read_text() == "tag the sprint"

    async def test_the_projection_never_shadows_a_skill_body(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Instructions and skills share ``agent/``. Writing the projection must
        not disturb the symlinks the linker placed one directory down."""
        instructions[INTEGRATION] = "cc legal"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()

    async def test_an_integration_id_that_could_escape_writes_nothing_outside_the_user(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The integration id reaches this from a Mongo document, so it is only
        as trusted as whatever wrote that row. A ``..`` here would write into
        another user's tree on the shared mount."""
        instructions[f"../../{OTHER}"] = "owned"
        instructions[INTEGRATION] = "legitimate"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not (bootstrapped / "users" / OTHER).exists()
        assert instructions_file(bootstrapped).read_text() == "legitimate"


class TestWithoutTheSharedSubtree:
    """``link_system_files_into_workspace`` no-ops when ``_system`` is absent —
    a fresh mount before startup has run, or a worker that came up first. The
    documented contract is that the copy-writers then transparently produce
    per-user copies, so the workspace is degraded (bigger) but never broken.
    """

    async def test_the_catalog_is_still_materialized_as_real_files(
        self, mount: Path, instructions: dict[str, str]
    ):
        """No symlink layer, so the bodies must be written outright. If this
        fallback were lost, a user provisioned before ``ensure_system_subtree``
        would have an empty ``integrations/`` tree until something else
        re-provisioned them."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        body = agent_dir(mount) / "skills" / "gmail-draft-send" / "skill.md"
        assert body.is_file()
        assert not body.is_symlink()
        assert body.read_text().strip()

    async def test_the_connected_marker_is_still_written(
        self, mount: Path, instructions: dict[str, str]
    ):
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert connected_marker(mount).is_file()

    async def test_an_unconnected_integrations_skills_are_materialized_too(
        self, mount: Path, instructions: dict[str, str]
    ):
        """The catalog is what tells the agent an integration *could* be used,
        so it is written for every integration that ships skills, not just the
        connected ones — ``.connected`` is the only thing that varies.

        Asserted here rather than on a linked workspace on purpose: with the
        shared subtree present the linker creates these same directories, so a
        materializer that had quietly narrowed to the connected set would still
        look correct. Without the subtree the materializer is the only writer."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        unconnected = agent_dir(mount, OTHER_INTEGRATION) / "skills"
        bodies = sorted(p.parent.name for p in unconnected.rglob("skill.md"))

        assert bodies == ["linear-create-issue", "linear-gather-context"]
        assert not connected_marker(mount, OTHER_INTEGRATION).exists()

    async def test_the_subtree_arriving_later_replaces_the_copies_with_pointers(
        self, mount: Path, instructions: dict[str, str]
    ):
        """Startup order is not guaranteed. When the subtree does show up, the
        next provisioning must reclaim the per-user copies rather than leave two
        divergent sources for the same body."""
        await lc.provision_user_workspace(USER, {INTEGRATION})
        body = agent_dir(mount) / "skills" / "gmail-draft-send" / "skill.md"
        assert not body.is_symlink()

        await ensure_system_subtree()
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert body.is_symlink()


class TestWithoutAMount:
    """Native dev: ``mise dev`` has no FUSE mount, so provisioning is a
    deliberate no-op rather than a crash on the signup path.

    This is also the guard for every other test in this file — it pins that the
    unmounted path really does write nothing, which is precisely why the rest
    must patch ``_is_mounted`` to assert anything at all.
    """

    async def test_provisioning_writes_nothing_and_does_not_raise(
        self, unmounted_root: Path, instructions: dict[str, str]
    ):
        instructions[INTEGRATION] = "cc legal"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not user_tree(unmounted_root).exists()
        assert children(unmounted_root) == []

    async def test_the_shared_subtree_is_not_written_either(self, unmounted_root: Path):
        assert await ensure_system_subtree() is False

        assert not (unmounted_root / SYSTEM_SUBDIR).exists()


class TestUserIsolation:
    async def test_provisioning_one_user_never_touches_another(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        await lc.provision_user_workspace(OTHER, {OTHER_INTEGRATION})
        before = real_files(user_tree(bootstrapped, OTHER))

        instructions[INTEGRATION] = "cc legal"
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert real_files(user_tree(bootstrapped, OTHER)) == before
        assert not connected_marker(bootstrapped, INTEGRATION, OTHER).exists()

    @pytest.mark.parametrize("bad", ["../_system", "a/b", "", "."])
    async def test_a_user_id_that_could_escape_is_refused_before_anything_is_written(
        self, bootstrapped: Path, instructions: dict[str, str], bad: str
    ):
        """``_place_symlink`` unlinks whatever it finds before linking, so an id
        like ``../_system`` would replace the ONE shared copy every user points
        at — and the hash marker then stops ``ensure_system_subtree`` from ever
        repairing it."""
        marker = bootstrapped / SYSTEM_SUBDIR / ".gaia_system.v"
        before = marker.read_text()

        with pytest.raises(ValueError, match="user_id"):
            await lc.provision_user_workspace(bad, {INTEGRATION})

        assert (bootstrapped / SYSTEM_SUBDIR / "INDEX.md").is_file()
        assert marker.read_text() == before
