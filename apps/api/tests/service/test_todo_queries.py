"""
Service tests: verify MongoDB query correctness for todo operations.

Drives the real ``todo_repository`` against real MongoDB — the `mongo_db` fixture
points the repository layer at the test database, so production filter, sort and
pagination logic runs unmodified. (Previously this file hand-wrote its own Mongo
filters against a raw collection, which asserted MongoDB's behaviour rather than
GAIA's.)

Key behaviors under test:
- Todos are returned sorted by created_at descending (newest first)
- Filtering by completed status / priority / overdue returns only matching todos
- User A's todos never appear in User B's query results
- page + per_page return distinct, non-overlapping slices
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.todos import todo_repository
from app.models.todo_models import Priority, SearchMode, TodoDocument, TodoSearchParams


def _params(**overrides: object) -> TodoSearchParams:
    return TodoSearchParams.model_validate({"mode": SearchMode.TEXT, **overrides})


@pytest.mark.service
class TestTodoQueriesReal:
    """Verify that todo queries return correct results from real MongoDB."""

    @pytest.fixture
    async def todos_collection(self, mongo_db, real_redis):
        """The real ``todos`` collection the repository reads, emptied per test.

        ``real_redis`` gives this test its own Redis DB — ``list_page`` is a
        ``@cached_query``, so a shared cache would let one test's page answer
        another's.
        """
        coll = mongo_db["todos"]
        await coll.delete_many({})

        yield coll

        await coll.delete_many({})

    @staticmethod
    async def _seed(user_id: str, title: str, **fields: object) -> TodoDocument:
        return await todo_repository.create(
            TodoDocument.model_validate({"user_id": user_id, "title": title, **fields})
        )

    async def test_todos_filtered_by_completed_false(self, todos_collection):
        """Querying completed=False must return only non-completed todos."""
        await self._seed("u1", "Done todo", completed=True)
        await self._seed("u1", "Active todo", completed=False)
        await self._seed("u1", "Another active", completed=False)

        page = await todo_repository.list_page(
            user_id="u1", params=_params(completed=False), inbox_project_id=None
        )

        assert page.total == 2
        assert all(t.completed is False for t in page.items)

    async def test_todos_filtered_by_completed_true(self, todos_collection):
        """Querying completed=True must return only completed todos."""
        await self._seed("u1", "Done", completed=True)
        await self._seed("u1", "Active", completed=False)

        page = await todo_repository.list_page(
            user_id="u1", params=_params(completed=True), inbox_project_id=None
        )

        assert page.total == 1
        assert page.items[0].title == "Done"

    async def test_todos_sorted_by_created_at_desc(self, todos_collection):
        """list_todos sorts by created_at descending — newest todo appears first."""
        now = datetime.now(UTC)
        await self._seed("u2", "Oldest", created_at=now - timedelta(hours=3))
        await self._seed("u2", "Middle", created_at=now - timedelta(hours=1))
        await self._seed("u2", "Newest", created_at=now)

        page = await todo_repository.list_page(
            user_id="u2", params=_params(), inbox_project_id=None
        )

        assert [t.title for t in page.items] == ["Newest", "Middle", "Oldest"]

    async def test_todo_user_isolation(self, todos_collection):
        """User A's todos must never appear in User B's query results."""
        await self._seed("user-A", "A's todo")
        await self._seed("user-A", "A's other todo")
        await self._seed("user-B", "B's todo")

        page_a = await todo_repository.list_page(
            user_id="user-A", params=_params(), inbox_project_id=None
        )
        page_b = await todo_repository.list_page(
            user_id="user-B", params=_params(), inbox_project_id=None
        )

        assert page_a.total == 2
        assert page_b.total == 1
        assert all(t.user_id == "user-A" for t in page_a.items)
        assert all(t.user_id == "user-B" for t in page_b.items)

    async def test_todo_priority_filter(self, todos_collection):
        """Filtering by priority must return only todos with the matching priority value."""
        await self._seed("u3", "High prio", priority=Priority.HIGH)
        await self._seed("u3", "Low prio", priority=Priority.LOW)
        await self._seed("u3", "Another high", priority=Priority.HIGH)

        page = await todo_repository.list_page(
            user_id="u3", params=_params(priority=Priority.HIGH), inbox_project_id=None
        )

        assert page.total == 2
        assert all(t.priority is Priority.HIGH for t in page.items)

    async def test_pagination_correct_slice(self, todos_collection):
        """page + per_page must return distinct, non-overlapping pages."""
        now = datetime.now(UTC)
        for i in range(5):
            await self._seed("page-user", f"Todo {i}", created_at=now - timedelta(seconds=i))

        pages = [
            await todo_repository.list_page(
                user_id="page-user", params=_params(page=n, per_page=2), inbox_project_id=None
            )
            for n in (1, 2, 3)
        ]

        assert [len(p.items) for p in pages] == [2, 2, 1]
        # The unpaginated total is reported on every page.
        assert {p.total for p in pages} == {5}
        all_ids = [t.id for page in pages for t in page.items]
        assert len(set(all_ids)) == 5

    async def test_overdue_filter(self, todos_collection):
        """Overdue query must return only non-completed todos with due_date in the past."""
        now = datetime.now(UTC)
        await self._seed("u4", "Overdue", completed=False, due_date=now - timedelta(days=1))
        await self._seed("u4", "Future", completed=False, due_date=now + timedelta(days=1))
        await self._seed(
            "u4", "Completed overdue", completed=True, due_date=now - timedelta(days=2)
        )

        page = await todo_repository.list_page(
            user_id="u4", params=_params(overdue=True), inbox_project_id=None
        )

        assert page.total == 1
        assert page.items[0].title == "Overdue"
