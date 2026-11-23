"""Contract tests for UserInstructionsRepository (user-scoped, one record per scope)."""

from __future__ import annotations

import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.user_instructions import UserInstructionsRepository
from app.models.user_instructions_models import InstructionsEditor


@pytest.fixture
async def repo(raw_collection: AsyncIOMotorCollection) -> UserInstructionsRepository:
    # The production unique index (db/mongodb/indexes.py) is what turns a racing
    # first write into a conflict instead of a second document.
    await raw_collection.create_index([("user_id", 1), ("scope", 1)], unique=True)
    return UserInstructionsRepository()


def _user() -> str:
    return f"u-{uuid.uuid4().hex}"


class TestUserInstructionsRepository:
    async def test_unconditional_write_creates_then_replaces_and_bumps_revision(self, repo):
        user = _user()
        created = await repo.write(
            user,
            "global",
            content="reply in Spanish",
            updated_by=InstructionsEditor.USER,
            expected_revision=None,
        )
        assert created is not None
        assert (created.content, created.revision) == ("reply in Spanish", 1)
        assert created.updated_by is InstructionsEditor.USER
        assert isinstance(created.id, str) and len(created.id) == 24
        assert created.updated_at is not None

        replaced = await repo.write(
            user,
            "global",
            content="be brief",
            updated_by=InstructionsEditor.AGENT,
            expected_revision=None,
        )
        assert replaced is not None
        assert (replaced.content, replaced.revision) == ("be brief", 2)
        assert replaced.updated_by is InstructionsEditor.AGENT
        assert replaced.id == created.id

    async def test_matching_revision_writes(self, repo):
        user = _user()
        await repo.write(
            user, "slack", content="a", updated_by=InstructionsEditor.USER, expected_revision=0
        )
        saved = await repo.write(
            user, "slack", content="b", updated_by=InstructionsEditor.USER, expected_revision=1
        )
        assert saved is not None
        assert (saved.content, saved.revision) == ("b", 2)

    async def test_stale_revision_is_refused_and_leaves_record_untouched(self, repo):
        user = _user()
        await repo.write(
            user, "slack", content="a", updated_by=InstructionsEditor.USER, expected_revision=0
        )
        await repo.write(
            user, "slack", content="b", updated_by=InstructionsEditor.AGENT, expected_revision=None
        )

        refused = await repo.write(
            user, "slack", content="stale", updated_by=InstructionsEditor.USER, expected_revision=1
        )
        assert refused is None
        current = await repo.get_record(user, "slack")
        assert current is not None
        assert (current.content, current.revision) == ("b", 2)

    async def test_claiming_an_unwritten_scope_that_exists_is_refused(self, repo, raw_collection):
        user = _user()
        await repo.write(
            user, "global", content="a", updated_by=InstructionsEditor.AGENT, expected_revision=None
        )

        refused = await repo.write(
            user, "global", content="mine", updated_by=InstructionsEditor.USER, expected_revision=0
        )
        assert refused is None
        assert await raw_collection.count_documents({"user_id": user, "scope": "global"}) == 1

    async def test_get_record_is_user_and_scope_scoped(self, repo):
        await repo.write(
            "owner",
            "linear",
            content="x",
            updated_by=InstructionsEditor.USER,
            expected_revision=None,
        )
        assert await repo.get_record("owner", "linear") is not None
        assert await repo.get_record("intruder", "linear") is None
        assert await repo.get_record("owner", "global") is None

    async def test_all_nonempty_excludes_empty_and_other_users(self, repo):
        user = _user()
        await repo.write(
            user,
            "global",
            content="keep",
            updated_by=InstructionsEditor.USER,
            expected_revision=None,
        )
        await repo.write(
            user, "github", content="", updated_by=InstructionsEditor.USER, expected_revision=None
        )
        await repo.write(
            "other",
            "slack",
            content="theirs",
            updated_by=InstructionsEditor.USER,
            expected_revision=None,
        )

        records = await repo.all_nonempty(user)
        assert {(r.scope, r.content) for r in records} == {("global", "keep")}
