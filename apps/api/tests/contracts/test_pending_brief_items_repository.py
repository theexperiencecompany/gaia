"""Contract tests for PendingBriefItemsRepository: held results, read oldest first, cleared by id."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.pending_brief_items import PendingBriefItemsRepository
from app.models.brief_models import PendingBriefItemDocument

_START = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)


def _item(user_id: str, minutes: int, text: str) -> PendingBriefItemDocument:
    return PendingBriefItemDocument(
        user_id=user_id,
        workflow_id="wf-1",
        workflow_title="Morning digest",
        conversation_id="conv-1",
        text=text,
        created_at=_START + timedelta(minutes=minutes),
    )


@pytest.fixture
def repo(raw_collection) -> PendingBriefItemsRepository:
    return PendingBriefItemsRepository()


class TestPendingBriefItems:
    async def test_the_brief_reads_a_users_items_oldest_first(self, repo):
        await repo.create(_item("owner", 5, "later"))
        await repo.create(_item("owner", 0, "earlier"))
        await repo.create(_item("someone-else", 1, "not yours"))

        items = await repo.list_for_user("owner", sort=[("created_at", 1)])

        assert [i.text for i in items] == ["earlier", "later"]

    async def test_consume_clears_only_the_carried_items_of_that_user(self, repo):
        carried = await repo.create(_item("owner", 0, "carried"))
        waiting = await repo.create(_item("owner", 1, "waiting"))
        theirs = await repo.create(_item("someone-else", 2, "theirs"))

        assert await repo.consume("owner", [carried.id, theirs.id]) == 1

        assert [i.id for i in await repo.list_for_user("owner")] == [waiting.id]
        assert [i.id for i in await repo.list_for_user("someone-else")] == [theirs.id]

    async def test_consuming_nothing_clears_nothing(self, repo):
        await repo.create(_item("owner", 0, "kept"))

        assert await repo.consume("owner", []) == 0
        assert len(await repo.list_for_user("owner")) == 1
