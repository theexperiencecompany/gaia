"""Contract tests for OpenUIArtifactsRepository's conversation-scoped reads and deletes."""

from __future__ import annotations

import pytest

from app.db.repositories.openui_artifacts import OpenUIArtifactsRepository
from app.models.openui_artifact_models import ArtifactKind, OpenUIArtifact


@pytest.fixture
def repo(raw_collection) -> OpenUIArtifactsRepository:
    return OpenUIArtifactsRepository()


async def _make(repo: OpenUIArtifactsRepository, user_id: str, conversation_id: str | None) -> str:
    artifact = await repo.create(
        OpenUIArtifact(
            user_id=user_id,
            conversation_id=conversation_id,
            kind=ArtifactKind.REPORT,
            title="Q3",
            program="root = Report()",
            brief_hash="b",
            model="m",
        )
    )
    return artifact.id


class TestOneConversationsArtifacts:
    async def test_are_found_and_deleted_for_their_owner_only(self, repo, raw_collection):
        mine = [await _make(repo, "owner", "conv-1"), await _make(repo, "owner", "conv-1")]
        kept = [
            await _make(repo, "owner", "conv-2"),
            await _make(repo, "owner", None),
            await _make(repo, "other", "conv-1"),
        ]

        assert sorted(await repo.ids_in_conversation("owner", "conv-1")) == sorted(mine)
        assert await repo.delete_for_conversation("owner", "conv-1") == 2

        assert await repo.ids_in_conversation("owner", "conv-1") == []
        left = [str(doc["_id"]) async for doc in raw_collection.find({})]
        assert sorted(left) == sorted(kept)
