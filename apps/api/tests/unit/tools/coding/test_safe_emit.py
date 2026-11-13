"""safe_emit: a coding tool's stream event reaches the writer, routed to its session."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.agents.tools.coding._context import safe_emit

WRITER = "app.agents.tools.coding._context.current_stream_writer"


def test_the_event_is_written_with_its_session_stamped() -> None:
    writer = MagicMock()
    with patch(WRITER, return_value=writer):
        safe_emit({"bash_data": {"command": "ls"}, "other": {"x": 1}}, session_id="s-1")

    writer.assert_called_once_with(
        {"bash_data": {"command": "ls", "session_id": "s-1"}, "other": {"x": 1}}
    )


def test_a_failed_write_does_not_fail_the_tool() -> None:
    with patch(WRITER, return_value=MagicMock(side_effect=RuntimeError("stream closed"))):
        safe_emit({"file_data": {"path": "/a"}})
