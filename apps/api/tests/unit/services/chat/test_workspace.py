"""Unit tests for the fire-and-forget last-active touch (workspace.py).

``schedule_last_active_touch`` spawns ``_touch()`` via ``spawn_background_task``.
Its inner try/except must swallow a plain failure from
``touch_session_last_active`` (log and move on) so an idle-prune bookkeeping
error never surfaces to the chat turn that scheduled it. The ``JuiceFSUnavailable``
branch (dev-mode no-op) is a separate, already-expected path and isn't the
target here.

``spawn_background_task`` is patched at the module's own binding so the test can
capture and await the real ``_touch()`` coroutine directly, rather than letting
it run detached on the event loop where a raised exception would only surface as
an "unhandled exception in task" warning instead of a test failure.
"""

from unittest.mock import AsyncMock, patch

from app.services.chat import workspace
from app.services.chat.workspace import schedule_last_active_touch
from app.services.storage import JuiceFSUnavailable


class TestScheduleLastActiveTouch:
    async def test_plain_exception_is_caught_and_logged(self) -> None:
        """A non-JuiceFS failure must be swallowed, not raised into the caller."""
        with (
            patch.object(workspace, "spawn_background_task") as mock_spawn,
            patch.object(
                workspace,
                "touch_session_last_active",
                new=AsyncMock(side_effect=RuntimeError("mongo timeout")),
            ),
            patch.object(workspace.log, "warning") as mock_warning,
        ):
            schedule_last_active_touch("user-1", "conv-1")
            mock_spawn.assert_called_once()
            coro = mock_spawn.call_args.args[0]
            await coro  # must not raise

        mock_warning.assert_called_once()

    async def test_juicefs_unavailable_is_a_silent_no_op(self) -> None:
        """The dev-mode no-mount case returns quietly without logging a warning."""
        with (
            patch.object(workspace, "spawn_background_task") as mock_spawn,
            patch.object(
                workspace,
                "touch_session_last_active",
                new=AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
            ),
            patch.object(workspace.log, "warning") as mock_warning,
        ):
            schedule_last_active_touch("user-1", "conv-1")
            mock_spawn.assert_called_once()
            coro = mock_spawn.call_args.args[0]
            await coro  # must not raise

        mock_warning.assert_not_called()
