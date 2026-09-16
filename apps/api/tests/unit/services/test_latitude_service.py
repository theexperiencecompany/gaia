"""Unit tests for Latitude turn telemetry."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.latitude_service import TurnCapture, begin_turn, end_turn


def _settings(api_key: str | None) -> SimpleNamespace:
    return SimpleNamespace(LATITUDE_API_KEY=api_key, LATITUDE_PROJECT="gaia")


class TestBeginTurn:
    def test_returns_none_when_api_key_missing(self) -> None:
        with (
            patch("app.services.latitude_service.settings", _settings(None)),
            patch("app.services.latitude_service.capture") as mock_capture,
        ):
            assert begin_turn(user_id="u1", conversation_id="c1") is None
            mock_capture.start.assert_not_called()

    def test_returns_none_when_user_id_missing(self) -> None:
        with (
            patch("app.services.latitude_service.settings", _settings("key-1")),
            patch("app.services.latitude_service.capture") as mock_capture,
        ):
            assert begin_turn(user_id="", conversation_id="c1") is None
            mock_capture.start.assert_not_called()

    def test_binds_scope_and_current_span(self) -> None:
        scope = MagicMock()
        span = MagicMock()
        with (
            patch("app.services.latitude_service.settings", _settings("key-1")),
            patch("app.services.latitude_service.capture") as mock_capture,
            patch("app.services.latitude_service.trace") as mock_trace,
        ):
            mock_capture.start.return_value = scope
            mock_trace.get_current_span.return_value = span

            result = begin_turn(
                user_id="u1",
                conversation_id="c1",
                properties={"source": "web", "voice_mode": None},
            )

            assert result == TurnCapture(scope=scope, span=span)
            name, options = mock_capture.start.call_args.args
            assert name == "comms_agent"
            assert options["user_id"] == "u1"
            assert options["session_id"] == "c1"
            assert options["project"] == "gaia"
            assert options["metadata"] == {"source": "web"}

    def test_sdk_failure_returns_none_without_raising(self) -> None:
        with (
            patch("app.services.latitude_service.settings", _settings("key-1")),
            patch("app.services.latitude_service.capture") as mock_capture,
            patch("app.services.latitude_service.log") as mock_log,
        ):
            mock_capture.start.side_effect = RuntimeError("boom")

            assert begin_turn(user_id="u1", conversation_id="c1") is None
            mock_log.warning.assert_called_once_with(
                "latitude_begin_failed",
                error="boom",
                error_type="RuntimeError",
                conversation_id="c1",
            )

    def test_none_valued_properties_are_dropped(self) -> None:
        scope = MagicMock()
        with (
            patch("app.services.latitude_service.settings", _settings("key-1")),
            patch("app.services.latitude_service.capture") as mock_capture,
        ):
            mock_capture.start.return_value = scope

            begin_turn(user_id="u1", conversation_id="c1", properties={"keep": "x", "drop": None})

            _, options = mock_capture.start.call_args.args
            assert options["metadata"] == {"keep": "x"}


class TestEndTurn:
    def test_none_scope_is_noop(self) -> None:
        with patch("app.services.latitude_service.capture") as mock_capture:
            end_turn(None)
            mock_capture.end.assert_not_called()

    def test_success_ends_without_error_or_tag(self) -> None:
        scope, span = MagicMock(), MagicMock()
        handle = TurnCapture(scope=scope, span=span)
        with patch("app.services.latitude_service.capture") as mock_capture:
            end_turn(handle)

            span.set_attribute.assert_not_called()
            mock_capture.end.assert_called_once_with(scope, None)

    def test_error_ends_with_error_and_no_tag(self) -> None:
        scope, span = MagicMock(), MagicMock()
        handle = TurnCapture(scope=scope, span=span)
        error = RuntimeError("provider down")
        with patch("app.services.latitude_service.capture") as mock_capture:
            end_turn(handle, error=error)

            span.set_attribute.assert_not_called()
            mock_capture.end.assert_called_once_with(scope, error)

    def test_cancelled_tags_stored_span_and_ends_clean(self) -> None:
        scope, span = MagicMock(), MagicMock()
        span.is_recording.return_value = True
        other_span = MagicMock()
        handle = TurnCapture(scope=scope, span=span)
        with (
            patch("app.services.latitude_service.capture") as mock_capture,
            patch("app.services.latitude_service.trace") as mock_trace,
        ):
            # Even if the ambient current span has moved on, the stored span
            # wears the marker — never the stranger.
            mock_trace.get_current_span.return_value = other_span

            end_turn(handle, cancelled=True)

            span.set_attribute.assert_called_once_with("cancelled", True)
            other_span.set_attribute.assert_not_called()
            mock_capture.end.assert_called_once_with(scope, None)

    def test_error_dominates_cancelled(self) -> None:
        scope, span = MagicMock(), MagicMock()
        handle = TurnCapture(scope=scope, span=span)
        error = RuntimeError("provider down")
        with patch("app.services.latitude_service.capture") as mock_capture:
            end_turn(handle, error=error, cancelled=True)

            span.set_attribute.assert_not_called()
            mock_capture.end.assert_called_once_with(scope, error)

    def test_sdk_failure_does_not_raise(self) -> None:
        scope, span = MagicMock(), MagicMock()
        handle = TurnCapture(scope=scope, span=span)
        with (
            patch("app.services.latitude_service.capture") as mock_capture,
            patch("app.services.latitude_service.log") as mock_log,
        ):
            mock_capture.end.side_effect = RuntimeError("boom")

            end_turn(handle, error=RuntimeError("x"))
            mock_log.warning.assert_called_once_with(
                "latitude_end_failed", error="boom", error_type="RuntimeError"
            )
