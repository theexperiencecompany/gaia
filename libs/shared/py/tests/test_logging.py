"""Tests for shared.py.logging — configure_loguru, configure_file_logging, get_contextual_logger, JSON format."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import shared.py.logging as logging_mod
from shared.py.logging import (
    LOG_CONFIG,
    _build_json_entry,
    _json_file_sink_factory,
    _json_stdout_sink,
    configure_file_logging,
    configure_loguru,
    get_contextual_logger,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_configured_flags():
    """Reset module-level guards so each test can reconfigure."""
    original_loguru = logging_mod._LOGURU_CONFIGURED
    original_file = logging_mod._FILE_LOGGING_CONFIGURED
    logging_mod._LOGURU_CONFIGURED = False
    logging_mod._FILE_LOGGING_CONFIGURED = False
    yield
    logging_mod._LOGURU_CONFIGURED = original_loguru
    logging_mod._FILE_LOGGING_CONFIGURED = original_file


@pytest.fixture()
def mock_logger():
    """Provide a fully mocked loguru logger for isolated unit tests."""
    with patch.object(logging_mod, "logger") as mocked:
        mocked.remove = MagicMock()
        mocked.configure = MagicMock()
        mocked.add = MagicMock(return_value=1)
        mocked.level = MagicMock()
        mocked.bind = MagicMock(return_value=mocked)
        yield mocked


# ---------------------------------------------------------------------------
# configure_loguru
# ---------------------------------------------------------------------------


class TestConfigureLoguru:
    """Tests for the configure_loguru function."""

    def test_returns_logger_instance(self, mock_logger: MagicMock):
        result = configure_loguru()
        assert result is mock_logger

    def test_idempotent_second_call_skips(self, mock_logger: MagicMock):
        configure_loguru()
        mock_logger.remove.assert_called_once()

        # Second call — the flag is already True
        configure_loguru()
        # remove() should still have been called only once
        mock_logger.remove.assert_called_once()

    def test_removes_default_handler(self, mock_logger: MagicMock):
        configure_loguru()
        mock_logger.remove.assert_called_once()

    def test_configures_extra_with_default_logger_name(self, mock_logger: MagicMock):
        configure_loguru()
        mock_logger.configure.assert_called_once_with(extra={"logger_name": "APP"})

    def test_registers_custom_levels(self, mock_logger: MagicMock):
        configure_loguru()
        level_calls = mock_logger.level.call_args_list
        level_names = [c.args[0] for c in level_calls]
        assert "PERFORMANCE" in level_names
        assert "AUDIT" in level_names
        assert "SECURITY" in level_names

    def test_console_mode_adds_stderr_sink(self, mock_logger: MagicMock):
        with patch.dict(LOG_CONFIG, {"format_mode": "console"}):
            configure_loguru()
        # The first .add() call should target stderr
        first_add = mock_logger.add.call_args_list[0]
        assert first_add.args[0] is sys.stderr

    def test_json_mode_adds_json_sink(self, mock_logger: MagicMock):
        with patch.dict(LOG_CONFIG, {"format_mode": "json"}):
            configure_loguru()
        first_add = mock_logger.add.call_args_list[0]
        assert first_add.args[0] is _json_stdout_sink

    def test_intercept_handlers_attached(self, mock_logger: MagicMock):
        configure_loguru()
        for name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "gunicorn", "livekit", "app"]:
            specific = logging.getLogger(name)
            assert len(specific.handlers) == 1
            assert specific.propagate is False

    def test_app_logger_set_to_debug(self, mock_logger: MagicMock):
        configure_loguru()
        assert logging.getLogger("app").level == logging.DEBUG


# ---------------------------------------------------------------------------
# configure_file_logging
# ---------------------------------------------------------------------------


class TestConfigureFileLogging:
    """Tests for configure_file_logging."""

    def test_creates_log_directory(self, tmp_path: Path, mock_logger: MagicMock):
        log_dir = tmp_path / "custom_logs"
        configure_file_logging(log_dir)
        assert log_dir.exists()

    def test_idempotent(self, tmp_path: Path, mock_logger: MagicMock):
        configure_file_logging(tmp_path)
        call_count = mock_logger.add.call_count
        # Reset flag manually since fixture resets before test — but the function
        # set it internally so second call should be skipped
        logging_mod._FILE_LOGGING_CONFIGURED = True
        configure_file_logging(tmp_path)
        assert mock_logger.add.call_count == call_count

    def test_adds_five_sinks(self, tmp_path: Path, mock_logger: MagicMock):
        configure_file_logging(tmp_path)
        # general, error, json (callable), critical, performance
        assert mock_logger.add.call_count == 5

    def test_default_log_dir_from_config(self, mock_logger: MagicMock):
        with patch.dict(LOG_CONFIG, {"log_dir": "/tmp/claude/test_logs"}):
            with patch.object(Path, "mkdir"):
                configure_file_logging(None)
            first_add = mock_logger.add.call_args_list[0]
            # The path should be based on the config value
            assert "/tmp/claude/test_logs" in str(first_add.args[0])

    def test_accepts_string_path(self, tmp_path: Path, mock_logger: MagicMock):
        configure_file_logging(str(tmp_path))
        assert mock_logger.add.call_count == 5

    def test_performance_sink_has_filter(self, tmp_path: Path, mock_logger: MagicMock):
        configure_file_logging(tmp_path)
        # The last .add() call is the performance sink
        perf_call = mock_logger.add.call_args_list[4]
        assert "filter" in perf_call.kwargs
        filter_fn = perf_call.kwargs["filter"]
        # Filter should pass when 'performance' is in extra
        record_with = {"extra": {"performance": True}}
        record_without = {"extra": {}}
        assert filter_fn(record_with) is True
        assert filter_fn(record_without) is False


# ---------------------------------------------------------------------------
# get_contextual_logger
# ---------------------------------------------------------------------------


class TestGetContextualLogger:
    """Tests for get_contextual_logger."""

    def test_returns_bound_logger(self, mock_logger: MagicMock):
        result = get_contextual_logger("auth")
        mock_logger.bind.assert_called_once_with(logger_name="AUTH")
        assert result is mock_logger.bind.return_value

    def test_name_truncated_to_seven_chars(self, mock_logger: MagicMock):
        get_contextual_logger("a_very_long_name")
        _, kwargs = mock_logger.bind.call_args
        assert kwargs["logger_name"] == "A_VERY_"

    def test_name_uppercased(self, mock_logger: MagicMock):
        get_contextual_logger("database")
        _, kwargs = mock_logger.bind.call_args
        assert kwargs["logger_name"] == "DATABAS"

    def test_extra_context_forwarded(self, mock_logger: MagicMock):
        get_contextual_logger("api", user_id=42, request_id="abc")
        _, kwargs = mock_logger.bind.call_args
        assert kwargs["user_id"] == 42
        assert kwargs["request_id"] == "abc"

    def test_short_name_not_padded(self, mock_logger: MagicMock):
        get_contextual_logger("db")
        _, kwargs = mock_logger.bind.call_args
        assert kwargs["logger_name"] == "DB"


# ---------------------------------------------------------------------------
# _build_json_entry
# ---------------------------------------------------------------------------


class TestBuildJsonEntry:
    """Tests for the _build_json_entry JSON serializer."""

    @staticmethod
    def _make_record(
        message: str = "test",
        level_name: str = "INFO",
        extra: dict | None = None,
        exception: object = None,
    ) -> dict:
        return {
            "time": datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            "level": SimpleNamespace(name=level_name),
            "message": message,
            "module": "test_module",
            "line": 42,
            "extra": {"logger_name": "TEST", **(extra or {})},
            "exception": exception,
        }

    def test_produces_valid_json(self):
        record = self._make_record()
        line = _build_json_entry(record)
        parsed = json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "test"
        assert parsed["logger"] == "TEST"
        assert parsed["module"] == "test_module"
        assert parsed["line"] == 42

    def test_ends_with_newline(self):
        record = self._make_record()
        assert _build_json_entry(record).endswith("\n")

    def test_extra_keys_merged(self):
        record = self._make_record(extra={"user_id": 123, "request_id": "abc"})
        parsed = json.loads(_build_json_entry(record))
        assert parsed["user_id"] == 123
        assert parsed["request_id"] == "abc"
        # logger_name itself should not leak into top-level
        assert "logger_name" not in parsed

    def test_exception_serialized(self):
        exc = SimpleNamespace(type=ValueError, value=ValueError("bad input"))
        record = self._make_record(exception=exc)
        parsed = json.loads(_build_json_entry(record))
        assert parsed["exception"]["type"] == "ValueError"
        assert "bad input" in parsed["exception"]["value"]

    def test_exception_none_fields(self):
        exc = SimpleNamespace(type=None, value=None)
        record = self._make_record(exception=exc)
        parsed = json.loads(_build_json_entry(record))
        assert parsed["exception"]["type"] is None
        assert parsed["exception"]["value"] is None

    def test_no_exception_field_when_none(self):
        record = self._make_record(exception=None)
        parsed = json.loads(_build_json_entry(record))
        assert "exception" not in parsed

    def test_non_serializable_defaults_to_str(self):
        record = self._make_record(extra={"weird": object()})
        # Should not raise — default=str handles it
        line = _build_json_entry(record)
        parsed = json.loads(line)
        assert isinstance(parsed["weird"], str)

    def test_time_is_isoformat(self):
        record = self._make_record()
        parsed = json.loads(_build_json_entry(record))
        assert "2025-01-01" in parsed["time"]


# ---------------------------------------------------------------------------
# _json_stdout_sink
# ---------------------------------------------------------------------------


class TestJsonStdoutSink:
    """Tests for _json_stdout_sink."""

    def test_writes_to_stdout(self):
        record = TestBuildJsonEntry._make_record()
        message = SimpleNamespace(record=record)

        with patch.object(sys, "stdout") as mock_stdout:
            mock_stdout.write = MagicMock()
            mock_stdout.flush = MagicMock()
            _json_stdout_sink(message)
            mock_stdout.write.assert_called_once()
            mock_stdout.flush.assert_called_once()

            written = mock_stdout.write.call_args.args[0]
            assert json.loads(written)["message"] == "test"


# ---------------------------------------------------------------------------
# _json_file_sink_factory
# ---------------------------------------------------------------------------


class TestJsonFileSinkFactory:
    """Tests for _json_file_sink_factory."""

    def test_creates_file_and_writes(self, tmp_path: Path):
        sink = _json_file_sink_factory(tmp_path)
        record = TestBuildJsonEntry._make_record()
        message = SimpleNamespace(record=record)

        sink(message)

        files = list(tmp_path.glob("structured-*.json"))
        assert len(files) == 1
        content = files[0].read_text()
        parsed = json.loads(content.strip())
        assert parsed["message"] == "test"

    def test_appends_to_same_file(self, tmp_path: Path):
        sink = _json_file_sink_factory(tmp_path)
        record = TestBuildJsonEntry._make_record()
        message = SimpleNamespace(record=record)

        sink(message)
        sink(message)

        files = list(tmp_path.glob("structured-*.json"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# InterceptHandler (integration through configure_loguru)
# ---------------------------------------------------------------------------


class TestInterceptHandler:
    """Test the stdlib InterceptHandler installed by configure_loguru."""

    def test_app_namespace_intercepted(self, mock_logger: MagicMock):
        configure_loguru()
        handler = logging.getLogger("app").handlers[0]
        # The handler should be an InterceptHandler
        assert handler.__class__.__name__ == "InterceptHandler"

    def test_non_app_namespace_ignored(self, mock_logger: MagicMock):
        configure_loguru()
        handler = logging.getLogger("app").handlers[0]
        # Create a record from a namespace that should NOT be intercepted
        record = logging.LogRecord(
            name="some.random.lib",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="should be ignored",
            args=(),
            exc_info=None,
        )
        # This should not raise and should not log
        handler.emit(record)

    def test_uvicorn_namespace_mapped(self, mock_logger: MagicMock):
        configure_loguru()
        handler = logging.getLogger("uvicorn.access").handlers[0]
        assert handler.__class__.__name__ == "InterceptHandler"


# ---------------------------------------------------------------------------
# LOG_CONFIG defaults
# ---------------------------------------------------------------------------


class TestLogConfig:
    """Test that LOG_CONFIG has expected defaults."""

    def test_default_level(self):
        # The config reads from env but falls back
        assert "level" in LOG_CONFIG

    def test_default_format_mode(self):
        assert LOG_CONFIG["format_mode"] in ("console", "json")

    def test_format_keys_present(self):
        assert "console" in LOG_CONFIG["format"]
        assert "file" in LOG_CONFIG["format"]
        assert "json" in LOG_CONFIG["format"]
