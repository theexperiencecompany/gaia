"""Unit tests for app/models/composio_schemas/todoist.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.todoist import TodoistNewTaskCreatedPayload


class TestTodoistNewTaskCreatedPayload:
    def test_valid_full(self):
        m = TodoistNewTaskCreatedPayload(
            event_type="task:added",
            task={"id": "6X2Vw9gHxv8hQ2pP", "content": "Ship it"},
        )
        assert m.event_type == "task:added"
        assert m.task is not None
        assert m.task["content"] == "Ship it"

    def test_task_required_shape_is_object(self):
        with pytest.raises(ValidationError):
            TodoistNewTaskCreatedPayload(task="not-a-dict")


# ---------------------------------------------------------------------------
# notion_tools
# ---------------------------------------------------------------------------
