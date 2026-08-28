"""The user-installed skill lifecycle, end to end: install → listed → disable → uninstall.

A user skill is only real if four independent things agree: the body lands on
JuiceFS at the path the prompt will advertise, MongoDB holds the metadata, the
Redis caches in front of both get invalidated on every write, and the listing the
agent is handed reflects all of it. Each of those lives in a different module and
nothing else in the repo checks they line up.

The invalidation is the load-bearing one, and it has already been wrong once —
``registry._SKILLS_INVALIDATION_PATTERNS`` carries a comment saying the glob must
track the ``v2:`` prefix in ``SKILLS_TEXT_CACHE_KEY``, because without it the glob
matches nothing and a disabled skill keeps being advertised to the agent for the
full 12h TTL. Nothing failed when that happened: the write "succeeded", the Redis
DEL matched zero keys, and the agent kept firing a skill the user had turned off.
So these tests run the real ``@CacheInvalidator``/``@Cacheable`` decorators
against a cache that implements Redis' glob semantics, and read the result back
through ``get_available_skills_text`` — the same function that builds the prompt.

What is real: the installer, the registry (decorators included), the parser and
validator, the discovery/formatting layer, and the filesystem — the mount root is
a real ``tmp_path`` (the ``test_juicefs.py`` recipe), so ``write_skill_file`` and
``delete_user_skill`` do real I/O.

What is doubled: MongoDB (an in-memory repository mirroring ``SkillsRepository``'s
query semantics — those semantics themselves are pinned against real Mongo in
``tests/contracts/test_skills_repository.py``, so nothing here re-asserts them)
and Redis (an in-memory store whose ``delete`` globs exactly like ``delete_cache``
→ ``delete_cache_by_pattern``). GitHub is respx-mocked.

Builtin skills are covered by ``test_builtin_skills.py`` and
``test_skills_reach_the_agent.py``; the executor listing contains them here too,
so every assertion is on membership of a specific user skill, never on the whole
string.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.agents.skills.discovery import get_available_skills_text
from app.agents.skills.installer import (
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
    update_skill_inline,
)
from app.agents.skills.models import Skill, SkillUpdate
from app.agents.skills.registry import (
    disable_skill,
    enable_skill,
    get_skill,
    list_skills,
)
from app.agents.skills.utils import GITHUB_API_BASE
from app.config.settings import settings
from app.constants.cache import SKILLS_TEXT_CACHE_KEY, USER_SKILLS_CACHE_KEY
from app.db.repositories.skills import SYSTEM_USER_ID
from app.services.storage import JuiceFSUnavailable
from app.utils.errors import AppError

pytestmark = pytest.mark.e2e

USER = "user-1"
OTHER_USER = "user-2"
EXECUTOR = "executor"
GMAIL = "gmail_agent"

INSTRUCTIONS = "Read the quarterly numbers, then summarise the top three movers."


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _FakeSkillsRepository:
    """In-memory stand-in for ``SkillsRepository``.

    Mirrors the real query semantics that the lifecycle depends on: ``for_agent``
    filters on enabled + target + (owner or system), ``set_enabled`` reports
    ``False`` for a no-op flip (the real ``$ne`` guard), and every read hands back
    a copy so a test cannot mutate stored state through a returned model.
    """

    def __init__(self) -> None:
        self.docs: dict[str, Skill] = {}

    async def create(self, skill: Skill) -> Skill:
        self.docs[skill.id] = skill.model_copy(deep=True)
        return skill

    async def find_by_name(
        self, user_id: str, name: str, target: str | None = None
    ) -> Skill | None:
        for doc in self.docs.values():
            if doc.user_id != user_id or doc.name != name:
                continue
            if target is not None and doc.target != target:
                continue
            return doc.model_copy(deep=True)
        return None

    async def get_for_user(self, skill_id: str, user_id: str) -> Skill | None:
        doc = self.docs.get(skill_id)
        if doc is None or doc.user_id != user_id:
            return None
        return doc.model_copy(deep=True)

    async def delete_for_user(self, skill_id: str, user_id: str) -> bool:
        doc = self.docs.get(skill_id)
        if doc is None or doc.user_id != user_id:
            return False
        del self.docs[skill_id]
        return True

    async def list_for_user(
        self, user_id: str, *, target: str | None = None, enabled_only: bool = False
    ) -> list[Skill]:
        return [
            doc.model_copy(deep=True)
            for doc in self.docs.values()
            if doc.user_id == user_id
            and (target is None or doc.target == target)
            and (not enabled_only or doc.enabled)
        ]

    async def for_agent(self, user_id: str, agent_name: str) -> list[Skill]:
        return [
            doc.model_copy(deep=True)
            for doc in self.docs.values()
            if doc.enabled and doc.target == agent_name and doc.user_id in (user_id, SYSTEM_USER_ID)
        ]

    async def set_enabled(self, user_id: str, skill_id: str, enabled: bool) -> bool:
        doc = self.docs.get(skill_id)
        if doc is None or doc.user_id != user_id or doc.enabled == enabled:
            return False
        doc.enabled = enabled
        doc.updated_at = datetime.now(UTC)
        return True

    async def patch(self, user_id: str, skill_id: str, *, update: SkillUpdate) -> Skill | None:
        doc = self.docs.get(skill_id)
        if doc is None or doc.user_id != user_id:
            return None
        for field, value in update.model_dump(exclude_unset=True).items():
            setattr(doc, field, value)
        doc.updated_at = datetime.now(UTC)
        return doc.model_copy(deep=True)


class _FakeCache:
    """In-memory Redis with the same glob contract as ``app.db.redis``.

    ``delete_cache`` only fans out to ``delete_cache_by_pattern`` when the key
    ends with ``*``; anything else is an exact DEL. Reproducing that exactly is
    the point — an invalidation pattern that has drifted from the cache key (or
    lost its trailing star) must silently match nothing here, just as it does in
    production.
    """

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.deleted_patterns: list[str] = []

    async def get(self, key: str, model: Any = None) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None, model: Any = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.deleted_patterns.append(key)
        if key.endswith("*"):
            for existing in [k for k in self.store if fnmatch(k, key)]:
                del self.store[existing]
            return
        self.store.pop(key, None)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def mount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real directory that reports itself as the JuiceFS mount.

    ``Path.is_mount()`` is False for any tmpdir, so without the lie every storage
    helper raises ``JuiceFSUnavailable`` and the install assertions would pass or
    fail for reasons that have nothing to do with skills.
    """
    root = tmp_path / "jfs"
    root.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(root))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    return root


