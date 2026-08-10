"""Unit tests for app/agents/core/background/subagent_runner.py.

The background subagent coroutine spawned by handoff(background=True): runs the
subagent graph, durably stores the final result (or parks it on a HIL approval),
and wakes a resting executor so the work is always collected.

These tests pin the exact contract with every external seam (Redis, stream
publish, session registry, wide-event boundary, formatting helpers) mocked:
exact call args, exact stream payloads, exact error strings, and the
finally-block bookkeeping that must survive every exit path. Note that
``decrement_pending_subagents`` / ``release_bg_integration`` are SYNC session
calls — asserted with ``assert_called_once_with``, not ``assert_awaited...``.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.agents.core.background.subagent_runner import (
    _append_error_result,
    _park,
    _wake_if_executor_rested,
    run_subagent_background,
)
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    SubagentOutcome,
)
from app.constants.log_tags import LogTag

MODULE = "app.agents.core.background.subagent_runner"

START_EVENT = {"subagent_id": "gh-1", "subagent_name": "GitHub Agent"}
END_EVENT = {"subagent_id": "gh-1", "duration_ms": 3250}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**overrides: object) -> SubagentExecutionContext:
    """A fully-shaped SubagentExecutionContext for background execution."""
    defaults: dict[str, object] = {
        "subagent_graph": MagicMock(),
        "agent_name": "test_agent",
        "config": {"configurable": {"thread_id": "t1"}},
        "configurable": {"thread_id": "t1", "conversation_id": "conv-1"},
        "integration_id": "test",
        "initial_state": {"messages": []},
        "user_id": "u1",
        "stream_id": "stream-1",
    }
    defaults.update(overrides)
    return SubagentExecutionContext(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def wide_task_mock() -> MagicMock:
    """Patch the wide-event boundary with an enterable/exitable context manager.

    ``__aexit__`` is pinned to return False so exceptions inside the boundary
    (e.g. the BaseException propagation test) are never suppressed.
    """
    cm = AsyncMock()
    cm.__aexit__ = AsyncMock(return_value=False)
    with patch(f"{MODULE}.wide_task", return_value=cm) as wt:
        yield wt


# ---------------------------------------------------------------------------
# run_subagent_background
# ---------------------------------------------------------------------------


class TestRunSubagentBackground:
    async def test_completes_appends_result_and_cleans_up(
        self, wide_task_mock: MagicMock
    ) -> None:
        """Happy path without a subagent row: no stream events, result appended,
        pending counter decremented, resting executor woken, integration slot
        untouched."""
        ctx = _make_ctx()
        writer = MagicMock()
        outcome = SubagentOutcome(text="done")
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=writer) as mock_writer,
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=outcome,
            ) as mock_execute,
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents") as mock_decrement,
            patch(f"{MODULE}.release_bg_integration") as mock_release,
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ) as mock_wake,
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(ctx, "stream-1")

        mock_writer.assert_called_once_with("stream-1")
        writer.assert_not_called()
        mock_execute.assert_awaited_once_with(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=None,
            subagent_id=None,
        )
        mock_append.assert_awaited_once_with("conv-1", "test_agent", "done")
        mock_decrement.assert_called_once_with("stream-1")
        mock_release.assert_not_called()
        mock_wake.assert_awaited_once_with("conv-1", ctx.configurable)
        log.info.assert_called_once_with(
            f"{LogTag.AGENT} Background subagent completed",
            agent_name="test_agent",
            stream_id="stream-1",
        )

    async def test_streams_exact_start_and_end_events(
        self, wide_task_mock: MagicMock
    ) -> None:
        """With a subagent_id, exact start/end payloads stream on the writer and
        the integration slot is released; duration is wall-clock in ms.

        ``time.monotonic`` is stubbed on the module's own ``time`` reference so
        the asyncio event loop's clock calls cannot consume the sequence.
        """
        ctx = _make_ctx()
        writer = MagicMock()
        log = MagicMock()
        fake_time = MagicMock(monotonic=MagicMock(side_effect=[100.0, 103.25]))

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=writer),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ) as mock_execute,
            patch(f"{MODULE}.time", fake_time),
            patch(
                f"{MODULE}.format_subagent_start_event", return_value=START_EVENT
            ) as mock_start,
            patch(
                f"{MODULE}.format_subagent_end_event", return_value=END_EVENT
            ) as mock_end,
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration") as mock_release,
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(
                ctx,
                "stream-1",
                subagent_id="gh-1",
                display_name="GitHub Agent",
                icon_url="https://icon.png",
                tool_category="github",
                integration_id="github",
            )

        mock_start.assert_called_once_with(
            subagent_name="GitHub Agent",
            agent_type="handoff",
            subagent_id="gh-1",
            icon_url="https://icon.png",
            tool_category="github",
        )
        # The subagent_id/stream identity must reach the graph run itself.
        mock_execute.assert_awaited_once_with(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=None,
            subagent_id="gh-1",
        )
        mock_end.assert_called_once_with(subagent_id="gh-1", duration_ms=3250)
        assert writer.call_args_list == [
            call({"subagent_start": START_EVENT}),
            call({"subagent_end": END_EVENT}),
        ]
        mock_release.assert_called_once_with("stream-1", "github")
        log.info.assert_called_once_with(
            f"{LogTag.AGENT} Background subagent completed",
            agent_name="test_agent",
            stream_id="stream-1",
        )

    async def test_integration_metadata_forwarded_to_graph_run(
        self, wide_task_mock: MagicMock
    ) -> None:
        """Non-None integration metadata is passed through untouched to the
        graph run — the handoff's icon/name must survive to the tool events."""
        ctx = _make_ctx()
        metadata = {"name": "GitHub", "icon_url": "https://icon.png"}
        writer = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=writer),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ) as mock_execute,
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(
                ctx, "stream-1", integration_metadata=metadata
            )

        mock_execute.assert_awaited_once_with(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=metadata,
            subagent_id=None,
        )

    async def test_display_name_falls_back_to_agent_name(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx()
        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.format_subagent_start_event", return_value=START_EVENT
            ) as mock_start,
            patch(
                f"{MODULE}.format_subagent_end_event", return_value=END_EVENT
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(ctx, "stream-1", subagent_id="gh-1")

        mock_start.assert_called_once_with(
            subagent_name="test_agent",
            agent_type="handoff",
            subagent_id="gh-1",
            icon_url=None,
            tool_category=None,
        )

    async def test_paused_outcome_parks_and_appends_nothing(
        self, wide_task_mock: MagicMock
    ) -> None:
        """A HIL pause is not an error: park durably, append no result, and still
        run the finally-block bookkeeping."""
        ctx = _make_ctx()
        interrupt = {"approval_id": "ap-1", "thread_id": "th-9"}
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="ignored", interrupt=interrupt),
            ),
            patch(f"{MODULE}._park", new_callable=AsyncMock) as mock_park,
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents") as mock_decrement,
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ) as mock_wake,
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(ctx, "stream-1", subagent_id="gh-1")

        mock_park.assert_awaited_once_with(ctx, interrupt, "stream-1")
        mock_append.assert_not_awaited()
        mock_decrement.assert_called_once_with("stream-1")
        mock_wake.assert_awaited_once_with("conv-1", ctx.configurable)
        log.info.assert_not_called()

    async def test_unresumable_pause_becomes_exact_error_result(
        self, wide_task_mock: MagicMock
    ) -> None:
        """An interrupt missing the approval id makes the real _park raise (the
        thread id comes from the configurable, not the interrupt); the error
        lands as the subagent's result text with the exact message."""
        ctx = _make_ctx()
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(
                    text="ignored", interrupt={"thread_id": "th-1"}
                ),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(ctx, "stream-1", subagent_id="gh-1")

        expected = (
            "Background subagent test_agent paused on approval but the pause "
            "is unresumable (approval_id='', thread_id='t1')"
        )
        mock_append.assert_awaited_once_with(
            "conv-1", "test_agent", f"Error from test_agent: {expected}"
        )
        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Background subagent failed",
            agent_name="test_agent",
            stream_id="stream-1",
            error=expected,
        )

    async def test_empty_interrupt_dict_is_unresumable(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx()
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="ignored", interrupt={}),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(ctx, "stream-1")

        expected = (
            "Background subagent test_agent paused on approval but the pause "
            "is unresumable (approval_id='', thread_id='t1')"
        )
        mock_append.assert_awaited_once_with(
            "conv-1", "test_agent", f"Error from test_agent: {expected}"
        )
        log.error.assert_called_once()

    async def test_execute_exception_appends_error_result_and_still_cleans_up(
        self, wide_task_mock: MagicMock
    ) -> None:
        """Any exception from the graph run becomes an exact error result, and
        the finally block still releases, decrements, and wakes."""
        ctx = _make_ctx()
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                side_effect=ValueError("boom"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents") as mock_decrement,
            patch(f"{MODULE}.release_bg_integration") as mock_release,
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ) as mock_wake,
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(
                ctx, "stream-1", subagent_id="gh-1", integration_id="github"
            )

        mock_append.assert_awaited_once_with(
            "conv-1", "test_agent", "Error from test_agent: boom"
        )
        mock_release.assert_called_once_with("stream-1", "github")
        mock_decrement.assert_called_once_with("stream-1")
        mock_wake.assert_awaited_once_with("conv-1", ctx.configurable)
        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Background subagent failed",
            agent_name="test_agent",
            stream_id="stream-1",
            error="boom",
        )

    async def test_writer_exception_appends_error_result(
        self, wide_task_mock: MagicMock
    ) -> None:
        """A failing stream publish must not crash the task either."""
        ctx = _make_ctx()
        failing_writer = MagicMock(side_effect=RuntimeError("publish failed"))
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=failing_writer),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log", log),
        ):
            await run_subagent_background(ctx, "stream-1", subagent_id="gh-1")

        mock_append.assert_awaited_once_with(
            "conv-1", "test_agent", "Error from test_agent: publish failed"
        )
        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Background subagent failed",
            agent_name="test_agent",
            stream_id="stream-1",
            error="publish failed",
        )

    async def test_wide_task_boundary_carries_spawner_context(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx()
        with (
            patch(f"{MODULE}.get_trace_id", return_value="trace-abc"),
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(
                ctx,
                "stream-1",
                subagent_id="gh-1",
                integration_id="github",
            )

        wide_task_mock.assert_called_once_with(
            "subagent_run",
            trace_id="trace-abc",
            agent_name="test_agent",
            conversation_id="conv-1",
            stream_id="stream-1",
            subagent_id="gh-1",
            integration_id="github",
        )

    async def test_wide_task_trace_id_defaults_to_none(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx()
        with (
            patch(f"{MODULE}.get_trace_id", return_value=""),
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(ctx, "stream-1")

        assert wide_task_mock.call_args.kwargs["trace_id"] is None

    async def test_missing_conversation_id_defaults_to_empty_string(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx(configurable={"thread_id": "t1"})
        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ) as mock_wake,
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(ctx, "stream-1")

        mock_append.assert_awaited_once_with("", "test_agent", "done")
        mock_wake.assert_awaited_once_with("", ctx.configurable)

    async def test_non_string_conversation_id_is_stringified(
        self, wide_task_mock: MagicMock
    ) -> None:
        ctx = _make_ctx(configurable={"thread_id": "t1", "conversation_id": 12345})
        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                return_value=SubagentOutcome(text="done"),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents"),
            patch(f"{MODULE}.release_bg_integration"),
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ),
            patch(f"{MODULE}.log"),
        ):
            await run_subagent_background(ctx, "stream-1")

        mock_append.assert_awaited_once_with("12345", "test_agent", "done")

    async def test_base_exception_propagates_but_finally_still_runs(
        self, wide_task_mock: MagicMock
    ) -> None:
        """Only Exception subclasses become error results. A BaseException (e.g.
        task cancellation) escapes — but the finally block still releases,
        decrements, and wakes so bookkeeping never leaks."""
        ctx = _make_ctx()
        log = MagicMock()

        with (
            patch(f"{MODULE}.make_redis_stream_writer", return_value=MagicMock()),
            patch(
                f"{MODULE}.execute_subagent_stream",
                new_callable=AsyncMock,
                side_effect=KeyboardInterrupt(),
            ),
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.decrement_pending_subagents") as mock_decrement,
            patch(f"{MODULE}.release_bg_integration") as mock_release,
            patch(
                f"{MODULE}._wake_if_executor_rested", new_callable=AsyncMock
            ) as mock_wake,
            patch(f"{MODULE}.log", log),
        ):
            with pytest.raises(KeyboardInterrupt):
                await run_subagent_background(
                    ctx, "stream-1", integration_id="github"
                )

        mock_append.assert_not_awaited()
        mock_release.assert_called_once_with("stream-1", "github")
        mock_decrement.assert_called_once_with("stream-1")
        mock_wake.assert_awaited_once_with("conv-1", ctx.configurable)
        log.error.assert_not_called()


# ---------------------------------------------------------------------------
# _wake_if_executor_rested
# ---------------------------------------------------------------------------


class TestWakeIfExecutorRested:
    async def test_empty_conversation_id_returns_immediately(self) -> None:
        with (
            patch(
                f"{MODULE}.is_executor_busy", new_callable=AsyncMock
            ) as mock_busy,
            patch(
                f"{MODULE}.enqueue_collection_run", new_callable=AsyncMock
            ) as mock_enqueue,
        ):
            await _wake_if_executor_rested("", {"thread_id": "t1"})

        mock_busy.assert_not_awaited()
        mock_enqueue.assert_not_awaited()

    async def test_background_execution_mode_returns_immediately(self) -> None:
        with (
            patch(
                f"{MODULE}.is_executor_busy", new_callable=AsyncMock
            ) as mock_busy,
            patch(
                f"{MODULE}.enqueue_collection_run", new_callable=AsyncMock
            ) as mock_enqueue,
        ):
            await _wake_if_executor_rested(
                "conv-1", {"execution_mode": "background"}
            )

        mock_busy.assert_not_awaited()
        mock_enqueue.assert_not_awaited()

    async def test_idle_executor_queues_collection_run(self) -> None:
        configurable = {"thread_id": "t1", "user_id": "u1"}
        with (
            patch(
                f"{MODULE}.is_executor_busy",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_busy,
            patch(
                f"{MODULE}.enqueue_collection_run", new_callable=AsyncMock
            ) as mock_enqueue,
            patch(f"{MODULE}.log"),
        ):
            await _wake_if_executor_rested("conv-1", configurable)

        mock_busy.assert_awaited_once_with("conv-1")
        mock_enqueue.assert_awaited_once_with("conv-1", configurable)

    async def test_busy_executor_skips_collection_run(self) -> None:
        with (
            patch(
                f"{MODULE}.is_executor_busy",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_busy,
            patch(
                f"{MODULE}.enqueue_collection_run", new_callable=AsyncMock
            ) as mock_enqueue,
            patch(f"{MODULE}.log"),
        ):
            await _wake_if_executor_rested("conv-1", {"thread_id": "t1"})

        mock_busy.assert_awaited_once_with("conv-1")
        mock_enqueue.assert_not_awaited()

    async def test_busy_check_failure_logged_and_suppressed(self) -> None:
        log = MagicMock()
        with (
            patch(
                f"{MODULE}.is_executor_busy",
                new_callable=AsyncMock,
                side_effect=RuntimeError("redis down"),
            ),
            patch(
                f"{MODULE}.enqueue_collection_run", new_callable=AsyncMock
            ) as mock_enqueue,
            patch(f"{MODULE}.log", log),
        ):
            await _wake_if_executor_rested("conv-1", {"thread_id": "t1"})

        mock_enqueue.assert_not_awaited()
        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Could not queue collection wake-up",
            conversation_id="conv-1",
            error="redis down",
        )

    async def test_enqueue_failure_logged_and_suppressed(self) -> None:
        log = MagicMock()
        with (
            patch(
                f"{MODULE}.is_executor_busy",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                f"{MODULE}.enqueue_collection_run",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
            patch(f"{MODULE}.log", log),
        ):
            await _wake_if_executor_rested("conv-1", {"thread_id": "t1"})

        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Could not queue collection wake-up",
            conversation_id="conv-1",
            error="boom",
        )


# ---------------------------------------------------------------------------
# _park
# ---------------------------------------------------------------------------


class TestPark:
    async def test_missing_approval_id_raises_exact_error(self) -> None:
        """The thread id for a park comes from the ctx configurable — the
        interrupt dict only supplies the approval id."""
        ctx = _make_ctx()
        with (
            patch(
                f"{MODULE}.stamp_subagent_resume", new_callable=AsyncMock
            ) as mock_stamp,
            patch(f"{MODULE}.log"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await _park(ctx, {"thread_id": "th-1"}, "stream-1")

        assert str(exc_info.value) == (
            "Background subagent test_agent paused on approval but the pause "
            "is unresumable (approval_id='', thread_id='t1')"
        )
        mock_stamp.assert_not_awaited()

    async def test_missing_thread_id_in_configurable_raises_exact_error(
        self,
    ) -> None:
        ctx = _make_ctx(configurable={"conversation_id": "conv-1"})
        with (
            patch(
                f"{MODULE}.stamp_subagent_resume", new_callable=AsyncMock
            ) as mock_stamp,
            patch(f"{MODULE}.log"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await _park(ctx, {"approval_id": "ap-1"}, "stream-1")

        assert str(exc_info.value) == (
            "Background subagent test_agent paused on approval but the pause "
            "is unresumable (approval_id='ap-1', thread_id='')"
        )
        mock_stamp.assert_not_awaited()

    async def test_stamps_resume_and_logs_park(self) -> None:
        """The stamped thread id is the ctx configurable's, NOT the interrupt's."""
        ctx = _make_ctx(
            configurable={"thread_id": "th-9", "conversation_id": "conv-1"}
        )
        log = MagicMock()
        with (
            patch(
                f"{MODULE}.stamp_subagent_resume", new_callable=AsyncMock
            ) as mock_stamp,
            patch(f"{MODULE}.log", log),
        ):
            await _park(
                ctx, {"approval_id": "ap-1", "thread_id": "IGNORED"}, "stream-1"
            )

        mock_stamp.assert_awaited_once_with(
            "ap-1",
            subagent_thread_id="th-9",
            subagent_agent_name="test_agent",
        )
        log.info.assert_called_once_with(
            f"{LogTag.HIL} Background subagent parked on approval",
            agent_name="test_agent",
            approval_id="ap-1",
            subagent_thread_id="th-9",
            stream_id="stream-1",
        )


# ---------------------------------------------------------------------------
# _append_error_result
# ---------------------------------------------------------------------------


class TestAppendErrorResult:
    async def test_appends_exact_error_text(self) -> None:
        with (
            patch(
                f"{MODULE}.append_bg_subagent_result", new_callable=AsyncMock
            ) as mock_append,
            patch(f"{MODULE}.log"),
        ):
            await _append_error_result("conv-1", "test_agent", RuntimeError("boom"))

        mock_append.assert_awaited_once_with(
            "conv-1", "test_agent", "Error from test_agent: boom"
        )

    async def test_redis_failure_logged_and_suppressed(self) -> None:
        log = MagicMock()
        with (
            patch(
                f"{MODULE}.append_bg_subagent_result",
                new_callable=AsyncMock,
                side_effect=ConnectionError("redis gone"),
            ),
            patch(f"{MODULE}.log", log),
        ):
            await _append_error_result("conv-1", "test_agent", RuntimeError("boom"))

        log.error.assert_called_once_with(
            f"{LogTag.AGENT} Could not store bg subagent error result",
            agent_name="test_agent",
            error="redis gone",
        )
