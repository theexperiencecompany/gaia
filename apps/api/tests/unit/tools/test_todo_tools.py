"""Unit tests for app.agents.tools.todo_tools helpers.

The todo_progress snapshot is what the frontend renders a live todo list from,
so the shape it puts on the stream is the behaviour worth pinning.
"""

from unittest.mock import MagicMock, patch

from app.agents.tools.todo_tools import Todo, _emit_todo_progress

MODULE = "app.agents.tools.todo_tools"


def _todo(todo_id: str, content: str, status: str) -> Todo:
    return Todo(id=todo_id, content=content, status=status)


class TestEmitTodoProgress:
    def test_snapshot_carries_every_todo_and_the_source(self) -> None:
        writer = MagicMock()
        with patch(f"{MODULE}.get_stream_writer", return_value=writer):
            _emit_todo_progress(
                [_todo("1", "write the tests", "in_progress"), _todo("2", "ship", "pending")],
                "mcp:linear",
            )

        assert writer.call_args.args[0] == {
            "todo_progress": {
                "todos": [
                    {"id": "1", "content": "write the tests", "status": "in_progress"},
                    {"id": "2", "content": "ship", "status": "pending"},
                ],
                "source": "mcp:linear",
            }
        }

    def test_source_label_is_added_only_when_given(self) -> None:
        writer = MagicMock()
        with patch(f"{MODULE}.get_stream_writer", return_value=writer):
            _emit_todo_progress([_todo("1", "a", "pending")], "mcp:linear", "Linear")

        assert writer.call_args.args[0]["todo_progress"]["integration_name"] == "Linear"

    def test_a_missing_stream_writer_is_survivable(self) -> None:
        with patch(f"{MODULE}.get_stream_writer", side_effect=RuntimeError("no writer")):
            _emit_todo_progress([_todo("1", "a", "pending")], "mcp:linear")