@pytest.fixture
def mongo() -> Iterator[_FakeSkillsRepository]:
    repo = _FakeSkillsRepository()
    with patch("app.agents.skills.registry.skill_repository", repo):
        yield repo


@pytest.fixture
def cache() -> Iterator[_FakeCache]:
    """Wire the real ``Cacheable``/``CacheInvalidator`` decorators to a fake Redis.

    Patched at ``app.decorators.caching`` because that is where both decorators
    resolve the three functions — the registry and discovery modules never touch
    the cache directly.
    """
    fake = _FakeCache()
    with (
        patch("app.decorators.caching.get_cache", AsyncMock(side_effect=fake.get)),
        patch("app.decorators.caching.set_cache", AsyncMock(side_effect=fake.set)),
        patch("app.decorators.caching.delete_cache", AsyncMock(side_effect=fake.delete)),
    ):
        yield fake


@pytest.fixture
def stack(mount: Path, mongo: _FakeSkillsRepository, cache: _FakeCache):
    """Filesystem + Mongo + Redis together — the whole lifecycle needs all three."""
    return mount, mongo, cache


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _install(
    name: str = "quarterly-report",
    *,
    user_id: str = USER,
    description: str = "Summarise the quarterly numbers.",
    instructions: str = INSTRUCTIONS,
    target: str = EXECUTOR,
) -> Skill:
    return await install_from_inline(
        user_id=user_id,
        name=name,
        description=description,
        instructions=instructions,
        target=target,
    )


def _skill_dir(mount: Path, name: str, user_id: str = USER) -> Path:
    return mount / "skills" / user_id / name


def _skill_md(mount: Path, name: str, user_id: str = USER) -> Path:
    return _skill_dir(mount, name, user_id) / "SKILL.md"


async def _listing(agent_name: str = EXECUTOR, user_id: str = USER) -> str:
    return await get_available_skills_text(user_id, agent_name)


_SKILL_MD_REMOTE = """\
---
name: repo-skill
description: A skill fetched from a GitHub repository
target: executor
---

Clone the repo, then run the checks.
"""


def _contents_entry(name: str, entry_type: str, path: str) -> dict[str, str]:
    return {
        "name": name,
        "path": path,
        "type": entry_type,
        "download_url": f"https://raw.githubusercontent.com/org/repo/main/{path}",
    }


# --------------------------------------------------------------------------
# Install
# --------------------------------------------------------------------------


