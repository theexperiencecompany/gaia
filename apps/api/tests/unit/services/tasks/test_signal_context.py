"""Signal-matching context: the entry format the agent sees and the key-details cap."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.tasks import Assignee, TaskFlag
from app.models.task_models import TaskDocument
from app.services.tasks.signal_context import (
    _SIGNAL_CONTEXT_TASK_LIMIT,
    get_signal_matching_context,
)

pytestmark = pytest.mark.unit

_MOD = "app.services.tasks.signal_context"
USER_ID = "507f1f77bcf86cd799439011"
TASK_ID = "task_0123456789ab"
HEADER = "OPEN GAIA TASKS (check if incoming signal relates to any):"


def _task(**overrides: object) -> TaskDocument:
    data: dict[str, object] = {
        "id": TASK_ID,
        "user_id": USER_ID,
        "title": "Prepare Q3 report",
        "assignee": Assignee.GAIA,
        "status_flags": [TaskFlag.NEEDS_REPLY],
    }
    data.update(overrides)
    return TaskDocument.model_validate(data)


@pytest.fixture
def repo():
    with patch(f"{_MOD}.task_repository") as repo:
        repo.list_open_gaia = AsyncMock(return_value=[])
        yield SimpleNamespace(list_open_gaia=repo.list_open_gaia)


class TestGetSignalMatchingContext:
    async def test_empty_string_without_tasks(self, repo) -> None:
        assert await get_signal_matching_context(USER_ID) == ""

    async def test_renders_entries_with_indented_key_details(self, repo) -> None:
        repo.list_open_gaia.return_value = [
            _task(notes="# Prepare Q3 report\n\n## Key Details\nthread: abc123\nemail: x@y.com\n")
        ]

        lines = (await get_signal_matching_context(USER_ID)).split("\n")

        assert lines == [
            HEADER,
            f'- "Prepare Q3 report" [needs_reply] (ID: {TASK_ID})',
            "    thread: abc123",
            "    email: x@y.com",
        ]
        repo.list_open_gaia.assert_awaited_once_with(USER_ID, limit=_SIGNAL_CONTEXT_TASK_LIMIT)

    async def test_notes_without_key_details_add_nothing(self, repo) -> None:
        repo.list_open_gaia.return_value = [_task(notes="# Prepare Q3 report\n\nA body.\n")]

        assert await get_signal_matching_context(USER_ID) == (
            f'{HEADER}\n- "Prepare Q3 report" [needs_reply] (ID: {TASK_ID})'
        )

    async def test_a_task_with_no_flags_renders_without_brackets(self, repo) -> None:
        repo.list_open_gaia.return_value = [_task(status_flags=[])]

        assert (await get_signal_matching_context(USER_ID)).split("\n")[1] == (
            f'- "Prepare Q3 report" (ID: {TASK_ID})'
        )

    async def test_caps_key_details_at_five_lines(self, repo) -> None:
        repo.list_open_gaia.return_value = [
            _task(notes="## Key Details\n" + "\n".join(f"line {i}" for i in range(8)))
        ]

        context = await get_signal_matching_context(USER_ID)

        assert len([line for line in context.split("\n") if line.startswith("    ")]) == 5
