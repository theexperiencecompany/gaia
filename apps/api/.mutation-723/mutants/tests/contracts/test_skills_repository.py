"""Contract tests for SkillsRepository (global registry, string-UUID _id)."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest

from app.agents.skills.models import Skill, SkillSource, SkillUpdate
from app.db.repositories.skills import SkillsRepository


@pytest.fixture
def repo(raw_collection) -> SkillsRepository:
    return SkillsRepository()


def _skill(**overrides: object) -> Skill:
    data: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "user_id": "u1",
        "name": f"skill-{uuid.uuid4().hex[:8]}",
        "description": "does a thing",
        "target": "executor",
        "vfs_path": "/skills/u1/x",
        "source": SkillSource.INLINE,
        "installed_at": datetime.now(UTC),
    }
    data.update(overrides)
    return Skill.model_validate(data)


class TestSkillsRepository:
    async def test_create_roundtrips_uuid_id_and_leaves_updated_at_unset(self, repo):
        sid = str(uuid.uuid4())
        created = await repo.create(_skill(id=sid, user_id="u", name="alpha"))
        assert created.id == sid  # UUID kept as _id, not an ObjectId

        got = await repo.get_for_user(sid, "u")
        assert got is not None and got.name == "alpha"
        assert got.updated_at is None  # base did not auto-stamp (opt-out)

    async def test_find_by_name_and_target(self, repo):
        await repo.create(_skill(user_id="u", name="dup", target="executor"))
        assert await repo.find_by_name("u", "dup") is not None
        assert await repo.find_by_name("u", "dup", "gmail_agent") is None
        assert await repo.find_by_name("other", "dup") is None

    async def test_for_agent_includes_system_and_excludes_disabled(self, repo):
        await repo.create(_skill(user_id="u", target="gmail_agent", enabled=True, name="mine"))
        await repo.create(_skill(user_id="system", target="gmail_agent", enabled=True, name="sys"))
        await repo.create(_skill(user_id="u", target="gmail_agent", enabled=False, name="off"))
        await repo.create(
            _skill(user_id="other", target="gmail_agent", enabled=True, name="theirs")
        )

        names = {s.name for s in await repo.for_agent("u", "gmail_agent")}
        assert names == {"mine", "sys"}  # own + system, enabled only, not other users

    async def test_set_enabled_reports_change_and_noop(self, repo):
        sid = str(uuid.uuid4())
        await repo.create(_skill(id=sid, user_id="u", enabled=True))
        assert await repo.set_enabled("u", sid, False) is True  # changed
        assert await repo.set_enabled("u", sid, False) is False  # no-op → False
        assert (await repo.get_for_user(sid, "u")).enabled is False

    async def test_patch_updates_fields_and_stamps_iso_string(self, repo, raw_collection):
        sid = str(uuid.uuid4())
        await repo.create(_skill(id=sid, user_id="u", description="old"))
        updated = await repo.patch(
            "u", sid, update=SkillUpdate(description="new", target="gmail_agent")
        )
        assert updated is not None
        assert updated.description == "new" and updated.target == "gmail_agent"
        raw = await raw_collection.find_one({"_id": sid})
        assert isinstance(raw["updated_at"], str)  # ISO string, not a BSON date

    async def test_get_for_user_is_scoped(self, repo):
        """Owner scoping on the read path. Skill ids appear in API routes, so
        without the ``user_id`` term any user who supplies another user's id
        reads their skill body — there is no separate owner check upstream.

        Deleting that term from the query passes every other skills test in the
        repo, which is why this lives here.
        """
        sid = str(uuid.uuid4())
        await repo.create(_skill(id=sid, user_id="u"))

        assert await repo.get_for_user(sid, "other") is None
        assert await repo.get_for_user(sid, "u") is not None

    async def test_patch_is_scoped(self, repo):
        """Owner scoping on the write path — the same exposure, but it lets one
        user rewrite another's skill instructions rather than just read them."""
        sid = str(uuid.uuid4())
        await repo.create(_skill(id=sid, user_id="u", description="mine"))

        assert await repo.patch("other", sid, update=SkillUpdate(description="theirs")) is None

        untouched = await repo.get_for_user(sid, "u")
        assert untouched is not None
        assert untouched.description == "mine"

    async def test_list_for_user_is_scoped(self, repo):
        """Owner scoping on enumeration. Unscoped, one user's skill list is
        every user's skill list."""
        mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
        await repo.create(_skill(id=mine, user_id="u"))
        await repo.create(_skill(id=theirs, user_id="other"))

        assert [s.id for s in await repo.list_for_user("u")] == [mine]
        assert [s.id for s in await repo.list_for_user("other")] == [theirs]

    async def test_delete_for_user_is_scoped(self, repo):
        sid = str(uuid.uuid4())
        await repo.create(_skill(id=sid, user_id="u"))
        assert await repo.delete_for_user(sid, "other") is False
        assert await repo.delete_for_user(sid, "u") is True
        assert await repo.get_for_user(sid, "u") is None