class TestInstall:
    async def test_the_body_lands_on_disk_without_its_frontmatter(self, stack):
        """JuiceFS stores body-only; the frontmatter is metadata and lives in
        Mongo. Writing the raw SKILL.md instead would feed the agent a YAML
        header it has to parse out of a file it was told is instructions."""
        mount, _, _ = stack

        await _install()

        written = _skill_md(mount, "quarterly-report").read_text()
        assert written == INSTRUCTIONS
        assert "---" not in written

    async def test_the_record_points_at_the_file_that_was_written(self, stack):
        """``vfs_path`` is what the prompt advertises and what ``read`` resolves.
        A record pointing somewhere the writer did not write is a skill the agent
        is told about and can never open."""
        mount, _, _ = stack

        skill = await _install()

        assert skill.vfs_path == f"/skills/{USER}/quarterly-report"
        assert (mount / skill.vfs_path.lstrip("/") / "SKILL.md").is_file()

    async def test_an_installed_skill_is_listed_to_its_target_agent(self, stack):
        """The whole point of installing. Name, description and an openable
        location all have to reach the prompt or the skill is inert."""
        await _install()

        listing = await _listing()

        assert "quarterly-report" in listing
        assert "Summarise the quarterly numbers." in listing
        assert f"/skills/{USER}/quarterly-report/SKILL.md" in listing

    async def test_a_skill_is_not_listed_to_an_agent_it_does_not_target(self, stack):
        """Targeting is the only scoping a skill has. Leaking one into every
        agent's prompt is both wrong advice and wasted context on every turn."""
        await _install(target=GMAIL)

        assert "quarterly-report" in await _listing(GMAIL)
        assert "quarterly-report" not in await _listing(EXECUTOR)

    async def test_a_skill_is_not_listed_to_another_user(self, stack):
        """``for_agent`` unions the owner with ``system``. Widening that is a
        cross-tenant leak of whatever the other user wrote in their skill."""
        await _install()

        assert "quarterly-report" not in await _listing(EXECUTOR, user_id=OTHER_USER)

    async def test_installing_the_same_name_on_the_same_target_twice_is_rejected(self, stack):
        """(user, name, target) is the uniqueness invariant. A second install
        that lands would give the agent two entries with one location, and the
        second body would overwrite the first on disk."""
        _, mongo, _ = stack
        await _install()

        with pytest.raises(AppError, match="already installed"):
            await _install()

        assert len(await list_skills(USER)) == 1

    async def test_the_same_name_on_a_different_target_is_allowed(self, stack):
        """The invariant is per-target, not per-name — the same skill scoped to
        the executor and to gmail is a legitimate setup."""
        await _install()
        await _install(target=GMAIL)

        assert len(await list_skills(USER)) == 2

    async def test_an_invalid_name_is_rejected_before_anything_is_written(self, stack):
        """Validation runs before the first side effect. If it did not, a bad
        name would leave an orphan directory on JuiceFS with no Mongo record
        pointing at it — invisible, and never cleaned up."""
        mount, mongo, _ = stack

        with pytest.raises(ValueError):
            await _install(name="Quarterly Report")

        assert not (mount / "skills").exists()
        assert mongo.docs == {}

    async def test_an_empty_description_is_rejected(self, stack):
        """The description is the only thing the model selects on; a blank one
        makes the skill listed but unselectable. Rejected twice over — by
        ``SkillMetadata`` and again by the generated file's round-trip
        validation — so this only goes red when both stop guarding it."""
        mount, mongo, _ = stack

        with pytest.raises(ValueError):
            await _install(description="   ")

        assert not (mount / "skills").exists()
        assert mongo.docs == {}


# --------------------------------------------------------------------------
# Cache invalidation — the regression this file exists for
# --------------------------------------------------------------------------


