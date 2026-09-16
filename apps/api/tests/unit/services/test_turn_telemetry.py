"""Unit tests for the turn-telemetry fan-out mapping.

These run the real ``begin_turn_all``/``end_turn_all`` with the vendor
services faked one layer down, so the outcome mapping itself executes —
mocking the services here is the seam, not the thing under test.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import settings
from app.services import turn_telemetry
from app.services.turn_telemetry import TurnOutcome, TurnSpec, begin_turn_all, end_turn_all


@pytest.fixture
def services() -> MagicMock:
    with (
        patch("app.services.turn_telemetry.agnost_service") as mock_agnost,
        patch("app.services.turn_telemetry.latitude_service") as mock_latitude,
        patch("app.services.turn_telemetry.laminar_service") as mock_laminar,
    ):
        yield MagicMock(agnost=mock_agnost, latitude=mock_latitude, laminar=mock_laminar)


@pytest.fixture
def _reset_disabled_flag() -> Iterator[None]:
    previous = turn_telemetry._disabled_logged
    turn_telemetry._disabled_logged = False
    yield
    turn_telemetry._disabled_logged = previous


@pytest.mark.unit
class TestOutcomeValues:
    def test_three_distinct_outcomes(self) -> None:
        assert {TurnOutcome.SUCCESS, TurnOutcome.CANCELLED, TurnOutcome.FAILED} == {
            TurnOutcome("success"),
            TurnOutcome("cancelled"),
            TurnOutcome("failed"),
        }


@pytest.mark.unit
class TestBeginFanOut:
    def test_carries_real_ids_input_and_uniform_properties(self, services: MagicMock) -> None:
        handles = begin_turn_all(
            TurnSpec(
                user_id="u1",
                conversation_id="c1",
                user_input="hello",
                source="web",
                mode="interactive",
                properties={"voice_mode": True},
            )
        )

        assert set(handles) == {"agnost", "latitude", "laminar"}
        assert handles["laminar"] is services.laminar.begin_turn.return_value

        expected_props = {
            "source": "web",
            "mode": "interactive",
            "tier": "comms_agent",
            "env": settings.ENV,
            "voice_mode": True,
        }
        agnost_kwargs = services.agnost.begin_turn.call_args.kwargs
        assert agnost_kwargs == {
            "user_id": "u1",
            "conversation_id": "c1",
            "user_input": "hello",
            "agent_name": "comms_agent",
            "properties": expected_props,
        }
        assert services.latitude.begin_turn.call_args.kwargs == {
            "user_id": "u1",
            "conversation_id": "c1",
            "agent_name": "comms_agent",
            "properties": expected_props,
        }
        assert services.laminar.begin_turn.call_args.kwargs == {
            "user_id": "u1",
            "conversation_id": "c1",
            "agent_name": "comms_agent",
            "user_input": "hello",
            "properties": expected_props,
        }

    def test_reserved_keys_win_over_caller_properties(self, services: MagicMock) -> None:
        begin_turn_all(
            TurnSpec(
                user_id="u1",
                conversation_id="c1",
                user_input="hello",
                source="web",
                mode="background",
                tier="narrator",
                properties={"source": "evil", "mode": "evil", "tier": "evil"},
            )
        )

        props = services.agnost.begin_turn.call_args.kwargs["properties"]
        assert props == {
            "source": "web",
            "mode": "background",
            "tier": "narrator",
            "env": settings.ENV,
        }

    def test_missing_source_defaults_to_background(self, services: MagicMock) -> None:
        begin_turn_all(TurnSpec(user_id="u1", conversation_id="c1", user_input="hello", mode="interactive"))

        props = services.agnost.begin_turn.call_args.kwargs["properties"]
        assert props == {
            "source": "background",
            "mode": "interactive",
            "tier": "comms_agent",
            "env": settings.ENV,
        }

    def test_empty_source_defaults_to_background(self, services: MagicMock) -> None:
        begin_turn_all(TurnSpec(user_id="u1", conversation_id="c1", user_input="hello", source="", mode="interactive"))

        props = services.agnost.begin_turn.call_args.kwargs["properties"]
        assert props["source"] == "background"

    def test_no_properties_leaves_only_reserved_keys(self, services: MagicMock) -> None:
        begin_turn_all(
            TurnSpec(
                user_id="u1",
                conversation_id="c1",
                user_input="hello",
                source="web",
                mode="m",
            )
        )

        props = services.agnost.begin_turn.call_args.kwargs["properties"]
        assert props == {"source": "web", "mode": "m", "tier": "comms_agent", "env": settings.ENV}

    def test_all_none_scopes_logs_once(
        self, services: MagicMock, _reset_disabled_flag: None
    ) -> None:
        services.agnost.begin_turn.return_value = None
        services.latitude.begin_turn.return_value = None
        services.laminar.begin_turn.return_value = None
        with patch("app.services.turn_telemetry.log") as mock_log:
            begin_turn_all(TurnSpec(user_id="u1", conversation_id="c1", user_input="hello", mode="interactive"))
            begin_turn_all(TurnSpec(user_id="u1", conversation_id="c1", user_input="hello", mode="interactive"))

            mock_log.info.assert_called_once_with(
                "turn_telemetry_no_scopes", reason="keys unset or all begins failed"
            )

    def test_partial_scopes_stay_silent(
        self, services: MagicMock, _reset_disabled_flag: None
    ) -> None:
        services.agnost.begin_turn.return_value = MagicMock()
        services.latitude.begin_turn.return_value = None
        services.laminar.begin_turn.return_value = None
        with patch("app.services.turn_telemetry.log") as mock_log:
            handles = begin_turn_all(
                TurnSpec(user_id="u1", conversation_id="c1", user_input="hello", mode="m")
            )

            assert handles["agnost"] is not None
            assert handles["latitude"] is None
            mock_log.info.assert_not_called()


@pytest.mark.unit
class TestEndFanOut:
    def test_success_is_clean_everywhere(self, services: MagicMock) -> None:
        handles = {
            "agnost": MagicMock(),
            "latitude": MagicMock(),
            "laminar": MagicMock(),
        }

        end_turn_all(handles, output="hi")  # type: ignore[typeddict-item]

        assert services.agnost.end_turn.call_args.args[0] is handles["agnost"]
        agnost_kwargs = services.agnost.end_turn.call_args.kwargs
        assert agnost_kwargs["output"] == "hi"
        assert agnost_kwargs["success"] is True
        assert agnost_kwargs["properties"] == {
            "cancelled": False,
            "has_error": False,
            "outcome": "success",
        }
        assert services.latitude.end_turn.call_args.args[0] is handles["latitude"]
        assert services.latitude.end_turn.call_args.kwargs == {
            "error": None,
            "cancelled": False,
        }
        assert services.laminar.end_turn.call_args.args[0] is handles["laminar"]
        laminar_kwargs = services.laminar.end_turn.call_args.kwargs
        assert laminar_kwargs["output"] == "hi"
        assert laminar_kwargs["error"] is None
        assert laminar_kwargs["cancelled"] is False

    def test_error_is_failed_with_same_exception(self, services: MagicMock) -> None:
        handles = {
            "agnost": MagicMock(),
            "latitude": MagicMock(),
            "laminar": MagicMock(),
        }
        error = RuntimeError("provider down")

        end_turn_all(handles, output="boom", error=error)

        agnost_kwargs = services.agnost.end_turn.call_args.kwargs
        assert agnost_kwargs["output"] == "boom"
        assert agnost_kwargs["success"] is False
        assert agnost_kwargs["properties"]["outcome"] == "failed"
        assert services.latitude.end_turn.call_args.args[0] is handles["latitude"]
        assert services.latitude.end_turn.call_args.kwargs["error"] is error
        assert services.laminar.end_turn.call_args.args[0] is handles["laminar"]
        assert services.laminar.end_turn.call_args.kwargs["error"] is error
        assert services.laminar.end_turn.call_args.kwargs["output"] == "boom"

    def test_cancelled_is_not_failed(self, services: MagicMock) -> None:
        handles = {
            "agnost": MagicMock(),
            "latitude": MagicMock(),
            "laminar": MagicMock(),
        }

        end_turn_all(handles, output="partial", cancelled=True)

        agnost_kwargs = services.agnost.end_turn.call_args.kwargs
        assert agnost_kwargs["output"] == "partial"
        assert agnost_kwargs["success"] is False
        assert agnost_kwargs["properties"] == {
            "cancelled": True,
            "has_error": False,
            "outcome": "cancelled",
        }
        assert services.latitude.end_turn.call_args.args[0] is handles["latitude"]
        assert services.latitude.end_turn.call_args.kwargs == {
            "error": None,
            "cancelled": True,
        }
        assert services.laminar.end_turn.call_args.args[0] is handles["laminar"]
        assert services.laminar.end_turn.call_args.kwargs["cancelled"] is True
        assert services.laminar.end_turn.call_args.kwargs["output"] == "partial"

    def test_error_dominates_cancelled(self, services: MagicMock) -> None:
        handles = {
            "agnost": MagicMock(),
            "latitude": MagicMock(),
            "laminar": MagicMock(),
        }
        error = RuntimeError("provider down")

        end_turn_all(handles, output="boom", error=error, cancelled=True)

        agnost_kwargs = services.agnost.end_turn.call_args.kwargs
        assert agnost_kwargs["properties"]["outcome"] == "failed"
        assert agnost_kwargs["properties"]["cancelled"] is False
        assert services.latitude.end_turn.call_args.kwargs["cancelled"] is False

    def test_none_handles_is_noop(self, services: MagicMock) -> None:
        end_turn_all(None, output="hi")

        services.agnost.end_turn.assert_not_called()
        services.latitude.end_turn.assert_not_called()
        services.laminar.end_turn.assert_not_called()
