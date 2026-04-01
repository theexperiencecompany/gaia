"""
Service tests: verify MongoDB query correctness for conversation operations.

Patches the production collection to point at real test MongoDB,
then calls the real service functions to verify query behavior.

Key behaviors under test:
- get_conversations sorts non-starred conversations by createdAt descending
- Pagination (page/limit) returns the correct slice of non-starred results
- User isolation: user A's conversations never appear in user B's query results
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.service
class TestConversationQueriesReal:
    """Verify that conversation queries return correct results from real MongoDB."""

    async def test_conversations_sorted_by_created_at_desc(
        self, conversations_collection, make_conversation
    ):
        """Non-starred conversations must be returned newest-first (createdAt descending).

        get_conversations sorts by createdAt descending for non-starred results.
        We seed three conversations with distinct createdAt values and verify
        the direct collection query returns them in the expected order.
        """
        import app.services.conversation_service as conv_svc  # noqa: F401 — ensures patch is active

        now = datetime.now(timezone.utc)

        c1 = await make_conversation(
            "sort-user",
            createdAt=now - timedelta(hours=2),
        )
        c2 = await make_conversation(
            "sort-user",
            createdAt=now - timedelta(hours=1),
        )
        c3 = await make_conversation(
            "sort-user",
            createdAt=now,
        )

        cursor = conversations_collection.find({"user_id": "sort-user"}).sort(
            "createdAt", -1
        )
        docs = await cursor.to_list(length=10)

        assert docs[0]["conversation_id"] == c3
        assert docs[1]["conversation_id"] == c2
        assert docs[2]["conversation_id"] == c1

    async def test_get_conversations_service_returns_newest_first(
        self, conversations_collection, make_conversation
    ):
        """get_conversations must return non-starred conversations newest-first."""
        import app.services.conversation_service as conv_svc

        now = datetime.now(timezone.utc)

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

    async def test_user_isolation_in_queries(
        self, conversations_collection, make_conversation
    ):
        """User A's conversations must not appear in User B's results."""
        await make_conversation("isolation-user-A")
        await make_conversation("isolation-user-A")
        await make_conversation("isolation-user-B")

        docs_a = await conversations_collection.find(
            {"user_id": "isolation-user-A"}
        ).to_list(length=100)
        docs_b = await conversations_collection.find(
            {"user_id": "isolation-user-B"}
        ).to_list(length=100)

        assert len(docs_a) == 2
        assert len(docs_b) == 1
        assert all(d["user_id"] == "isolation-user-A" for d in docs_a)
        assert all(d["user_id"] == "isolation-user-B" for d in docs_b)

    async def test_user_isolation_via_service(
        self, conversations_collection, make_conversation
    ):
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

    async def test_pagination_returns_correct_slice(
        self, conversations_collection, make_conversation
    ):
        """Skip + limit must return the correct page of results."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            await make_conversation("page-user", createdAt=now - timedelta(hours=i))

        page1 = (
            await conversations_collection.find({"user_id": "page-user"})
            .sort("createdAt", -1)
            .skip(0)
            .limit(2)
            .to_list(length=2)
        )
        page2 = (
            await conversations_collection.find({"user_id": "page-user"})
            .sort("createdAt", -1)
            .skip(2)
            .limit(2)
            .to_list(length=2)
        )
        page3 = (
            await conversations_collection.find({"user_id": "page-user"})
            .sort("createdAt", -1)
            .skip(4)
            .limit(2)
            .to_list(length=2)
        )

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        all_ids = (
            [d["conversation_id"] for d in page1]
            + [d["conversation_id"] for d in page2]
            + [d["conversation_id"] for d in page3]
        )
        assert len(set(all_ids)) == 5

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

        now = datetime.now(timezone.utc)

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
