"""Workspace provisioning composed end to end, against a real filesystem."""

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
    """Build a real tmpdir that also answers the mountpoint check.

    Patches both namespaces: lifecycle imported _is_mounted by value, while
    system_workspace reaches it via the juicefs module global. Patching only
    one leaves the materializer gate live and every assertion silently vacuous.
    """
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    monkeypatch.setattr(lc, "_is_mounted", lambda: True)
    return root


@pytest.fixture
def unmounted_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build the same real tmpdir, honestly reporting itself as not a mountpoint."""
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
    """Write the shared _system subtree exactly as startup writes it.

    Without it, link_system_files_into_workspace short-circuits and the
    whole symlink layer is skipped (see TestWithoutTheSharedSubtree).
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

    Mirrors the skills/ overlay split by hand rather than importing
    _host_base_and_rel: the point is to check the routing, and reusing the
    routing function would only prove it agrees with itself.
    """
    if rel_path == "skills" or rel_path.startswith("skills/"):
        return mount / "skills" / user / rel_path[len("skills/") :]
    return user_tree(mount, user) / rel_path


def real_files(root: Path) -> set[str]:
    """Every non-symlink regular file under root, root-relative."""
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
        """system_files() and _link_location are computed independently and must agree on every path."""
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
        """The link writer and the subtree writer derive paths independently and must never drift."""
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
        """The symlink target is deliberately broken host-side; it resolves only inside the sandbox."""
        link = link_location(bootstrapped, "INDEX.md")

        await lc.provision_user_workspace(USER)

        assert link.readlink().as_posix() == "/workspace/.system/INDEX.md"
        assert not link.resolve().exists()

    async def test_the_executor_skills_land_in_the_skills_overlay_not_the_user_tree(
        self, bootstrapped: Path
    ):
        """/workspace/skills is a separate JuiceFS subtree (/skills/<uid>) mounted over the user tree."""
        await lc.provision_user_workspace(USER)

        assert (bootstrapped / "skills" / USER / "create-artifacts" / "skill.md").is_symlink()
        assert not (user_tree(bootstrapped) / "skills").exists()

    async def test_an_integration_skill_lands_under_its_integration(self, bootstrapped: Path):
        await lc.provision_user_workspace(USER)

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()

    async def test_a_multi_file_skills_bundled_resources_are_all_placed(self, bootstrapped: Path):
        """A skill whose SKILL.md points at reference.md / scripts/ is broken if only the body links."""
        skill_dir = user_tree(bootstrapped) / "integrations/docgen/agent/skills/create-docx"

        await lc.provision_user_workspace(USER)

        assert (skill_dir / "skill.md").is_symlink()
        assert (skill_dir / "reference.md").is_symlink()
        assert (skill_dir / "scripts" / "build.sh").is_symlink()

    async def test_provisioning_stamps_all_three_staleness_markers(self, bootstrapped: Path):
        """These three files are the entire staleness gate; an unstamped one forces a full rewrite."""
        await lc.provision_user_workspace(USER, {INTEGRATION})
        root = user_tree(bootstrapped)

        assert (root / SKILLS_MARKER).read_text() == library_hash()
        assert (root / CONNECTED_MARKER).read_text() == INTEGRATION
        assert (root / INSTRUCTIONS_MARKER).is_file()

    async def test_the_catalog_covers_every_integration_that_ships_skills(self, bootstrapped: Path):
        """The catalog covers every integration that could be used, not just the connected ones."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        expected = {iid for iid, skills in skills_by_subagent().items() if iid != "executor"}
        present = {
            p.name for p in (user_tree(bootstrapped) / "integrations").iterdir() if p.is_dir()
        }

        assert expected <= present, f"missing from the catalog: {expected - present}"


