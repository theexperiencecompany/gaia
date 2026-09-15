"""Unit tests for Laminar turn telemetry."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.laminar_service import TurnScope, begin_turn, end_turn


def _settings(api_key: str | None) -> SimpleNamespace:
    return SimpleNamespace(LMNR_PROJECT_API_KEY=api_key)


def _entered_scope() -> tuple[MagicMock, MagicMock]:
    """A faked SDK context manager: enter returns the span it wraps."""
    scope = MagicMock()
    span = MagicMock()
    scope.__enter__.return_value = span
    return scope, span


class TestBeginTurn:
    def test_returns_none_when_api_key_missing(self) -> None:
        with (
            patch("app.services.laminar_service.settings", _settings(None)),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
        ):
            assert begin_turn(user_id="u1", conversation_id="c1") is None
            mock_sdk.start_as_current_span.assert_not_called()

    def test_returns_none_when_user_id_missing(self) -> None:
        with (
            patch("app.services.laminar_service.settings", _settings("key-1")),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
        ):
            assert begin_turn(user_id="", conversation_id="c1") is None
            mock_sdk.start_as_current_span.assert_not_called()

    def test_passes_input_ids_and_filtered_metadata(self) -> None:
        scope, span = _entered_scope()
        with (
            patch("app.services.laminar_service.settings", _settings("key-1")),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
        ):
            mock_sdk.start_as_current_span.return_value = scope

            result = begin_turn(
                user_id="u1",
                conversation_id="c1",
                user_input="hello",
                properties={"source": "web", "voice_mode": None},
            )

            assert result == TurnScope(scope=scope, span=span)
            kwargs = mock_sdk.start_as_current_span.call_args.kwargs
            assert mock_sdk.start_as_current_span.call_args.args == ("comms_agent",)
            assert kwargs["user_id"] == "u1"
            assert kwargs["session_id"] == "c1"
            assert kwargs["metadata"] == {"source": "web"}
            assert kwargs["input"] == "hello"

    def test_sdk_failure_returns_none_without_raising(self) -> None:
        with (
            patch("app.services.laminar_service.settings", _settings("key-1")),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
        ):
            mock_sdk.start_as_current_span.side_effect = RuntimeError("boom")

            assert begin_turn(user_id="u1", conversation_id="c1") is None

    def test_none_valued_properties_are_dropped(self) -> None:
        scope, _ = _entered_scope()
        with (
            patch("app.services.laminar_service.settings", _settings("key-1")),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
        ):
            mock_sdk.start_as_current_span.return_value = scope

            begin_turn(user_id="u1", conversation_id="c1", properties={"keep": "x", "drop": None})

            assert mock_sdk.start_as_current_span.call_args.kwargs["metadata"] == {"keep": "x"}


class TestEndTurn:
    def test_none_scope_is_noop(self) -> None:
        end_turn(None, output="hi")

    def test_success_sets_output_and_exits_clean(self) -> None:
        scope, span = _entered_scope()
        handle = TurnScope(scope=scope, span=span)

        end_turn(handle, output="hi")

        span.set_output.assert_called_once_with("hi")
        span.set_attribute.assert_not_called()
        scope.__exit__.assert_called_once_with(None, None, None)

    def test_error_exits_with_exception_and_no_cancelled_tag(self) -> None:
        scope, span = _entered_scope()
        handle = TurnScope(scope=scope, span=span)
        try:
            raise RuntimeError("provider down")
        except RuntimeError as error:
            caught = error
            tb = error.__traceback__

        assert tb is not None, "mutant guard: traceback must be real"
        end_turn(handle, output="boom", error=caught)

        span.set_output.assert_called_once_with("boom")
        span.set_attribute.assert_not_called()
        assert scope.__exit__.call_args.args == (type(caught), caught, tb)

    def test_cancelled_sets_output_tag_and_exits_clean(self) -> None:
        scope, span = _entered_scope()
        handle = TurnScope(scope=scope, span=span)

        end_turn(handle, output="partial", cancelled=True)

        span.set_output.assert_called_once_with("partial")
        span.set_attribute.assert_called_once_with("cancelled", True)
        scope.__exit__.assert_called_once_with(None, None, None)

    def test_span_update_failure_still_exits_without_raising(self) -> None:
        scope, span = _entered_scope()
        span.set_output.side_effect = RuntimeError("otel down")
        handle = TurnScope(scope=scope, span=span)
        with patch("app.services.laminar_service.log") as mock_log:
            end_turn(handle, output="hi")

            scope.__exit__.assert_called_once_with(None, None, None)
            mock_log.warning.assert_called_once_with(
                "laminar_span_update_failed", error="otel down", error_type="RuntimeError"
            )

    def test_exit_failure_does_not_raise(self) -> None:
        scope, span = _entered_scope()
        scope.__exit__.side_effect = RuntimeError("export down")
        handle = TurnScope(scope=scope, span=span)
        with patch("app.services.laminar_service.log") as mock_log:
            end_turn(handle, output="hi")

            mock_log.warning.assert_called_once_with(
                "laminar_end_failed", error="export down", error_type="RuntimeError"
            )

    def test_exit_reraise_of_turn_error_stays_quiet(self) -> None:
        scope, span = _entered_scope()
        try:
            raise RuntimeError("turn blew up")
        except RuntimeError as error:
            scope.__exit__.side_effect = error
            handle = TurnScope(scope=scope, span=span)
            with patch("app.services.laminar_service.log") as mock_log:
                end_turn(handle, output="boom", error=error)

                mock_log.warning.assert_not_called()

    def test_begin_failure_logs_conversation(self) -> None:
        with (
            patch("app.services.laminar_service.settings", _settings("key-1")),
            patch("app.services.laminar_service.Laminar") as mock_sdk,
            patch("app.services.laminar_service.log") as mock_log,
        ):
            mock_sdk.start_as_current_span.side_effect = RuntimeError("boom")

            assert begin_turn(user_id="u1", conversation_id="c1") is None
            mock_log.warning.assert_called_once_with(
                "laminar_begin_failed",
                error="boom",
                error_type="RuntimeError",
                conversation_id="c1",
            )
