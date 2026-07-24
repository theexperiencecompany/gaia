"""
Service tests: verify get_conversations' composition against real MongoDB.

The `mongo_db` fixture points the repository layer at the test database, so the
real service function runs unmodified over real documents.

Scoped deliberately to what the service adds *above* the repository — the
repository's own ordering, filtering and pagination are asserted in
tests/contracts/test_conversations_repository.py:

- starred results are concatenated ahead of active ones, regardless of age
- total_pages is ceil(active_count / limit), and total spans both lists
- neither list leaks another user's conversations through the service
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest


@pytest.mark.service
class TestConversationQueriesReal:
    """Verify that conversation queries return correct results from real MongoDB."""

    async def test_get_conversations_service_returns_newest_first(
        self, conversations_collection, make_conversation
    ):
        """get_conversations must return non-starred conversations newest-first."""
        import app.services.conversation_service as conv_svc

        now = datetime.now(UTC)

        oldest = await make_conversation(
            "svc-sort-user",
            createdAt=now - timedelta(hours=3),
        )
        middle = await make_conversation(
            "svc-sort-user",
            createdAt=now - timedelta(hours=1),
        )
        newest = await make_conversation(
            "svc-sort-user",
            createdAt=now,
        )

        result = await conv_svc.get_conversations(
            user={"user_id": "svc-sort-user"}, page=1, limit=10
        )

        conversation_ids = [c["conversation_id"] for c in result["conversations"]]
        assert conversation_ids.index(newest) < conversation_ids.index(middle)
        assert conversation_ids.index(middle) < conversation_ids.index(oldest)

    async def test_user_isolation_via_service(self, conversations_collection, make_conversation):
        """get_conversations must never return another user's conversations."""
        import app.services.conversation_service as conv_svc

        await make_conversation("svc-user-A")
        await make_conversation("svc-user-A")
        await make_conversation("svc-user-B")

        result_a = await conv_svc.get_conversations(
            user={"user_id": "svc-user-A"}, page=1, limit=10
        )
        result_b = await conv_svc.get_conversations(
            user={"user_id": "svc-user-B"}, page=1, limit=10
        )

        ids_a = {c["conversation_id"] for c in result_a["conversations"]}
        ids_b = {c["conversation_id"] for c in result_b["conversations"]}

        # No overlap between the two users' results
        assert ids_a.isdisjoint(ids_b)
        assert result_a["total"] == 2
        assert result_b["total"] == 1

    async def test_service_pagination_total_pages(
        self, conversations_collection, make_conversation
    ):
        """get_conversations must report the correct total_pages for non-starred results."""
        import app.services.conversation_service as conv_svc

        for _ in range(5):
            await make_conversation("paginate-svc-user")

        result = await conv_svc.get_conversations(
            user={"user_id": "paginate-svc-user"}, page=1, limit=2
        )

        # 5 non-starred conversations at limit=2 → ceil(5/2) = 3 pages
        assert result["total_pages"] == 3
        assert result["total"] == 5
        assert len(result["conversations"]) == 2

    async def test_starred_conversations_always_appear_first(
        self, conversations_collection, make_conversation
    ):
        """Starred conversations must precede non-starred ones in get_conversations output."""
        import app.services.conversation_service as conv_svc

        now = datetime.now(UTC)

        non_starred = await make_conversation(
            "starred-test-user",
            createdAt=now,  # newest — but not starred
        )
        starred = await make_conversation(
            "starred-test-user",
            createdAt=now - timedelta(hours=5),  # older — but starred
            starred=True,
        )

        result = await conv_svc.get_conversations(
            user={"user_id": "starred-test-user"}, page=1, limit=10
        )

        conversation_ids = [c["conversation_id"] for c in result["conversations"]]
        assert conversation_ids[0] == starred, (
            "Starred conversation must appear before non-starred even if older"
        )
        assert non_starred in conversation_ids
