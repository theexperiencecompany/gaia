"""``WorkflowsRepository``'s shared list predicate — what "a user's workflows" means.

``list_for_user`` and ``count_for_user`` answer the same question in two shapes,
so they share ``_list_query``: a page and its reported total must never come from
different filters. Both exclusions are opt-in per caller and the defaults differ
between them, which is exactly the kind of thing a service test that mocks the
repository cannot see — so the filter handed to the driver is asserted here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.workflows import WorkflowsRepository

pytestmark = pytest.mark.unit

USER_ID = "user-1"
TODO_EXCLUSION = [{"is_todo_workflow": {"$exists": False}}, {"is_todo_workflow": False}]


class _EmptyCursor:
    """A Motor cursor that yields nothing — these tests read the filter, not rows."""

    def sort(self, _sort: object) -> _EmptyCursor:
        return self

    def skip(self, _skip: int) -> _EmptyCursor:
        return self

    def limit(self, _limit: int) -> _EmptyCursor:
        return self

    def __aiter__(self) -> _EmptyCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        raise StopAsyncIteration


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.count_documents = AsyncMock(return_value=0)
    mock.find = MagicMock(return_value=_EmptyCursor())
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.fixture
def repo() -> WorkflowsRepository:
    return WorkflowsRepository()


def _counted(collection: MagicMock) -> dict[str, Any]:
    collection.count_documents.assert_awaited_once()
    return collection.count_documents.await_args.args[0]


def _listed(collection: MagicMock) -> dict[str, Any]:
    collection.find.assert_called_once()
    return collection.find.call_args.args[0]


class TestCountForUser:
    async def test_by_default_counts_everything_but_the_todo_workflows(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        """System workflows are part of the default total: the workflows page
        shows the auto-provisioned ones, so its total has to include them."""
        await repo.count_for_user(USER_ID)

        assert _counted(collection) == {"user_id": USER_ID, "$or": TODO_EXCLUSION}

    async def test_drops_the_auto_provisioned_ones_when_asked(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        """The activation checklist asks what the user authored themselves, so a
        workflow GAIA provisioned for them must not tick the step."""
        await repo.count_for_user(USER_ID, exclude_system_workflows=True)

        assert _counted(collection) == {
            "user_id": USER_ID,
            "$or": TODO_EXCLUSION,
            "is_system_workflow": {"$ne": True},
        }

    async def test_a_workflow_predating_the_flag_still_counts_as_the_user_s(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        """``$ne`` rather than ``False``: rows written before ``is_system_workflow``
        existed carry no such field, and ``{"is_system_workflow": False}`` would
        exclude every one of them — a user with only old workflows would be told
        they have never created one."""
        await repo.count_for_user(USER_ID, exclude_system_workflows=True)

        assert _counted(collection)["is_system_workflow"] == {"$ne": True}

    async def test_both_exclusions_can_be_lifted_together(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        await repo.count_for_user(
            USER_ID, exclude_todo_workflows=False, exclude_system_workflows=False
        )

        assert _counted(collection) == {"user_id": USER_ID}

    async def test_reports_the_driver_s_count(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        collection.count_documents.return_value = 3

        assert await repo.count_for_user(USER_ID) == 3


class TestListForUser:
    async def test_lists_the_auto_provisioned_workflows_alongside_the_user_s_own(
        self, repo: WorkflowsRepository, collection: MagicMock
    ) -> None:
        """The system-workflow exclusion is a count-side opt-in only; adding it to
        the list default would silently empty the workflows page for users whose
        workflows were all provisioned for them."""
        await repo.list_for_user(USER_ID)

        assert _listed(collection) == {"user_id": USER_ID, "$or": TODO_EXCLUSION}
