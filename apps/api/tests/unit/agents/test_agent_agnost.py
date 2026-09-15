"""Turn telemetry on the silent agent path.

``call_agent_silent`` serves workflows, worker tasks, and maintenance sweeps —
every non-interactive turn. The fan-out must carry the real user id,
conversation id, and input, close with the real output, and a turn failure
must still raise to the caller after being recorded.
"""

import asyncio
from collections.abc import Iterator
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.agent import AgentRunOptions, call_agent_silent
from app.models.message_models import MessageRequestWithHistory


@pytest.fixture
def test_user() -> dict:
    return {"user_id": "user_abc", "email": "tester@example.com"}


@pytest.fixture
def body() -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message="Summarize inbox",
        messages=[{"role": "user", "content": "Summarize inbox"}],
    )


@contextlib.contextmanager
def _silent_agent(
    complete_message: str = "done reply", error: Exception | None = None
) -> Iterator[None]:
    """Stub graph setup/execution; optionally fail the execution."""
    graph = MagicMock()
    initial_state: dict = {}
    config: dict = {"configurable": {}}
    execute = (
        AsyncMock(side_effect=error)
        if error is not None
        else AsyncMock(return_value=(complete_message, {"tool_data": []}))
    )
    with (
        patch(
            "app.agents.core.agent._core_agent_logic",
            new=AsyncMock(return_value=(graph, initial_state, config)),
        ),
        patch("app.agents.core.agent.execute_graph_silent", new=execute),
        # PostHog capture is a separate seam with its own tests (see the
        # streaming telemetry tests for why the ambient provider registry
        # must not leak in here).
        patch("app.agents.core.agent.capture_event", new=MagicMock()),
    ):
        yield


@pytest.mark.unit
class TestSilentTelemetry:
    async def test_success_records_real_ids_input_output(self, test_user, body):
        with (
            patch("app.services.agnost_service.begin_turn") as mock_begin,
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
            _silent_agent("done reply"),
        ):
            result = await call_agent_silent(
                request=body,
                conversation_id="conv_bg_1",
                user=test_user,
                options=AgentRunOptions(source="cron"),
            )

        assert result.message == "done reply"
        begin_kwargs = mock_begin.call_args.kwargs
        assert begin_kwargs["user_id"] == "user_abc"
        assert begin_kwargs["conversation_id"] == "conv_bg_1"
        assert begin_kwargs["user_input"] == "Summarize inbox"
        assert begin_kwargs["properties"] == {
            "source": "cron",
            "mode": "background",
            "tier": "comms_agent",
        }

        assert mock_agnost_end.call_args.kwargs["output"] == "done reply"
        assert mock_agnost_end.call_args.kwargs["success"] is True
        assert mock_lat_end.call_args.kwargs["error"] is None
        assert mock_lam_end.call_args.kwargs["error"] is None

    async def test_empty_user_id_opens_turn_unattributed(self, body):
        with patch("app.agents.core.agent.begin_turn_all") as mock_begin_all:
            with _silent_agent("done reply"):
                await call_agent_silent(
                    request=body,
                    conversation_id="conv_bg_1",
                    user={"user_id": ""},
                )

        assert mock_begin_all.call_args.kwargs["user_id"] == ""

    async def test_failure_records_and_still_raises(self, test_user, body):
        with (
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            _silent_agent(error=RuntimeError("worker exploded")),
            pytest.raises(RuntimeError, match="worker exploded"),
        ):
            await call_agent_silent(
                request=body,
                conversation_id="conv_bg_1",
                user=test_user,
            )

        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["output"] == "worker exploded"
        lat_error = mock_lat_end.call_args.kwargs["error"]
        assert isinstance(lat_error, RuntimeError) and str(lat_error) == "worker exploded"

    async def test_cancel_records_and_still_raises(self, test_user, body):
        with (
            patch("app.services.agnost_service.end_turn") as mock_agnost_end,
            patch("app.services.latitude_service.end_turn") as mock_lat_end,
            patch("app.services.laminar_service.end_turn") as mock_lam_end,
            _silent_agent(error=asyncio.CancelledError("worker shutdown")),
            pytest.raises(asyncio.CancelledError),
        ):
            await call_agent_silent(
                request=body,
                conversation_id="conv_bg_1",
                user=test_user,
            )

        assert mock_agnost_end.call_args.kwargs["success"] is False
        assert mock_agnost_end.call_args.kwargs["output"] == ""
        assert mock_agnost_end.call_args.kwargs["properties"]["outcome"] == "cancelled"
        assert mock_lat_end.call_args.kwargs["error"] is None
        assert mock_lat_end.call_args.kwargs["cancelled"] is True
        assert mock_lam_end.call_args.kwargs["cancelled"] is True
