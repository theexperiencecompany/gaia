"""Contract tests for IntegrationInstructionsRepository (user-scoped, per-integration)."""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.integration_instructions import IntegrationInstructionsRepository
from app.models.integration_instructions_models import InstructionsEditor


@pytest.fixture
def repo(raw_collection) -> IntegrationInstructionsRepository:
    return IntegrationInstructionsRepository()


class TestIntegrationInstructionsRepository:
    async def test_upsert_creates_then_replaces(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        created = await repo.upsert(
            user, "slack", content="focus on #eng", updated_by=InstructionsEditor.USER
        )
        assert created.content == "focus on #eng"
        assert created.updated_by is InstructionsEditor.USER
        assert isinstance(created.id, str) and len(created.id) == 24  # ObjectId preserved
        assert created.updated_at is not None  # base stamped it

        replaced = await repo.upsert(
            user, "slack", content="focus on #design", updated_by=InstructionsEditor.AGENT
        )
        assert replaced.content == "focus on #design"
        assert replaced.updated_by is InstructionsEditor.AGENT
        assert replaced.id == created.id  # same record, not a new one

    async def test_get_record_is_user_scoped(self, repo):
        await repo.upsert("owner", "linear", content="x", updated_by=InstructionsEditor.USER)
        assert await repo.get_record("owner", "linear") is not None
        assert await repo.get_record("intruder", "linear") is None
        assert await repo.get_record("owner", "github") is None

    async def test_all_nonempty_excludes_empty_and_other_users(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.upsert(user, "slack", content="keep", updated_by=InstructionsEditor.USER)
        await repo.upsert(user, "github", content="", updated_by=InstructionsEditor.USER)
        await repo.upsert("other", "slack", content="theirs", updated_by=InstructionsEditor.USER)

        records = await repo.all_nonempty(user)
        assert {(r.integration_id, r.content) for r in records} == {("slack", "keep")}
