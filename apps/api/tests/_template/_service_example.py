"""Canonical service test — copy into tests/unit/services/, rename, adapt.

The repository singleton is patched at the module where the service imports it, and the
test asserts the service's orchestration — never the repo's behavior (that lives in
tests/contracts/). Arranged (fixture + mocks) → acted (one await) → asserted (result +
the mock's call contract). Every test covers a failure path.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.tasks import Assignee
from app.models.task_models import TaskDocument
from app.services.tasks.errors import TaskNotFoundError
from app.services.tasks.task_service import require_task

FAKE_USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_task_repo() -> Iterator[MagicMock]:
    with patch("app.services.tasks.task_service.task_repository") as repo:
        repo.get = AsyncMock(return_value=None)
        yield repo


def _task_doc(task_id: str) -> TaskDocument:
    return TaskDocument(id=task_id, user_id=FAKE_USER_ID, title="Buy milk", assignee=Assignee.USER)


@pytest.mark.unit
class TestRequireTask:
    async def test_returns_the_task_when_found(self, mock_task_repo: MagicMock) -> None:
        # Arrange
        mock_task_repo.get = AsyncMock(return_value=_task_doc("task_1"))
        # Act
        result = await require_task(FAKE_USER_ID, "task_1")
        # Assert
        assert result.id == "task_1"
        mock_task_repo.get.assert_awaited_once_with("task_1", user_id=FAKE_USER_ID)

    async def test_raises_when_not_found(self, mock_task_repo: MagicMock) -> None:
        with pytest.raises(TaskNotFoundError, match="not found"):
            await require_task(FAKE_USER_ID, "missing")
        mock_task_repo.get.assert_awaited_once_with("missing", user_id=FAKE_USER_ID)
