"""LLM accounting middleware: usage extraction, cost, step index, HWM signal.

The middleware is the only place token spend is measured, so an arithmetic or
fallback mistake here is invisible until a bill arrives. Cost calculation is
stubbed (it is a pricing-table lookup, an external boundary); everything else
runs for real.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar, cast
from unittest.mock import patch

from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.middleware import accounting
from app.agents.middleware.accounting import (
    LLMAccountingMiddleware,
    _current_config,
    _extract_usage,
    _latest_ai_message,
)
from app.constants.llm import AGENT_RECURSION_LIMIT, RECURSION_HWM_FRACTION
from shared.py.wide_events import log

pytestmark = pytest.mark.unit


CONFIG: dict[str, Any] = {
    "configurable": {
        "thread_id": "conv-1",
        "model_name": "gemini-3-pro",
        "provider": "gemini",
        "user_id": "user-1",
    }
}


async def _fixed_cost(
    *, model_name: str, input_tokens: int, output_tokens: int, cached_tokens: int
) -> dict[str, float]:
    """Stand-in for the pricing-table lookup: $0.001 per token, cached at half."""
    return {"total_cost": (input_tokens + output_tokens + cached_tokens / 2) / 1000}


def _ai(
    input_tokens: int = 100,
    output_tokens: int = 20,
    cached: int = 0,
    **kwargs: Any,
) -> AIMessage:
    return AIMessage(
        content="response",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cached},
        },
        **kwargs,
    )


def _state(message: AIMessage) -> AgentState[Any]:
    return {"messages": [HumanMessage(content="ask"), message]}


def _accounting_env(config: dict[str, Any] = CONFIG):
    return (
        patch.object(accounting, "_current_config", lambda: config),
        patch.object(accounting, "calculate_token_cost", _fixed_cost),
    )


async def _call(
    mw: LLMAccountingMiddleware,
    message: AIMessage,
    config: dict[str, Any] = CONFIG,
) -> dict[str, Any]:
    """Drive one before/after model pair and return the emitted model context."""
    config_patch, cost_patch = _accounting_env(config)
    with config_patch, cost_patch:
        await mw.abefore_model({"messages": []}, None)
        await mw.aafter_model(_state(message), None)
    return dict(log.get().get("model") or {})


@pytest.fixture(autouse=True)
def _fresh_wide_event() -> None:
    log.reset()


# --- _extract_usage ----------------------------------------------------------- #


def test_canonical_usage_metadata_is_read_verbatim() -> None:
    assert _extract_usage(_ai(input_tokens=100, output_tokens=20, cached=40)) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
    }


def test_message_without_any_usage_reports_zeros() -> None:
    assert _extract_usage(AIMessage(content="x")) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
    }


def test_provider_native_response_metadata_is_used_when_usage_metadata_is_absent() -> None:
    message = AIMessage(
        content="x",
        response_metadata={
            "usage_metadata": {
                "prompt_token_count": 500,
                "candidates_token_count": 70,
                "cached_content_token_count": 200,
            }
        },
    )
    assert _extract_usage(message) == {
        "input_tokens": 500,
        "output_tokens": 70,
        "cached_tokens": 200,
    }


def test_langchain_normalised_keys_in_response_metadata_are_accepted() -> None:
    message = AIMessage(
        content="x",
        response_metadata={"usage_metadata": {"input_tokens": 11, "output_tokens": 3}},
    )
    assert _extract_usage(message) == {
        "input_tokens": 11,
        "output_tokens": 3,
        "cached_tokens": 0,
    }


def test_output_tokens_fall_back_even_when_input_tokens_are_present() -> None:
    # Regression: the output fallback used to be nested inside the "no input
    # tokens" branch, so a message reporting only its input count silently
    # billed zero output tokens.
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
        response_metadata={"usage_metadata": {"candidates_token_count": 70}},
    )
    assert _extract_usage(message)["output_tokens"] == 70


def test_input_tokens_fall_back_even_when_output_tokens_are_present() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 0, "output_tokens": 20, "total_tokens": 20},
        response_metadata={"usage_metadata": {"prompt_token_count": 640}},
    )
    assert _extract_usage(message)["input_tokens"] == 640


def test_cached_tokens_fall_back_to_the_provider_specific_key() -> None:
    message = _ai(cached=0)
    message.response_metadata = {"usage_metadata": {"cached_content_token_count": 33}}
    assert _extract_usage(message)["cached_tokens"] == 33


def test_canonical_cache_read_wins_over_the_provider_specific_key() -> None:
    message = _ai(cached=40)
    message.response_metadata = {"usage_metadata": {"cached_content_token_count": 999}}
    assert _extract_usage(message)["cached_tokens"] == 40


def test_missing_input_token_details_does_not_raise() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    )
    assert _extract_usage(message)["cached_tokens"] == 0


# --- _latest_ai_message ------------------------------------------------------- #


def test_latest_ai_message_picks_the_most_recent_one() -> None:
    messages = [AIMessage(content="first"), HumanMessage(content="h"), AIMessage(content="last")]
    picked = _latest_ai_message(messages)
    assert picked is not None and picked.content == "last"


def test_latest_ai_message_is_none_without_any_ai_message() -> None:
    assert _latest_ai_message([HumanMessage(content="h")]) is None


def test_latest_ai_message_tolerates_empty_and_none_histories() -> None:
    assert _latest_ai_message([]) is None
    assert _latest_ai_message(cast(Any, None)) is None


# --- _current_config ---------------------------------------------------------- #


def test_current_config_is_empty_outside_a_graph_run() -> None:
    assert _current_config() == {}


# --- the emitted model context ------------------------------------------------ #


async def test_model_context_carries_the_usage_and_identity_of_the_call() -> None:
    mw = LLMAccountingMiddleware(agent_name="comms_agent")
    model = await _call(mw, _ai(input_tokens=100, output_tokens=20, cached=40))

    assert model["name"] == "gemini-3-pro"
    assert model["provider"] == "gemini"
    assert model["agent_name"] == "comms_agent"
    assert model["input_tokens"] == 100
    assert model["output_tokens"] == 20
    assert model["cached_tokens"] == 40
    assert model["tokens_used"] == 120
    assert model["step_index"] == 1


async def test_cache_hit_rate_is_cached_over_input_tokens() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=200, output_tokens=10, cached=50))
    assert model["cache_hit_rate"] == 0.25


async def test_cache_hit_rate_is_zero_when_nothing_was_sent() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=0, output_tokens=0))
    assert model["cache_hit_rate"] == 0.0


async def test_successive_calls_add_up_within_one_wide_event_scope() -> None:
    # The middleware read-merges the previous totals out of the wide event before
    # re-setting them, so the numbers accumulate rather than each step clobbering
    # the last. NB: inside a compiled LangGraph graph this accumulation never
    # actually happens — each superstep runs in a child copy_context() frame, so
    # `log.get()` is empty every time. See the note in
    # `app/services/chat/stream.py::_log_usage_summary`, which is why the chat
    # rollup reads token totals from UsageMetadataCallback instead of from here.
    mw = LLMAccountingMiddleware(agent_name="a")
    for step in (1, 2, 3):
        model = await _call(mw, _ai(input_tokens=100, output_tokens=20, cached=40))
        assert model["input_tokens"] == 100 * step
        assert model["output_tokens"] == 20 * step
        assert model["cached_tokens"] == 40 * step
        assert model["tokens_used"] == 120 * step
        assert model["cost_usd"] == pytest.approx(0.14 * step)
        assert model["cache_hit_rate"] == 0.4


async def test_accumulation_survives_a_partially_populated_prior_context() -> None:
    log.set(model={"input_tokens": None, "cost_usd": None})
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=50, output_tokens=10))

    assert model["input_tokens"] == 50
    assert model["cost_usd"] == pytest.approx(0.06)


async def test_cost_is_taken_from_the_pricing_table_and_charged_as_credits() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=100, output_tokens=20, cached=40))
    # _fixed_cost: (100 + 20 + 40/2) / 1000
    assert model["cost_usd"] == pytest.approx(0.14)
    assert model["credits_charged"] == pytest.approx(0.14)


async def test_cached_tokens_are_passed_to_the_pricing_call_not_discarded() -> None:
    seen: dict[str, Any] = {}

    async def spy(**kwargs: Any) -> dict[str, float]:
        seen.update(kwargs)
        return {"total_cost": 1.0}

    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        patch.object(accounting, "_current_config", lambda: CONFIG),
        patch.object(accounting, "calculate_token_cost", spy),
    ):
        await mw.aafter_model(_state(_ai(input_tokens=100, output_tokens=20, cached=40)), None)

    assert seen == {
        "model_name": "gemini-3-pro",
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
    }


async def test_a_pricing_failure_is_logged_and_charged_as_zero() -> None:
    async def broken(**_kwargs: Any) -> dict[str, float]:
        raise RuntimeError("pricing table unavailable")

    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        patch.object(accounting, "_current_config", lambda: CONFIG),
        patch.object(accounting, "calculate_token_cost", broken),
    ):
        await mw.aafter_model(_state(_ai()), None)

    model = log.get()["model"]
    assert model["cost_usd"] == 0.0
    # The usage itself must still be recorded — only the price is unknown.
    assert model["input_tokens"] == 100
    assert any("Token cost calc failed" in w["msg"] for w in log.get()["warnings"])


async def test_a_turn_with_no_model_response_emits_nothing() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        assert (
            await mw.aafter_model(
                cast(AgentState[Any], {"messages": [HumanMessage(content="h")]}), None
            )
            is None
        )
    assert "model" not in log.get()


async def test_state_exposed_as_an_object_is_read_through_its_attribute() -> None:
    class ObjectState:
        messages: ClassVar[list[AIMessage]] = [_ai(input_tokens=7, output_tokens=3)]

    mw = LLMAccountingMiddleware(agent_name="a")
    config_patch, cost_patch = _accounting_env()
    with config_patch, cost_patch:
        await mw.aafter_model(ObjectState(), cast(Any, None))

    assert log.get()["model"]["input_tokens"] == 7


async def test_unknown_model_and_provider_when_the_config_is_bare() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(), config={"configurable": {}})
    assert model["name"] == "unknown"
    assert model["provider"] == "unknown"


async def test_legacy_model_key_is_accepted_when_model_name_is_absent() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(), config={"configurable": {"model": "gpt-legacy"}})
    assert model["name"] == "gpt-legacy"


# --- handoff latency ---------------------------------------------------------- #


async def test_handoff_latency_is_the_gap_between_the_two_hooks_in_ms() -> None:
    clock = iter([10.0, 10.25])  # 250ms apart
    mw = LLMAccountingMiddleware(agent_name="a")
    config_patch, cost_patch = _accounting_env()
    with config_patch, cost_patch, patch.object(time, "monotonic", lambda: next(clock)):
        await mw.abefore_model({"messages": []}, None)
        await mw.aafter_model(_state(_ai()), None)

    assert log.get()["model"]["handoff_latency_ms"] == 250.0


async def test_handoff_latency_is_zero_when_the_pre_hook_never_ran() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    config_patch, cost_patch = _accounting_env()
    with config_patch, cost_patch:
        await mw.aafter_model(_state(_ai()), None)
    assert log.get()["model"]["handoff_latency_ms"] == 0.0


async def test_the_start_timestamp_is_consumed_by_the_call_it_belongs_to() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    await _call(mw, _ai())
    assert "conv-1" not in mw._start_ts  # popped, not left to accumulate


# --- step index --------------------------------------------------------------- #


async def test_step_index_increments_once_per_model_call() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    for expected in (1, 2, 3):
        model = await _call(mw, _ai())
        assert model["step_index"] == expected


async def test_step_index_is_tracked_separately_per_thread() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    other = {"configurable": {"thread_id": "conv-2", "model_name": "m"}}
    await _call(mw, _ai())
    await _call(mw, _ai())
    model = await _call(mw, _ai(), config=other)

    assert model["step_index"] == 1
    assert mw._step_counts == {"conv-1": 2, "conv-2": 1}


def test_thread_id_falls_back_to_the_stream_id() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    assert mw._thread_id({"configurable": {"stream_id": "stream-9"}}) == "stream-9"


def test_thread_id_prefers_the_thread_over_the_stream() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    assert mw._thread_id({"configurable": {"thread_id": "t", "stream_id": "s"}}) == "t"


def test_thread_id_is_unknown_without_any_identifier() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    assert mw._thread_id({}) == "unknown"
    assert mw._thread_id({"configurable": None}) == "unknown"


# --- recursion high-water mark ------------------------------------------------ #


def _hwm_cap(recursion_limit: int) -> int:
    return max(1, int(recursion_limit * RECURSION_HWM_FRACTION))


def _hwm_events() -> list[dict[str, Any]]:
    return [w for w in log.get().get("warnings", []) if w.get("msg").startswith("recursion_high")]


async def test_no_high_water_mark_below_the_cap() -> None:
    limit = 10
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    for _ in range(_hwm_cap(limit) - 1):
        await _call(mw, _ai())
    assert _hwm_events() == []


async def test_high_water_mark_fires_on_reaching_the_cap() -> None:
    limit = 10
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    for _ in range(_hwm_cap(limit)):
        await _call(mw, _ai())

    events = _hwm_events()
    assert len(events) == 1
    assert events[0]["step_index"] == _hwm_cap(limit)
    assert events[0]["recursion_limit"] == limit
    assert events[0]["hwm_cap"] == _hwm_cap(limit)
    assert events[0]["agent_name"] == "a"
    assert events[0]["thread_id"] == "conv-1"
    assert events[0]["user_id"] == "user-1"


async def test_high_water_mark_is_emitted_only_once_per_thread() -> None:
    limit = 10
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    for _ in range(_hwm_cap(limit) + 4):
        await _call(mw, _ai())
    assert len(_hwm_events()) == 1


async def test_a_tiny_recursion_limit_still_yields_a_usable_cap() -> None:
    # int(1 * 0.8) is 0; the floor keeps the signal from firing on step zero.
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=1)
    assert _hwm_events() == []
    await _call(mw, _ai())
    assert len(_hwm_events()) == 1
    assert _hwm_events()[0]["hwm_cap"] == 1


def test_the_default_recursion_limit_is_the_shipped_constant() -> None:
    assert LLMAccountingMiddleware(agent_name="a").recursion_limit == AGENT_RECURSION_LIMIT


# --- synchronous fallbacks ---------------------------------------------------- #


def test_sync_pre_hook_records_the_start_timestamp() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        assert mw.before_model({"messages": []}, None) is None
    assert "conv-1" in mw._start_ts


def test_sync_post_hook_advances_the_step_and_emits_the_high_water_mark() -> None:
    limit = 5  # cap = 4
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        for _ in range(_hwm_cap(limit)):
            assert mw.after_model({"messages": []}, None) is None

    assert mw._step_counts["conv-1"] == _hwm_cap(limit)
    events = _hwm_events()
    assert len(events) == 1
    assert events[0]["step_index"] == _hwm_cap(limit)
    assert events[0]["recursion_limit"] == limit


def test_sync_post_hook_stays_silent_below_the_cap() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=10)
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)
    assert _hwm_events() == []


def test_a_tiny_recursion_limit_still_yields_a_usable_cap_on_the_sync_path() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=1)
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)

    events = _hwm_events()
    assert len(events) == 1
    assert events[0]["hwm_cap"] == 1


def test_sync_high_water_mark_is_emitted_only_once_per_thread() -> None:
    limit = 5
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        for _ in range(_hwm_cap(limit) + 4):
            mw.after_model({"messages": []}, None)
    assert len(_hwm_events()) == 1


def test_sync_and_async_paths_share_one_step_counter() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=10)
    with patch.object(accounting, "_current_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)
        mw.after_model({"messages": []}, None)
    assert mw._step_counts["conv-1"] == 2


# --- the llm_call event itself ------------------------------------------------ #


async def test_the_llm_call_event_carries_the_per_step_attribution() -> None:
    # This event is per-step, not aggregated: it is what per-user, per-model cost
    # attribution is reconstructed from downstream.
    emitted: list[tuple[str, dict[str, Any]]] = []
    mw = LLMAccountingMiddleware(agent_name="executor_agent")
    config_patch, cost_patch = _accounting_env()
    with (
        config_patch,
        cost_patch,
        patch.object(log, "info", lambda message, **kw: emitted.append((message, kw))),
    ):
        await mw.aafter_model(_state(_ai(input_tokens=100, output_tokens=20, cached=40)), None)
        await mw.aafter_model(_state(_ai(input_tokens=7, output_tokens=3)), None)

    assert [message for message, _ in emitted] == ["llm_call", "llm_call"]
    assert emitted[0][1] == {
        "llm_event": "llm_call",
        "agent_name": "executor_agent",
        "model": "gemini-3-pro",
        "thread_id": "conv-1",
        "user_id": "user-1",
        "input_tokens": 100,
        "cached_tokens": 40,
        "output_tokens": 20,
        "cost_usd": pytest.approx(0.14),
        "step_index": 1,
    }
    second = emitted[1][1]
    assert second["input_tokens"] == 7  # per step, not a running total
    assert second["step_index"] == 2
