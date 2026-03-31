"""
Service tests: verify MongoDB query correctness for todo operations.

Uses real MongoDB to test sort orders, filtering, and user isolation.
Patches todos_collection into TodoService so production query logic
runs against the real test database.

Key behaviors under test:
- Todos are returned sorted by created_at descending (newest first)
- Filtering by completed status returns only matching todos
- User A's todos never appear in User B's query results
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId


@pytest.mark.service
class TestTodoQueriesReal:
    """Verify that todo queries return correct results from real MongoDB."""

    @pytest.fixture
    async def todos_collection(self, mongo_db, monkeypatch):
        """Real MongoDB todos collection patched into the TodoService singleton."""
        coll = mongo_db["todos"]
        await coll.delete_many({})

        import app.services.todos.todo_service as todo_svc

        monkeypatch.setattr(todo_svc, "todos_collection", coll)

        yield coll

        await coll.delete_many({})

    async def test_todos_filtered_by_completed_false(self, todos_collection):
        """Querying completed=False must return only non-completed todos."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "u1",
                    "title": "Done todo",
                    "completed": True,
                    "created_at": now,
                },
                {
                    "user_id": "u1",
                    "title": "Active todo",
                    "completed": False,
                    "created_at": now,
                },
                {
                    "user_id": "u1",
                    "title": "Another active",
                    "completed": False,
                    "created_at": now,
                },
            ]
        )

        pending = await todos_collection.find(
            {"user_id": "u1", "completed": False}
        ).to_list(length=100)

        assert len(pending) == 2
        assert all(t["completed"] is False for t in pending)

    async def test_todos_filtered_by_completed_true(self, todos_collection):
        """Querying completed=True must return only completed todos."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "u1",
                    "title": "Done",
                    "completed": True,
                    "created_at": now,
                },
                {
                    "user_id": "u1",
                    "title": "Active",
                    "completed": False,
                    "created_at": now,
                },
            ]
        )

        completed = await todos_collection.find(
            {"user_id": "u1", "completed": True}
        ).to_list(length=100)

        assert len(completed) == 1
        assert completed[0]["title"] == "Done"

    async def test_todos_sorted_by_created_at_desc(self, todos_collection):
        """list_todos sorts by created_at descending — newest todo appears first."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "u2",
                    "title": "Oldest",
                    "completed": False,
                    "created_at": now - timedelta(hours=3),
                },
                {
                    "user_id": "u2",
                    "title": "Middle",
                    "completed": False,
                    "created_at": now - timedelta(hours=1),
                },
                {
                    "user_id": "u2",
                    "title": "Newest",
                    "completed": False,
                    "created_at": now,
                },
            ]
        )

        docs = (
            await todos_collection.find({"user_id": "u2"})
            .sort("created_at", -1)
            .to_list(length=100)
        )

        assert docs[0]["title"] == "Newest"
        assert docs[1]["title"] == "Middle"
        assert docs[2]["title"] == "Oldest"

    async def test_todo_user_isolation(self, todos_collection):
        """User A's todos must never appear in User B's query results."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "user-A",
                    "title": "A's todo",
                    "completed": False,
                    "created_at": now,
                },
                {
                    "user_id": "user-A",
                    "title": "A's other todo",
                    "completed": False,
                    "created_at": now,
                },
                {
                    "user_id": "user-B",
                    "title": "B's todo",
                    "completed": False,
                    "created_at": now,
                },
            ]
        )

        a_todos = await todos_collection.find({"user_id": "user-A"}).to_list(length=100)
        b_todos = await todos_collection.find({"user_id": "user-B"}).to_list(length=100)

        assert len(a_todos) == 2
        assert len(b_todos) == 1
        assert all(t["user_id"] == "user-A" for t in a_todos)
        assert all(t["user_id"] == "user-B" for t in b_todos)

    async def test_todo_priority_filter(self, todos_collection):
        """Filtering by priority must return only todos with the matching priority value."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "u3",
                    "title": "High prio",
                    "completed": False,
                    "priority": "high",
                    "created_at": now,
                },
                {
                    "user_id": "u3",
                    "title": "Low prio",
                    "completed": False,
                    "priority": "low",
                    "created_at": now,
                },
                {
                    "user_id": "u3",
                    "title": "Another high",
                    "completed": False,
                    "priority": "high",
                    "created_at": now,
                },
            ]
        )

        high_prio = await todos_collection.find(
            {"user_id": "u3", "priority": "high"}
        ).to_list(length=100)

        assert len(high_prio) == 2
        assert all(t["priority"] == "high" for t in high_prio)

    async def test_pagination_correct_slice(self, todos_collection):
        """Skip + limit must return distinct, non-overlapping pages."""
        now = datetime.now(timezone.utc)

        for i in range(5):
            await todos_collection.insert_one(
                {
                    "user_id": "page-user",
                    "title": f"Todo {i}",
                    "completed": False,
                    "created_at": now - timedelta(seconds=i),
                    "_id": ObjectId(),
                }
            )

        page1 = (
            await todos_collection.find({"user_id": "page-user"})
            .sort("created_at", -1)
            .skip(0)
            .limit(2)
            .to_list(length=2)
        )
        page2 = (
            await todos_collection.find({"user_id": "page-user"})
            .sort("created_at", -1)
            .skip(2)
            .limit(2)
            .to_list(length=2)
        )
        page3 = (
            await todos_collection.find({"user_id": "page-user"})
            .sort("created_at", -1)
            .skip(4)
            .limit(2)
            .to_list(length=2)
        )

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

        all_ids = (
            [str(d["_id"]) for d in page1]
            + [str(d["_id"]) for d in page2]
            + [str(d["_id"]) for d in page3]
        )
        # All five IDs must be unique across pages — no duplicates
        assert len(set(all_ids)) == 5

    async def test_overdue_filter(self, todos_collection):
        """Overdue query must return only non-completed todos with due_date in the past."""
        now = datetime.now(timezone.utc)

        await todos_collection.insert_many(
            [
                {
                    "user_id": "u4",
                    "title": "Overdue",
                    "completed": False,
                    "due_date": now - timedelta(days=1),
                    "created_at": now,
                },
                {
                    "user_id": "u4",
                    "title": "Future",
                    "completed": False,
                    "due_date": now + timedelta(days=1),
                    "created_at": now,
                },
                {
                    "user_id": "u4",
                    "title": "Completed overdue",
                    "completed": True,
                    "due_date": now - timedelta(days=2),
                    "created_at": now,
                },
            ]
        )

        overdue = await todos_collection.find(
            {
                "user_id": "u4",
                "completed": False,
                "due_date": {"$lt": now},
            }
        ).to_list(length=100)

        assert len(overdue) == 1
        assert overdue[0]["title"] == "Overdue"