class TestInvalidationReachesTheAgent:
    async def test_disabling_a_skill_removes_it_from_the_agents_listing(self, stack):
        """THE bug. The listing is cached for 12h, so an invalidation glob that
        matches nothing leaves the agent firing a skill the user just turned off,
        with no error anywhere. Warming the cache first is what makes this able
        to fail — without the first read there is nothing stale to serve."""
        skill = await _install()

        assert "quarterly-report" in await _listing()

        await disable_skill(USER, skill.id)

        assert "quarterly-report" not in await _listing()

    async def test_a_write_deletes_the_exact_keys_the_listing_is_cached_under(self, stack):
        """Pins both invalidation patterns against the real key constants. The
        behavioural test above catches a broken text glob; this one names which
        of the two patterns drifted, and catches a per-agent glob that stopped
        matching even while the text one still works."""
        _, _, cache = stack
        skill = await _install()
        text_key = SKILLS_TEXT_CACHE_KEY.format(user_id=USER, agent_name=EXECUTOR)
        agent_key = USER_SKILLS_CACHE_KEY.format(user_id=USER, agent_name=EXECUTOR)

        await _listing()
        assert text_key in cache.store
        assert agent_key in cache.store

        await disable_skill(USER, skill.id)

        assert text_key not in cache.store
        assert agent_key not in cache.store

    async def test_invalidation_covers_every_agent_the_user_has_skills_for(self, stack):
        """The globs are per-user, not per-agent, precisely because one write can
        change what several agents are told. Narrowing them to the target agent
        would leave every other agent's listing stale."""
        await _install(name="alpha")
        gmail_skill = await _install(name="beta", target=GMAIL)

        await _listing(EXECUTOR)
        executor_key = SKILLS_TEXT_CACHE_KEY.format(user_id=USER, agent_name=EXECUTOR)
        _, _, cache = stack
        assert executor_key in cache.store

        await disable_skill(USER, gmail_skill.id)

        assert executor_key not in cache.store

    async def test_one_users_write_does_not_flush_another_users_listing(self, stack):
        """The other half of the glob: ``skills:text:v2:*`` would also make the
        disable test pass, while stampeding every user's cache on every install."""
        _, _, cache = stack
        skill = await _install()
        await _listing(EXECUTOR, user_id=OTHER_USER)
        other_key = SKILLS_TEXT_CACHE_KEY.format(user_id=OTHER_USER, agent_name=EXECUTOR)
        assert other_key in cache.store

        await disable_skill(USER, skill.id)

        assert other_key in cache.store

    async def test_re_enabling_puts_the_skill_back_in_the_listing(self, stack):
        """Enable invalidates through the same decorator. If only disable did,
        turning a skill back on would appear to do nothing for 12h."""
        skill = await _install()
        await disable_skill(USER, skill.id)
        assert "quarterly-report" not in await _listing()

        await enable_skill(USER, skill.id)

        assert "quarterly-report" in await _listing()

    async def test_a_disabled_skill_keeps_its_files_and_its_record(self, stack):
        """Disable is not uninstall. Deleting the body here would make the toggle
        one-way — re-enabling would restore a record pointing at nothing."""
        mount, _, _ = stack
        skill = await _install()

        await disable_skill(USER, skill.id)

        assert _skill_md(mount, "quarterly-report").read_text() == INSTRUCTIONS
        stored = await get_skill(USER, skill.id)
        assert stored is not None
        assert stored.enabled is False


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------