class TestTheFallbackCopiesSurviveTheirOwnPruner:
    """_write_skill_dir writes a skill's resources, then prunes anything not in the manifest.

    This is the one path that *deletes* files with no second copy: it has
    been wrong before, comparing existing.name against manifest keys like
    templates/report.mjs, unlinking every nested resource right after writing
    it. Invisible once _system exists (the pruner skips symlinks), so these
    call the materializer directly on a bare directory.
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
        """Existence is not enough — an empty or truncated file still satisfies is_file()."""
        materialize_skills(tmp_path, set())
        skill = next(s for s in skills_by_subagent()["docgen"] if s.slug == "create-docx")
        expected = dict(skill.resources)["templates/report.mjs"]

        body = (tmp_path / self.SKILL_DIR / "templates/report.mjs").read_text()

        assert body == expected

    def test_a_resource_that_left_the_manifest_is_removed(self, tmp_path: Path):
        """Control: without the pruner a renamed template would outlive the registry change forever."""
        materialize_skills(tmp_path, set())
        stale = tmp_path / self.SKILL_DIR / "templates" / "retired.mjs"
        stale.write_text("a template that was renamed two releases ago")

        materialize_skills(tmp_path, set())

        assert not stale.exists()

    def test_a_second_pass_rewrites_nothing_and_deletes_nothing(self, tmp_path: Path):
        """Provisioning re-runs on every connect/disconnect; a repeat pass must churn nothing."""
        materialize_skills(tmp_path, set())
        before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}

        written = materialize_skills(tmp_path, set())
        after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}

        assert written == 0
        assert after == before


class TestDeDuplication:
    """One copy of every system body on the whole mount, not one per user.

    This is the entire reason _system exists. matches_text returning True
    for a symlink is what keeps the copy-writers from clobbering the pointers —
    lose that and every user silently gets 63 full copies back.
    """

    async def test_no_system_body_is_copied_into_the_users_tree(self, bootstrapped: Path):
        """The regression: a materializer overwriting the symlink with a real per-user copy."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        system_rel = {f.rel_path for f in system_files()}
        copied = [rel for rel in real_files(user_tree(bootstrapped)) if rel in system_rel]

        assert copied == [], f"materialized a per-user copy over the symlink: {copied[:5]}"

    async def test_the_only_real_files_in_the_users_tree_are_the_per_user_ones(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Whitelist rather than blacklist, so a new writer dropping copies anywhere unexpected shows up."""
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
    """_materialize_if_stale skips the whole catalog rewrite when all three signatures match.

    Both directions are load-bearing: skipping too much never tells the agent
    about a new connection; skipping too little rewrites the full 63-file
    catalog every time. The probe is .connected — unlike the system files, it
    is not re-created by the linker, so deleting it asks exactly one question:
    did the materializer run?
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
        """A gate that only watches the library hash would never tell the agent about a new connection."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        await lc.provision_user_workspace(USER, {INTEGRATION, OTHER_INTEGRATION})

        assert connected_marker(bootstrapped, OTHER_INTEGRATION).is_file()
        assert (
            user_tree(bootstrapped) / CONNECTED_MARKER
        ).read_text() == f"{INTEGRATION},{OTHER_INTEGRATION}"

    async def test_disconnecting_an_integration_clears_its_marker(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """A marker left behind keeps advertising a tool the user revoked."""
        await lc.provision_user_workspace(USER, {INTEGRATION, OTHER_INTEGRATION})
        assert connected_marker(bootstrapped, OTHER_INTEGRATION).is_file()

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not connected_marker(bootstrapped, OTHER_INTEGRATION).exists()
        assert connected_marker(bootstrapped, INTEGRATION).is_file()

    async def test_a_user_with_no_integrations_still_gets_the_full_catalog(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Provisioning runs before any integration exists; the catalog must still be there."""
        await lc.provision_user_workspace(USER)

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()
        assert (user_tree(bootstrapped) / CONNECTED_MARKER).read_text() == ""
        assert list(user_tree(bootstrapped).rglob(".connected")) == []

    async def test_edited_instructions_rewrite_the_catalog(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Third staleness signature: edited instructions must rewrite the catalog."""
        instructions[INTEGRATION] = "always cc legal"
        await lc.provision_user_workspace(USER, {INTEGRATION})

        instructions[INTEGRATION] = "never cc legal"
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert instructions_file(bootstrapped).read_text() == "never cc legal"

    async def test_a_deploy_that_ships_a_new_skill_library_rewrites_the_catalog(
        self, bootstrapped: Path, instructions: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ):
        """The startup resync path: a new skill library must rewrite the catalog with no connect event."""
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
        """All three markers absent must read as "stale", not as "nothing to do"."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert connected_marker(bootstrapped).is_file()

    async def test_a_half_written_catalog_is_never_stamped_as_current(
        self, bootstrapped: Path, instructions: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ):
        """Markers stamp after the writers, so a mid-rewrite failure never gets marked current."""

        def boom(user_root: Path, connected: set[str]) -> int:
            raise OSError("mount went read-only")

        monkeypatch.setattr(lc, "materialize_skills", boom)

        with pytest.raises(OSError, match="read-only"):
            await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not (user_tree(bootstrapped) / SKILLS_MARKER).exists()
        assert not (user_tree(bootstrapped) / CONNECTED_MARKER).exists()


class TestInstructionsProjection:
    """integrations/<id>/agent/instructions.md is a read-only projection of Mongo.

    A file that outlives its row is the agent following an instruction the
    user believes they deleted.
    """

    async def test_saved_instructions_appear_beside_the_integrations_skills(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        instructions[INTEGRATION] = "always cc legal@example.com"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert instructions_file(bootstrapped).read_text() == "always cc legal@example.com"

    async def test_cleared_instructions_are_pruned_from_disk(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Deleted instructions must be pruned from disk, or the subagent keeps obeying them invisibly."""
        instructions[INTEGRATION] = "always cc legal@example.com"
        await lc.provision_user_workspace(USER, {INTEGRATION})
        assert instructions_file(bootstrapped).is_file()

        instructions.clear()
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not instructions_file(bootstrapped).exists()

    async def test_pruning_one_integration_leaves_the_others_instructions_alone(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """The prune walks every */agent directory, so an over-broad condition could wipe untouched ones."""
        instructions.update({INTEGRATION: "cc legal", OTHER_INTEGRATION: "tag the sprint"})
        await lc.provision_user_workspace(USER, set())

        del instructions[INTEGRATION]
        await lc.provision_user_workspace(USER, set())

        assert not instructions_file(bootstrapped).exists()
        assert instructions_file(bootstrapped, OTHER_INTEGRATION).read_text() == "tag the sprint"

    async def test_the_projection_never_shadows_a_skill_body(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """Instructions and skills share agent/; writing one must not disturb the other's symlinks."""
        instructions[INTEGRATION] = "cc legal"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert (agent_dir(bootstrapped) / "skills" / "gmail-draft-send" / "skill.md").is_symlink()

    async def test_an_integration_id_that_could_escape_writes_nothing_outside_the_user(
        self, bootstrapped: Path, instructions: dict[str, str]
    ):
        """An integration id with a ".." must not escape into another user's tree on the shared mount."""
        instructions[f"../../{OTHER}"] = "owned"
        instructions[INTEGRATION] = "legitimate"

        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert not (bootstrapped / "users" / OTHER).exists()
        assert instructions_file(bootstrapped).read_text() == "legitimate"


class TestWithoutTheSharedSubtree:
    """link_system_files_into_workspace no-ops when _system is absent.

    The documented contract is that copy-writers then transparently produce
    per-user copies, so the workspace is degraded (bigger) but never broken.
    """

    async def test_the_catalog_is_still_materialized_as_real_files(
        self, mount: Path, instructions: dict[str, str]
    ):
        """No symlink layer, so the skill bodies must be written outright."""
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
        """The catalog materializes every integration that ships skills, not just connected ones."""
        await lc.provision_user_workspace(USER, {INTEGRATION})

        unconnected = agent_dir(mount, OTHER_INTEGRATION) / "skills"
        bodies = sorted(p.parent.name for p in unconnected.rglob("skill.md"))

        assert bodies == ["linear-create-issue", "linear-gather-context"]
        assert not connected_marker(mount, OTHER_INTEGRATION).exists()

    async def test_the_subtree_arriving_later_replaces_the_copies_with_pointers(
        self, mount: Path, instructions: dict[str, str]
    ):
        """When the subtree arrives later, the next provisioning must reclaim per-user copies."""
        await lc.provision_user_workspace(USER, {INTEGRATION})
        body = agent_dir(mount) / "skills" / "gmail-draft-send" / "skill.md"
        assert not body.is_symlink()

        await ensure_system_subtree()
        await lc.provision_user_workspace(USER, {INTEGRATION})

        assert body.is_symlink()


class TestWithoutAMount:
    """Native dev has no FUSE mount, so provisioning is a deliberate no-op, not a crash.

    This is also the guard for every other test in this file — it pins that
    the unmounted path writes nothing, which is why the rest must patch
    _is_mounted to assert anything at all.
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
        """A user_id like "../_system" must be refused before _place_symlink can replace the shared copy."""
        marker = bootstrapped / SYSTEM_SUBDIR / ".gaia_system.v"
        before = marker.read_text()

        with pytest.raises(ValueError, match="user_id"):
            await lc.provision_user_workspace(bad, {INTEGRATION})

        assert (bootstrapped / SYSTEM_SUBDIR / "INDEX.md").is_file()
        assert marker.read_text() == before
