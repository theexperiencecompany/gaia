"""Unit tests for the executor's own telemetry turn.

Every executor run — live, queued, or HIL-resumed — spends the turn's
largest LLM budget inside ``run_executor_background``. These pin that the
run opens one turn as tier=executor and closes it with the run's real
outcome, instead of folding silently into the parent or orphaning.
"""

import asyncio
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.executor_runner import _ExecutorResult, run_executor_background
from app.agents.core.background.session import ExecutorRun, RunKind

MODULE = "app.agents.core.background.executor_runner"

USER = {"user_id": "user-1", "email": "u@gaia.local"}


def _run(**overrides: Any) -> ExecutorRun:
    values: dict[str, Any] = {
        "stream_id": "stream-exec-1",
        "conversation_id": "conv-1",
        "user": USER,
        "kind": RunKind.QUEUED,
        "task_id": "task-1",
        "user_message_id": None,
        "queued": True,
    }
    values.update(overrides)
    return ExecutorRun(**values)  # type: ignore[arg-type]


@contextmanager
def _quiet_runner(execute_result: Any = None, execute_error: Any = None, cancelled: bool = False):
    """Stub the runner's side channels; the telemetry pairing is what's under test."""
    execute = AsyncMock(
        return_value=execute_result or _ExecutorResult("did the thing", "final", None),
        **({"side_effect": execute_error} if execute_error is not None else {}),
    )
    span = MagicMock()
    span.__enter__.return_value = lambda: 0.001
    with (
        patch(f"{MODULE}._execute_executor", new=execute),
        patch(f"{MODULE}._finalize_executor_run", new=AsyncMock()),
        patch(f"{MODULE}.StreamManager") as mock_manager,
        patch(f"{MODULE}.capture_event", new=MagicMock()),
        patch(f"{MODULE}.span", return_value=span),
    ):
        mock_manager.is_cancelled = AsyncMock(return_value=cancelled)
        yield


@pytest.mark.unit
class TestExecutorTurn:
    async def test_success_opens_and_closes_executor_turn(self) -> None:
        run = _run(workflow_execution_id="wfexec-1")
        config: dict[str, object] = {"conversation_source": "web"}
        with (
            _quiet_runner(),
            patch(f"{MODULE}.begin_turn_all") as mock_begin,
            patch(f"{MODULE}.end_turn_all") as mock_end,
        ):
            await run_executor_background(run, "do the thing", config, None)  # type: ignore[arg-type]

        spec = mock_begin.call_args.args[0]
        assert spec.user_id == "user-1"
        assert spec.conversation_id == "conv-1"
        assert spec.user_input == "do the thing"
        assert spec.source == "web"
        assert spec.mode == "background"
        assert spec.tier == "executor"
        assert spec.properties == {
            "task_id": "task-1",
            "queued": True,
            "workflow_execution_id": "wfexec-1",
        }
        assert mock_end.call_args.args[0] is mock_begin.return_value
        end_kwargs = mock_end.call_args.kwargs
        assert end_kwargs["output"] == "did the thing"
        assert end_kwargs.get("error") is None

    async def test_error_result_fails_the_turn(self) -> None:
        with (
            _quiet_runner(execute_result=_ExecutorResult("it broke", "error", None)),
            patch(f"{MODULE}.begin_turn_all") as mock_begin,
            patch(f"{MODULE}.end_turn_all") as mock_end,
        ):
            await run_executor_background(_run(), "do the thing", {}, None)

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == "it broke"
        error = mock_end.call_args.kwargs["error"]
        assert isinstance(error, RuntimeError) and str(error) == "it broke"

    async def test_runner_bug_records_failed_and_propagates(self) -> None:
        with (
            _quiet_runner(execute_error=RuntimeError("runner bug")),
            patch(f"{MODULE}.begin_turn_all") as mock_begin,
            patch(f"{MODULE}.end_turn_all") as mock_end,
            pytest.raises(RuntimeError, match="runner bug"),
        ):
            await run_executor_background(_run(), "do the thing", {}, None)

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == "runner bug"
        assert mock_end.call_args.kwargs["error"] is not None

    async def test_cancel_closes_as_cancelled_and_propagates(self) -> None:
        with (
            _quiet_runner(cancelled=True),
            patch(f"{MODULE}.begin_turn_all") as mock_begin,
            patch(f"{MODULE}.end_turn_all") as mock_end,
        ):
            await run_executor_background(_run(), "do the thing", {}, None)

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["cancelled"] is True
        assert "error" not in mock_end.call_args.kwargs

    async def test_hard_cancel_propagates_cancelled(self) -> None:
        with (
            _quiet_runner(execute_error=asyncio.CancelledError("shutdown")),
            patch(f"{MODULE}.begin_turn_all") as mock_begin,
            patch(f"{MODULE}.end_turn_all") as mock_end,
            pytest.raises(asyncio.CancelledError),
        ):
            await run_executor_background(_run(), "do the thing", {}, None)

        assert mock_end.call_args.args[0] is mock_begin.return_value
        assert mock_end.call_args.kwargs["output"] == ""
        assert mock_end.call_args.kwargs["cancelled"] is True