class TestUpdate:
    async def test_editing_the_instructions_rewrites_the_file_on_disk(self, stack):
        """The body is the skill. An edit that only lands in Mongo leaves the
        agent reading the old instructions from JuiceFS forever."""
        mount, _, _ = stack
        skill = await _install()

        await update_skill_inline(USER, skill.id, instructions="Do the new thing instead.")

        assert _skill_md(mount, "quarterly-report").read_text() == "Do the new thing instead."

    async def test_a_description_only_edit_leaves_the_file_untouched(self, stack):
        """Description and target are metadata; rewriting the body for them is an
        unnecessary write on every rename. Proven with a sentinel written
        straight to disk — if the branch rewrote unconditionally the stored body
        would clobber it."""
        mount, _, _ = stack
        skill = await _install()
        _skill_md(mount, "quarterly-report").write_text("SENTINEL")

        updated = await update_skill_inline(USER, skill.id, description="A new description.")

        assert _skill_md(mount, "quarterly-report").read_text() == "SENTINEL"
        assert updated is not None
        assert updated.description == "A new description."

    async def test_the_edited_description_is_what_the_agent_is_shown(self, stack):
        """Update invalidates through its own decorator. A stale listing here
        means the model keeps selecting the skill on the old description."""
        skill = await _install()
        await _listing()

        await update_skill_inline(USER, skill.id, description="Only for quarterly numbers.")

        listing = await _listing()
        assert "Only for quarterly numbers." in listing
        assert "Summarise the quarterly numbers." not in listing

    async def test_retargeting_moves_the_skill_between_agent_listings(self, stack):
        """Both listings have to change on one write — that is exactly what the
        per-user (not per-agent) invalidation glob buys."""
        skill = await _install()
        await _listing(EXECUTOR)
        await _listing(GMAIL)

        await update_skill_inline(USER, skill.id, target=GMAIL)

        assert "quarterly-report" not in await _listing(EXECUTOR)
        assert "quarterly-report" in await _listing(GMAIL)

    async def test_retargeting_onto_an_occupied_name_is_rejected(self, stack):
        """Retargeting is the one edit that can break the (user, name, target)
        invariant, since ``update`` does not go through the install duplicate
        check. Without the guard the collision lands and the agent gets two
        entries with the same name."""
        keeper = await _install()
        await _install(target=GMAIL)

        with pytest.raises(ValueError, match="already targets"):
            await update_skill_inline(USER, keeper.id, target=GMAIL)

        stored = await get_skill(USER, keeper.id)
        assert stored is not None
        assert stored.target == EXECUTOR

    async def test_re_saving_a_skill_with_its_current_target_is_not_a_clash(self, stack):
        """Every edit through the UI re-sends the current target, so a re-save
        must not collide with the skill itself.

        Two guards each prevent this independently — the target-changed gate
        skips the lookup, and the exclude-self term discards the only row it
        could find — so this test survives either one being removed on its own,
        and only goes red when both are. Given the gate, the exclude-self term
        is in fact unreachable: any row the lookup returns has the *new* target,
        which the gate has already established is not the skill's own.
        """
        skill = await _install()

        updated = await update_skill_inline(USER, skill.id, target=EXECUTOR)

        assert updated is not None
        assert updated.target == EXECUTOR

    async def test_an_invalid_edit_leaves_disk_and_registry_untouched(self, stack):
        """Validation runs on the regenerated SKILL.md before any write. A
        partial edit — file rewritten, Mongo not, or the reverse — is the state
        nothing downstream can recover from."""
        mount, _, _ = stack
        skill = await _install()

        with pytest.raises(ValueError):
            await update_skill_inline(USER, skill.id, description="")

        assert _skill_md(mount, "quarterly-report").read_text() == INSTRUCTIONS
        stored = await get_skill(USER, skill.id)
        assert stored is not None
        assert stored.description == "Summarise the quarterly numbers."

    async def test_editing_another_users_skill_does_nothing(self, stack):
        """Ownership is scoped at the lookup, and it is the *caller's* id that
        goes into it — not the id stored on the skill.

        The owner-succeeds half is what makes this falsifiable. Whether a given
        id is refused is decided inside the repository, which is doubled here
        (and pinned against real Mongo in ``tests/contracts/test_skills_repository``),
        so the negative alone is satisfied by a lookup that returns None for
        everybody — including one whose arguments have simply been swapped.
        """
        mount, _, _ = stack
        skill = await _install()

        assert await update_skill_inline(OTHER_USER, skill.id, instructions="Owned.") is None
        assert _skill_md(mount, "quarterly-report").read_text() == INSTRUCTIONS

        mine = await update_skill_inline(USER, skill.id, instructions="Mine.")

        assert mine is not None
        assert _skill_md(mount, "quarterly-report").read_text() == "Mine."

    async def test_editing_a_skill_that_does_not_exist_returns_none(self, stack):
        assert await update_skill_inline(USER, "no-such-id", description="x") is None


# --------------------------------------------------------------------------
# Uninstall
# --------------------------------------------------------------------------


