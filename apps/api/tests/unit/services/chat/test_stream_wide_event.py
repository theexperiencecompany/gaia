"""What a finished chat turn reports on its wide event (stream.py).

``_finalize_stream`` and ``_log_usage_summary`` write the turn's only
observability record — tool counts and names, token totals, cache hit rate. A
wrong key here reads as "that tool was never called" or "the turn used no
tokens" in Grafana, with nothing failing anywhere, so these tests run both
inside a real wide-event boundary and assert the emitted fields exactly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import session as sess
from app.services.chat import stream as chat_stream
from app.services.chat.stream import _finalize_stream, _log_usage_summary, _StreamState
from shared.py.wide_events import log
from tests.helpers import captured_wide_event


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


async def test_finalize_stream_reports_the_turn_s_tool_calls() -> None:
    """tool_calls_count/tool_types come out of ``state.tool_data["tool_data"]``,
    keyed by each entry's ``tool_name``."""
    state = _StreamState()
    state.saved = True
    state.complete_message = "done"
    state.tool_data = {
        "tool_data": [
            {"tool_name": "calendar_options", "data": {}},
            {"tool_name": "weather_data", "data": {}},
        ]
    }
    state.todo_progress_accumulated = {"executor": {}}

    with (
        patch.object(chat_stream, "stream_manager") as sm,
        patch.object(chat_stream, "flush_fs_metrics", return_value={}),
    ):
        sm.cleanup = AsyncMock()
        async with captured_wide_event() as event:
            await _finalize_stream("s1", MagicMock(), {"user_id": "u1"}, "conv-1", state, None)

    assert event["tool_calls_count"] == 2
    assert sorted(event["tool_types"]) == ["calendar_options", "weather_data"]
    assert event["todo_progress_sources"] == ["executor"]
    assert event["response_length"] == 4


async def test_finalize_stream_ignores_entries_without_a_tool_name() -> None:
    """Control for the ``"tool_name" in e`` guard: a nameless entry still counts
    as a call but contributes no type (an empty-string type would be a lie)."""
    state = _StreamState()
    state.saved = True
    state.tool_data = {"tool_data": [{"tool_name": "weather_data"}, {"data": {}}]}

    with (
        patch.object(chat_stream, "stream_manager") as sm,
        patch.object(chat_stream, "flush_fs_metrics", return_value={}),
    ):
        sm.cleanup = AsyncMock()
        async with captured_wide_event() as event:
            await _finalize_stream("s1", MagicMock(), {"user_id": "u1"}, "conv-1", state, None)

    assert event["tool_calls_count"] == 2
    assert event["tool_types"] == ["weather_data"]


async def test_log_usage_summary_totals_tokens_and_keeps_existing_model_fields() -> None:
    """The token block is merged INTO whatever ``model`` the turn already set —
    overwriting it would drop the model name the totals belong to."""
    state = _StreamState()
    state.complete_message = "hello"
    state.follow_up_actions = ["a", "b"]
    state.usage_metadata = {
        "claude-opus": {
            "input_tokens": 800,
            "output_tokens": 100,
            "input_token_details": {"cache_read": 200},
        },
        "claude-haiku": {"input_tokens": 200, "output_tokens": 50},
    }

    async with captured_wide_event() as event:
        log.set(model={"name": "claude-opus"})
        _log_usage_summary(state)

    assert event["model"] == {
        "name": "claude-opus",
        "tokens_used": 1150,
        "input_tokens": 1000,
        "output_tokens": 150,
        "cached_tokens": 200,
        "cache_hit_rate": 0.2,
    }
    assert event["response_length"] == 5
    assert event["follow_up_actions_count"] == 2
    assert event["is_cancelled"] is False


async def test_log_usage_summary_on_a_turn_with_no_model_calls() -> None:
    """A fresh state carries an empty usage map — the totals must be zeros, not
    a crash (this is the cancelled/errored turn)."""
    async with captured_wide_event() as event:
        _log_usage_summary(_StreamState())

    assert event["model"] == {
        "tokens_used": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "cache_hit_rate": 0.0,
    }
