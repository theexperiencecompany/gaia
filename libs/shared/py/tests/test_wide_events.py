"""Tests for shared.py.wide_events — WideEventLogger, wide_task context manager, trace_id."""

import asyncio
import contextvars
from unittest.mock import MagicMock, patch

import pytest

from shared.py.wide_events import (
    WideEventLogger,
    _LEVEL_ORDER,
    _max_level,
    _trace_id,
    _wide_event,
    get_trace_id,
    log,
    wide_task,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_context_vars():
    """Reset all ContextVars between tests to prevent cross-test leakage."""
    _wide_event.set(None)
    _max_level.set("INFO")
    _trace_id.set("")
    yield
    _wide_event.set(None)
    _max_level.set("INFO")
    _trace_id.set("")


# ---------------------------------------------------------------------------
# WideEventLogger — set / get / reset
# ---------------------------------------------------------------------------


class TestWideEventLoggerSetGetReset:
    """Tests for the core set(), get(), reset() API."""

    def test_get_returns_empty_dict_when_no_event(self):
        assert log.get() == {}

    def test_set_creates_event_from_none(self):
        log.set(user_id="abc")
        assert log.get() == {"user_id": "abc"}

    def test_set_merges_keys(self):
        log.set(a=1)
        log.set(b=2)
        event = log.get()
        assert event == {"a": 1, "b": 2}

    def test_set_overwrites_existing_key(self):
        log.set(status="pending")
        log.set(status="done")
        assert log.get()["status"] == "done"

    def test_reset_clears_event_and_sets_trace_id(self):
        log.set(old="data")
        log.reset()
        event = log.get()
        assert "old" not in event
        assert "trace_id" in event
        assert len(event["trace_id"]) == 16

    def test_reset_resets_max_level_to_info(self):
        _max_level.set("ERROR")
        log.reset()
        assert log.get_max_level() == "INFO"

    def test_reset_generates_unique_trace_ids(self):
        log.reset()
        tid1 = log.get_trace_id()
        log.reset()
        tid2 = log.get_trace_id()
        assert tid1 != tid2

    def test_get_trace_id_returns_empty_before_reset(self):
        assert log.get_trace_id() == ""


# ---------------------------------------------------------------------------
# WideEventLogger — info / warning / error / critical / debug / exception
# ---------------------------------------------------------------------------


class TestWideEventLoggerLevels:
    """Tests for log level methods and their side effects on wide event."""

    @patch("shared.py.wide_events._loguru")
    def test_info_emits_loguru_but_not_wide_event(self, mock_loguru: MagicMock):
        log.info("hello")
        mock_loguru.opt.return_value.info.assert_called_once_with("hello")
        # info should NOT append to wide event
        assert log.get() == {}

    @patch("shared.py.wide_events._loguru")
    def test_debug_emits_loguru_but_not_wide_event(self, mock_loguru: MagicMock):
        log.debug("debugging")
        mock_loguru.opt.return_value.debug.assert_called_once_with("debugging")
        assert log.get() == {}

    @patch("shared.py.wide_events._loguru")
    def test_warning_appends_to_warnings(self, mock_loguru: MagicMock):
        log.warning("watch out")
        event = log.get()
        assert len(event["warnings"]) == 1
        assert event["warnings"][0]["msg"] == "watch out"

    @patch("shared.py.wide_events._loguru")
    def test_warning_bumps_max_level(self, mock_loguru: MagicMock):
        log.warning("bump")
        assert log.get_max_level() == "WARNING"

    @patch("shared.py.wide_events._loguru")
    def test_error_appends_to_errors(self, mock_loguru: MagicMock):
        log.error("failure")
        event = log.get()
        assert len(event["errors"]) == 1
        assert event["errors"][0]["msg"] == "failure"

    @patch("shared.py.wide_events._loguru")
    def test_error_bumps_max_level(self, mock_loguru: MagicMock):
        log.error("fail")
        assert log.get_max_level() == "ERROR"

    @patch("shared.py.wide_events._loguru")
    def test_critical_appends_to_errors(self, mock_loguru: MagicMock):
        log.critical("crash")
        event = log.get()
        assert len(event["errors"]) == 1
        assert event["errors"][0]["msg"] == "crash"

    @patch("shared.py.wide_events._loguru")
    def test_critical_bumps_max_level_above_error(self, mock_loguru: MagicMock):
        log.error("err")
        log.critical("crash")
        assert log.get_max_level() == "CRITICAL"

    @patch("shared.py.wide_events._loguru")
    def test_exception_appends_to_errors_with_traceback(self, mock_loguru: MagicMock):
        log.exception("unhandled")
        event = log.get()
        assert event["errors"][0]["msg"] == "unhandled"
        # Should call loguru with exception=True
        mock_loguru.opt.assert_called_with(depth=1, exception=True)

    @patch("shared.py.wide_events._loguru")
    def test_warning_with_kwargs(self, mock_loguru: MagicMock):
        log.warning("slow query", query="SELECT *", duration_ms=5000)
        event = log.get()
        assert event["warnings"][0]["query"] == "SELECT *"
        assert event["warnings"][0]["duration_ms"] == 5000

    @patch("shared.py.wide_events._loguru")
    def test_error_with_exc_info(self, mock_loguru: MagicMock):
        log.error("failure", exc_info=True)
        mock_loguru.opt.assert_called_with(depth=1, exception=True)

    @patch("shared.py.wide_events._loguru")
    def test_warning_with_exc_info(self, mock_loguru: MagicMock):
        log.warning("warn", exc_info=True)
        mock_loguru.opt.assert_called_with(depth=1, exception=True)

    @patch("shared.py.wide_events._loguru")
    def test_critical_with_exc_info(self, mock_loguru: MagicMock):
        log.critical("crit", exc_info=True)
        mock_loguru.opt.assert_called_with(depth=1, exception=True)

    @patch("shared.py.wide_events._loguru")
    def test_multiple_warnings_accumulate(self, mock_loguru: MagicMock):
        log.warning("first")
        log.warning("second")
        log.warning("third")
        assert len(log.get()["warnings"]) == 3

    @patch("shared.py.wide_events._loguru")
    def test_errors_and_warnings_coexist(self, mock_loguru: MagicMock):
        log.warning("w1")
        log.error("e1")
        event = log.get()
        assert len(event["warnings"]) == 1
        assert len(event["errors"]) == 1


# ---------------------------------------------------------------------------
# WideEventLogger — bind
# ---------------------------------------------------------------------------


class TestWideEventLoggerBind:
    """Tests for the Loguru-compat bind() method."""

    def test_bind_merges_into_wide_event(self):
        log.bind(user_id="u1", plan="pro")
        event = log.get()
        assert event["user_id"] == "u1"
        assert event["plan"] == "pro"

    def test_bind_returns_self(self):
        result = log.bind(x=1)
        assert result is log

    @patch("shared.py.wide_events._loguru")
    def test_bind_then_info(self, mock_loguru: MagicMock):
        log.bind(user_id="u1").info("hello")
        assert log.get()["user_id"] == "u1"
        mock_loguru.opt.return_value.info.assert_called_once_with("hello")


# ---------------------------------------------------------------------------
# _bump — max level tracking
# ---------------------------------------------------------------------------


class TestBumpMaxLevel:
    """Test _bump() correctly tracks the highest severity."""

    @patch("shared.py.wide_events._loguru")
    def test_info_does_not_bump(self, mock_loguru: MagicMock):
        log.info("nothing")
        assert log.get_max_level() == "INFO"

    @patch("shared.py.wide_events._loguru")
    def test_error_does_not_downgrade_to_warning(self, mock_loguru: MagicMock):
        log.error("bad")
        log.warning("minor")
        assert log.get_max_level() == "ERROR"

    @patch("shared.py.wide_events._loguru")
    def test_unknown_level_treated_as_zero(self, mock_loguru: MagicMock):
        # Directly call _bump with an unknown level
        logger = WideEventLogger()
        logger._bump("UNKNOWN")
        # Should not bump above INFO default
        assert _max_level.get() == "INFO"


# ---------------------------------------------------------------------------
# _LEVEL_ORDER
# ---------------------------------------------------------------------------


class TestLevelOrder:
    """Verify the level ordering is correct."""

    def test_ordering(self):
        assert _LEVEL_ORDER["DEBUG"] < _LEVEL_ORDER["INFO"]
        assert _LEVEL_ORDER["INFO"] < _LEVEL_ORDER["WARNING"]
        assert _LEVEL_ORDER["WARNING"] < _LEVEL_ORDER["ERROR"]
        assert _LEVEL_ORDER["ERROR"] < _LEVEL_ORDER["CRITICAL"]


# ---------------------------------------------------------------------------
# trace_id
# ---------------------------------------------------------------------------


class TestTraceId:
    """Tests for trace_id management."""

    def test_get_trace_id_matches_event(self):
        log.reset()
        tid = log.get_trace_id()
        assert tid == log.get()["trace_id"]

    def test_trace_id_is_16_hex_chars(self):
        log.reset()
        tid = log.get_trace_id()
        assert len(tid) == 16
        int(tid, 16)  # Should not raise — valid hex

    def test_module_level_get_trace_id(self):
        log.reset()
        assert get_trace_id() == log.get_trace_id()


# ---------------------------------------------------------------------------
# wide_task context manager
# ---------------------------------------------------------------------------


class TestWideTask:
    """Tests for the wide_task async context manager."""

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_sets_task_name(self, mock_loguru: MagicMock):
        async with wide_task("process_email"):
            event = log.get()
            assert event["task"] == "process_email"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_sets_initial_context(self, mock_loguru: MagicMock):
        async with wide_task("sync", reminder_id="r1"):
            event = log.get()
            assert event["reminder_id"] == "r1"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_success_sets_outcome(self, mock_loguru: MagicMock):
        async with wide_task("ok_task"):
            pass
        # After exiting, the final event should have outcome=success
        event = log.get()
        assert event["outcome"] == "success"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_failure_sets_outcome_and_reraises(self, mock_loguru: MagicMock):
        with pytest.raises(RuntimeError, match="boom"):
            async with wide_task("fail_task"):
                raise RuntimeError("boom")
        event = log.get()
        assert event["outcome"] == "failed"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_duration_ms_recorded(self, mock_loguru: MagicMock):
        async with wide_task("timed_task"):
            pass
        event = log.get()
        assert "duration_ms" in event
        assert isinstance(event["duration_ms"], float)

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_final_level_set(self, mock_loguru: MagicMock):
        async with wide_task("level_task"):
            log.warning("w")
        event = log.get()
        assert event["final_level"] == "WARNING"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_emits_worker_task_log(self, mock_loguru: MagicMock):
        async with wide_task("worker"):
            pass
        mock_loguru.bind.assert_called()
        # The .log() call should have level="INFO" (default max) and message "worker_task"
        mock_loguru.bind.return_value.log.assert_called_once()
        call_args = mock_loguru.bind.return_value.log.call_args
        assert call_args.args[1] == "worker_task"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_custom_trace_id(self, mock_loguru: MagicMock):
        async with wide_task("traced", trace_id="custom123"):
            assert log.get_trace_id() == "custom123"
            assert log.get()["trace_id"] == "custom123"

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_auto_trace_id_when_none(self, mock_loguru: MagicMock):
        async with wide_task("auto_trace"):
            tid = log.get_trace_id()
            assert len(tid) == 16

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_yields_log_instance(self, mock_loguru: MagicMock):
        async with wide_task("yield_test") as yielded:
            assert yielded is log

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_failure_records_error_in_event(self, mock_loguru: MagicMock):
        with pytest.raises(ValueError):
            async with wide_task("err_task"):
                raise ValueError("bad value")
        event = log.get()
        assert len(event["errors"]) == 1
        assert event["errors"][0]["error"] == "bad value"
        assert event["errors"][0]["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# ContextVar isolation
# ---------------------------------------------------------------------------


class TestContextVarIsolation:
    """Verify each async task gets its own wide event context."""

    @pytest.mark.asyncio
    @patch("shared.py.wide_events._loguru")
    async def test_concurrent_tasks_isolated(self, mock_loguru: MagicMock):
        results: dict[str, dict] = {}

        async def task(name: str):
            log.reset()
            log.set(task_name=name)
            await asyncio.sleep(0.01)
            results[name] = log.get()

        ctx1 = contextvars.copy_context()
        ctx2 = contextvars.copy_context()

        loop = asyncio.get_event_loop()
        await asyncio.gather(
            loop.run_in_executor(None, ctx1.run, asyncio.run, task("task_a")),
            loop.run_in_executor(None, ctx2.run, asyncio.run, task("task_b")),
        )

        assert results["task_a"]["task_name"] == "task_a"
        assert results["task_b"]["task_name"] == "task_b"


# ---------------------------------------------------------------------------
# WideEventLogger — fresh instance
# ---------------------------------------------------------------------------


class TestWideEventLoggerFreshInstance:
    """Test that WideEventLogger can be instantiated independently."""

    def test_new_instance_shares_context_vars(self):
        fresh = WideEventLogger()
        log.set(shared="yes")
        assert fresh.get()["shared"] == "yes"

    def test_new_instance_reset_affects_module_log(self):
        fresh = WideEventLogger()
        log.set(old="data")
        fresh.reset()
        assert "old" not in log.get()