class TestUninstall:
    async def test_uninstall_removes_the_directory_and_the_record(self, stack):
        mount, mongo, _ = stack
        skill = await _install()

        assert (await uninstall_skill_full(USER, skill.id)) is not None

        assert not _skill_dir(mount, "quarterly-report").exists()
        assert await get_skill(USER, skill.id) is None

    async def test_an_uninstalled_skill_is_gone_from_the_agents_listing(self, stack):
        """Same 12h staleness window as disable, on the path a user is far more
        likely to take when a skill misbehaves."""
        skill = await _install()
        assert "quarterly-report" in await _listing()

        await uninstall_skill_full(USER, skill.id)

        assert "quarterly-report" not in await _listing()

    async def test_uninstalling_one_skill_leaves_the_others_on_disk(self, stack):
        """``delete_user_skill`` takes a skill name and rmtree's it. Widening
        that by one path segment deletes the user's entire skill library."""
        mount, _, _ = stack
        doomed = await _install(name="alpha")
        keeper = await _install(name="beta")

        await uninstall_skill_full(USER, doomed.id)

        assert not _skill_dir(mount, "alpha").exists()
        assert _skill_md(mount, "beta").is_file()
        assert await get_skill(USER, keeper.id) is not None

    async def test_another_users_skill_cannot_be_uninstalled_by_id(self, stack):
        """The id is the only thing a caller supplies. Dropping the user scope
        from the lookup turns a guessed id into a cross-tenant delete of both the
        record and the files."""
        mount, _, _ = stack
        skill = await _install()

        assert (await uninstall_skill_full(OTHER_USER, skill.id)) is None

        assert _skill_md(mount, "quarterly-report").is_file()
        assert await get_skill(USER, skill.id) is not None

    async def test_uninstalling_an_unknown_id_reports_false_and_deletes_nothing(self, stack):
        mount, _, _ = stack
        await _install()

        assert (await uninstall_skill_full(USER, "no-such-id")) is None

        assert _skill_md(mount, "quarterly-report").is_file()

    async def test_an_unavailable_mount_still_removes_the_registry_record(self, stack):
        """Storage cleanup is best-effort on purpose: a native API run has no
        JuiceFS mount, and letting ``JuiceFSUnavailable`` escape would leave the
        skill permanently un-uninstallable — still listed, still firing, with the
        delete button reporting an error every time."""
        _, mongo, _ = stack
        skill = await _install()

        with patch(
            "app.agents.skills.installer.delete_user_skill",
            AsyncMock(side_effect=JuiceFSUnavailable("mount not available")),
        ):
            result = await uninstall_skill_full(USER, skill.id)

        assert result is not None
        assert await get_skill(USER, skill.id) is None

    async def test_a_reinstall_after_uninstall_succeeds(self, stack):
        """The duplicate guard keys on the registry, so an uninstall that left
        the record behind would make the name unusable forever."""
        mount, _, _ = stack
        skill = await _install()
        await uninstall_skill_full(USER, skill.id)

        reinstalled = await _install(instructions="Second time around.")

        assert reinstalled.id != skill.id
        assert _skill_md(mount, "quarterly-report").read_text() == "Second time around."


# --------------------------------------------------------------------------
# GitHub install, through the same lifecycle
# --------------------------------------------------------------------------


class TestGithubInstallLifecycle:
    """``test_installer_github.py`` covers the fetch/parse/recursion with the
    filesystem and Mongo mocked out. These two run the same path against the real
    filesystem, the real registry and the real caches — the part that decides
    whether a GitHub skill actually reaches the agent and actually goes away."""

    @staticmethod
    def _mock_repo() -> None:
        respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/repo-skill").mock(
            return_value=httpx.Response(
                200,
                json=[
                    _contents_entry("SKILL.md", "file", "skills/repo-skill/SKILL.md"),
                    _contents_entry("resources", "dir", "skills/repo-skill/resources"),
                ],
            )
        )
        respx.get(f"{GITHUB_API_BASE}/repos/org/repo/contents/skills/repo-skill/resources").mock(
            return_value=httpx.Response(
                200,
                json=[
                    _contents_entry(
                        "reference.md", "file", "skills/repo-skill/resources/reference.md"
                    )
                ],
            )
        )
        respx.get(
            "https://raw.githubusercontent.com/org/repo/main/skills/repo-skill/SKILL.md"
        ).mock(return_value=httpx.Response(200, text=_SKILL_MD_REMOTE))
        respx.get(
            "https://raw.githubusercontent.com/org/repo/main/skills/repo-skill/resources/reference.md"
        ).mock(return_value=httpx.Response(200, text="# Reference\nExtra detail."))

    async def test_a_github_skill_lands_on_disk_and_reaches_the_agent(self, stack):
        mount, _, _ = stack
        with respx.mock:
            self._mock_repo()
            await install_from_github(user_id=USER, repo_url="org/repo/skills/repo-skill")

        assert _skill_md(mount, "repo-skill").read_text() == "Clone the repo, then run the checks."
        assert (_skill_dir(mount, "repo-skill") / "resources" / "reference.md").is_file()

        listing = await _listing()
        assert "repo-skill" in listing
        assert "resources/reference.md" in listing

    async def test_uninstalling_a_github_skill_removes_its_subdirectories_too(self, stack):
        """A multi-file skill is a tree, not a file. Deleting only SKILL.md
        leaves the resources orphaned on JuiceFS with nothing referencing them."""
        mount, _, _ = stack
        with respx.mock:
            self._mock_repo()
            skill = await install_from_github(user_id=USER, repo_url="org/repo/skills/repo-skill")

        await uninstall_skill_full(USER, skill.id)

        assert not _skill_dir(mount, "repo-skill").exists()
        assert "repo-skill" not in await _listing()
