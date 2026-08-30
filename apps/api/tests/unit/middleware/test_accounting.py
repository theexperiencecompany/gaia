"""LLM accounting middleware: usage extraction, cost, step index, HWM signal.

The middleware is the only place token spend is measured, so an arithmetic or
fallback mistake here is invisible until a bill arrives. Cost calculation is
stubbed (it is a pricing-table lookup, an external boundary); everything else
runs for real.
"""

from __future__ import annotations

from datetime import UTC, datetime
import time
from typing import Any, ClassVar, cast
from unittest.mock import AsyncMock, patch

from langchain.agents.middleware.types import AgentState, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.middleware import accounting
from app.agents.middleware.accounting import (
    LLMAccountingMiddleware,
    _latest_ai_message,
)
from app.config.rate_limits import (
    PRIMARY_METERED_FEATURE,
    RateLimitPeriod,
    get_daily_cost_budget_usd,
)
from app.constants.llm import (
    AGENT_RECURSION_LIMIT,
    BUDGET_WRAPUP_REMAINING_FRACTION,
    RECURSION_HWM_FRACTION,
)
from app.constants.log_tags import LogTag
from app.models.payment_models import PlanType
from app.services import llm_metering
from app.services.cost_budget import (
    BUDGET_WRAPUP_NOTICE,
    BudgetCheck,
    is_budget_wrapup_threshold,
)
from shared.py.wide_events import log

CONFIG: dict[str, Any] = {
    "configurable": {
        "thread_id": "conv-1",
        "lane": {"provider": "gemini", "model": "gemini-3-pro"},
        "user_id": "user-1",
    }
}


def _fixed_cost(
    *, model_name: str, input_tokens: int, output_tokens: int, cached_tokens: int
) -> dict[str, float]:
    """Stand-in for the pricing-table lookup: $0.001 per token, cached at half."""
    return {"total_cost": (input_tokens + output_tokens + cached_tokens / 2) / 1000}


def _ai(
    input_tokens: int = 100,
    output_tokens: int = 20,
    cached: int = 0,
    reasoning: int = 0,
    **kwargs: Any,
) -> AIMessage:
    return AIMessage(
        content="response",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cached},
            "output_token_details": {"reasoning": reasoning},
        },
        **kwargs,
    )


def _state(message: AIMessage) -> AgentState[Any]:
    return {"messages": [HumanMessage(content="ask"), message]}


def _accounting_env(config: dict[str, Any] = CONFIG):
    # Pricing + the budget write moved behind record_llm_call (llm_metering);
    # patch them there so these tests exercise the middleware against a fixed
    # price and no real Redis/Mongo.
    return (
        patch.object(accounting, "current_run_config", lambda: config),
        patch.object(llm_metering, "calculate_token_cost", _fixed_cost),
        patch.object(llm_metering, "record_model_call_usage", AsyncMock()),
    )


async def _call(
    mw: LLMAccountingMiddleware,
    message: AIMessage,
    config: dict[str, Any] = CONFIG,
) -> dict[str, Any]:
    """Drive one before/after model pair and return the emitted model context."""
    config_patch, cost_patch, usage_patch = _accounting_env(config)
    with config_patch, cost_patch, usage_patch:
        await mw.abefore_model({"messages": []}, None)
        await mw.aafter_model(_state(message), None)
    return dict(log.get().get("model") or {})


@pytest.fixture(autouse=True)
def _fresh_wide_event() -> None:
    log.reset()


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
        model = await _call(mw, _ai(input_tokens=100, output_tokens=20, cached=40, reasoning=5))
        assert model["input_tokens"] == 100 * step
        assert model["output_tokens"] == 20 * step
        assert model["cached_tokens"] == 40 * step
        # Reasoning tokens are billed as output; a total that fails to accumulate
        # under-reports what thinking cost across the run.
        assert model["reasoning_tokens"] == 5 * step
        assert model["tokens_used"] == 120 * step
        assert model["cost_usd"] == pytest.approx(0.14 * step)
        assert model["cache_hit_rate"] == 0.4


async def test_accumulation_survives_a_partially_populated_prior_context() -> None:
    log.set(model={"input_tokens": None, "cost_usd": None})
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=50, output_tokens=10))

    assert model["input_tokens"] == 50
    assert model["cost_usd"] == pytest.approx(0.06)


async def test_reasoning_tokens_are_reported_and_accumulate_across_steps() -> None:
    # Reasoning is a subset of output spend the provider bills for but does not
    # show the user; if it does not survive into the wide event, thinking-heavy
    # models look free in the rollups.
    mw = LLMAccountingMiddleware(agent_name="a")
    first = await _call(mw, _ai(output_tokens=40, reasoning=30))
    assert first["reasoning_tokens"] == 30

    second = await _call(mw, _ai(output_tokens=15, reasoning=11))
    assert second["reasoning_tokens"] == 41


async def test_cost_is_taken_from_the_pricing_table_and_charged_as_credits() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(input_tokens=100, output_tokens=20, cached=40))
    # _fixed_cost: (100 + 20 + 40/2) / 1000
    assert model["cost_usd"] == pytest.approx(0.14)
    assert model["credits_charged"] == pytest.approx(0.14)


async def test_cached_tokens_are_passed_to_the_pricing_call_not_discarded() -> None:
    seen: dict[str, Any] = {}

    def spy(**kwargs: Any) -> dict[str, float]:
        seen.update(kwargs)
        return {"total_cost": 1.0}

    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(llm_metering, "calculate_token_cost", spy),
        patch.object(llm_metering, "record_model_call_usage", AsyncMock()),
    ):
        await mw.aafter_model(_state(_ai(input_tokens=100, output_tokens=20, cached=40)), None)

    assert seen == {
        "model_name": "gemini-3-pro",
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
    }


async def test_a_pricing_failure_is_logged_and_charged_as_zero() -> None:
    def broken(**_kwargs: Any) -> dict[str, float]:
        raise RuntimeError("pricing table unavailable")

    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(llm_metering, "calculate_token_cost", broken),
        patch.object(llm_metering, "record_model_call_usage", AsyncMock()),
    ):
        await mw.aafter_model(_state(_ai()), None)

    model = log.get()["model"]
    assert model["cost_usd"] == 0.0
    # The usage itself must still be recorded — only the price is unknown.
    assert model["input_tokens"] == 100
    assert any("Token cost calc failed" in e["msg"] for e in log.get()["errors"])


async def test_a_turn_with_no_model_response_emits_nothing() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
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
    config_patch, cost_patch, usage_patch = _accounting_env()
    with config_patch, cost_patch, usage_patch:
        await mw.aafter_model(ObjectState(), cast(Any, None))

    assert log.get()["model"]["input_tokens"] == 7


async def test_unknown_model_and_provider_when_the_config_is_bare() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(), config={"configurable": {}})
    assert model["name"] == "unknown"
    assert model["provider"] == "unknown"


async def test_a_run_with_no_lane_reports_an_unknown_model_rather_than_guessing() -> None:
    """A bag written before lanes existed (in-flight queue item, stored HIL
    resume_item) has no lane. Accounting must say so, not invent a model name."""
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai(), config={"configurable": {"user_id": "u1"}})
    assert model["name"] == "unknown"
    assert model["provider"] == "unknown"


# --- handoff latency ---------------------------------------------------------- #


async def test_handoff_latency_is_the_gap_between_the_two_hooks_in_ms() -> None:
    clock = iter([10.0, 10.25])  # 250ms apart
    mw = LLMAccountingMiddleware(agent_name="a")
    config_patch, cost_patch, usage_patch = _accounting_env()
    with (
        config_patch,
        cost_patch,
        usage_patch,
        patch.object(time, "monotonic", lambda: next(clock)),
    ):
        await mw.abefore_model({"messages": []}, None)
        await mw.aafter_model(_state(_ai()), None)

    assert log.get()["model"]["handoff_latency_ms"] == 250.0


async def test_handoff_latency_is_zero_when_the_pre_hook_never_ran() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    config_patch, cost_patch, usage_patch = _accounting_env()
    with config_patch, cost_patch, usage_patch:
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


# --- budget wall / wrap-up notice --------------------------------------------- #


def _model_request(messages: list[Any] | None = None) -> ModelRequest:
    return ModelRequest(model=cast(Any, None), messages=messages or [HumanMessage(content="hi")])


def _recording_handler() -> tuple[list[ModelRequest], Any]:
    captured: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> ModelResponse:
        captured.append(request)
        return ModelResponse(result=[AIMessage(content="ok")])

    return captured, handler


def _has_wrapup_notice(request: ModelRequest) -> bool:
    return any(
        isinstance(m, HumanMessage) and m.content == BUDGET_WRAPUP_NOTICE for m in request.messages
    )


async def test_budget_wrapup_notice_injected_once_when_spend_crosses_threshold() -> None:
    budget = get_daily_cost_budget_usd(PlanType.FREE)
    spent = budget * (1 - BUDGET_WRAPUP_REMAINING_FRACTION)  # exactly at the threshold
    check = BudgetCheck(None, spent, PlanType.FREE)
    mw = LLMAccountingMiddleware(agent_name="a")
    captured, handler = _recording_handler()

    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", AsyncMock(return_value=check)),
    ):
        await mw.awrap_model_call(_model_request(), handler)
        await mw.awrap_model_call(_model_request(), handler)

    assert len(captured) == 2
    assert _has_wrapup_notice(captured[0])
    assert not _has_wrapup_notice(captured[1])  # already emitted for this thread

    notices = [w for w in log.get().get("warnings", []) if w.get("msg") == "budget_wrapup_notice"]
    assert notices == [
        {
            "msg": "budget_wrapup_notice",
            "event_name": "budget_wrapup_notice",
            "agent_name": "a",
            "user_id": "user-1",
            "thread_id": "conv-1",
            "spent": spent,
            "budget": budget,
        }
    ]


async def test_budget_wrapup_notice_not_injected_below_threshold() -> None:
    budget = get_daily_cost_budget_usd(PlanType.FREE)
    spent = budget * (1 - BUDGET_WRAPUP_REMAINING_FRACTION) - 0.0001  # just under
    check = BudgetCheck(None, spent, PlanType.FREE)
    mw = LLMAccountingMiddleware(agent_name="a")
    captured, handler = _recording_handler()

    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", AsyncMock(return_value=check)),
    ):
        await mw.awrap_model_call(_model_request(), handler)

    assert len(captured) == 1
    assert not _has_wrapup_notice(captured[0])
    assert "warnings" not in log.get() or not any(
        w.get("msg") == "budget_wrapup_notice" for w in log.get()["warnings"]
    )


async def test_hard_wall_stop_short_circuits_and_skips_the_wrapup_notice() -> None:
    # Spend is already past the hard wall (far above the wrap-up threshold too) —
    # the stop text must win and the handler must never run.
    check = BudgetCheck("You've reached today's usage limit.", 999.0, PlanType.FREE)
    mw = LLMAccountingMiddleware(agent_name="a")
    handler = AsyncMock()

    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", AsyncMock(return_value=check)),
    ):
        response = await mw.awrap_model_call(_model_request(), handler)

    handler.assert_not_called()
    assert response.result == [AIMessage(content="You've reached today's usage limit.")]
    assert not any(w.get("msg") == "budget_wrapup_notice" for w in log.get().get("warnings", []))


async def test_the_wall_is_checked_against_the_callers_user_plan_and_request_tree() -> None:
    # Every argument comes off the run's configurable. Reading the wrong bag
    # checks a budget that belongs to nobody, and the wall silently stops
    # binding for the user who is actually spending.
    seen: list[tuple[Any, ...]] = []

    async def spy(*args: Any) -> BudgetCheck:
        seen.append(args)
        return BudgetCheck(None, None, None)

    config = {
        "configurable": {
            "thread_id": "conv-1",
            "user_id": "user-1",
            "plan_type": "pro",
            "root_request_id": "req-9",
        }
    }
    mw = LLMAccountingMiddleware(agent_name="a")
    _captured, handler = _recording_handler()
    with (
        patch.object(accounting, "current_run_config", lambda: config),
        patch.object(accounting, "get_budget_stop_reason", spy),
    ):
        await mw.awrap_model_call(_model_request(), handler)

    assert seen == [("user-1", PlanType.PRO, "req-9")]


async def test_a_budget_check_failure_fails_open_and_still_runs_the_model() -> None:
    # Redis being down must not take the turn down with it — the model call goes
    # through unchanged and the failure is logged rather than swallowed.
    mw = LLMAccountingMiddleware(agent_name="a")
    captured, handler = _recording_handler()
    broken = AsyncMock(side_effect=RuntimeError("redis down"))

    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", broken),
    ):
        response = await mw.awrap_model_call(_model_request(), handler)

    assert len(captured) == 1
    assert not _has_wrapup_notice(captured[0])
    assert response.result == [AIMessage(content="ok")]
    assert any(
        w["msg"] == f"{LogTag.AGENT} Budget check failed (failing open)"
        for w in log.get().get("warnings", [])
    )


async def _run_stopped_call(check: BudgetCheck, reset_at: datetime) -> tuple[list[Any], list[Any]]:
    """Drive one stopped call; return the streamed frames and the reset periods asked for."""
    frames: list[Any] = []
    periods: list[Any] = []

    def _reset(period: Any) -> datetime:
        periods.append(period)
        return reset_at

    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", AsyncMock(return_value=check)),
        patch.object(accounting, "get_stream_writer", lambda: frames.append),
        patch.object(accounting, "get_reset_time", _reset),
    ):
        await mw.awrap_model_call(_model_request(), AsyncMock())
    return frames, periods


async def test_the_budget_stop_streams_a_rate_limit_card_a_free_user_can_act_on() -> None:
    # Without the card the frontend renders the bare stop sentence, with no
    # reset time and no way to upgrade — the stop reads as a broken chat.
    reset_at = datetime(2030, 1, 2, tzinfo=UTC)
    stop_reason = "You've reached today's usage limit."
    frames, periods = await _run_stopped_call(
        BudgetCheck(stop_reason, 999.0, PlanType.FREE), reset_at
    )

    assert periods == [RateLimitPeriod.DAY]  # the daily window, not the monthly one
    assert len(frames) == 1
    tool_data = frames[0]["tool_data"]
    assert tool_data["tool_name"] == "rate_limit_data"
    assert tool_data["data"] == {
        "feature": PRIMARY_METERED_FEATURE,
        "plan_required": "pro",
        "reset_time": reset_at.isoformat(),
        "current_plan": "free",
        "message": stop_reason,
    }


async def test_the_budget_stop_card_offers_a_paid_user_no_upgrade() -> None:
    frames, _periods = await _run_stopped_call(
        BudgetCheck("Daily cap reached.", 999.0, PlanType.PRO), datetime(2030, 1, 2, tzinfo=UTC)
    )

    data = frames[0]["tool_data"]["data"]
    assert data["plan_required"] is None
    assert data["current_plan"] == "pro"


async def test_a_missing_stream_writer_never_breaks_the_stop() -> None:
    # Workflows, bots and voice run with no stream to write to; the stop text
    # still has to come back.
    def _no_writer() -> Any:
        raise RuntimeError("no stream writer in this context")

    mw = LLMAccountingMiddleware(agent_name="a")
    check = BudgetCheck("Daily cap reached.", 999.0, PlanType.FREE)
    with (
        patch.object(accounting, "current_run_config", lambda: CONFIG),
        patch.object(accounting, "get_budget_stop_reason", AsyncMock(return_value=check)),
        patch.object(accounting, "get_stream_writer", _no_writer),
    ):
        response = await mw.awrap_model_call(_model_request(), AsyncMock())

    assert response.result == [AIMessage(content="Daily cap reached.")]


def test_a_plan_with_no_configured_budget_never_reaches_the_wrapup_threshold() -> None:
    # Both shipped plans carry a non-zero budget, so this guard is only
    # reachable through the config seam — but without it a budget of 0 makes
    # `spent >= 0` true from the very first request, and every run would be
    # told to wrap up before it had done anything.
    #
    # Lives here rather than beside is_budget_wrapup_threshold's own tests
    # because the mutation gate mutates cost_budget.py against THIS file:
    # scripts/ci/lib/mutation_matrix.py picks the alphabetically first test file
    # that references the module, and middleware/ sorts before services/.
    with patch("app.services.cost_budget.get_daily_cost_budget_usd", return_value=0.0):
        assert is_budget_wrapup_threshold(0.0, PlanType.FREE) is False
        assert is_budget_wrapup_threshold(5.0, PlanType.FREE) is False


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
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        assert mw.before_model({"messages": []}, None) is None
    assert "conv-1" in mw._start_ts


def test_sync_post_hook_advances_the_step_and_emits_the_high_water_mark() -> None:
    limit = 5  # cap = 4
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        for _ in range(_hwm_cap(limit)):
            assert mw.after_model({"messages": []}, None) is None

    assert mw._step_counts["conv-1"] == _hwm_cap(limit)
    events = _hwm_events()
    assert len(events) == 1
    assert events[0]["step_index"] == _hwm_cap(limit)
    assert events[0]["recursion_limit"] == limit


def test_sync_post_hook_stays_silent_below_the_cap() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=10)
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)
    assert _hwm_events() == []


def test_a_tiny_recursion_limit_still_yields_a_usable_cap_on_the_sync_path() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=1)
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)

    events = _hwm_events()
    assert len(events) == 1
    assert events[0]["hwm_cap"] == 1


def test_sync_high_water_mark_is_emitted_only_once_per_thread() -> None:
    limit = 5
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=limit)
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        for _ in range(_hwm_cap(limit) + 4):
            mw.after_model({"messages": []}, None)
    assert len(_hwm_events()) == 1


def test_sync_and_async_paths_share_one_step_counter() -> None:
    mw = LLMAccountingMiddleware(agent_name="a", recursion_limit=10)
    with patch.object(accounting, "current_run_config", lambda: CONFIG):
        mw.after_model({"messages": []}, None)
        mw.after_model({"messages": []}, None)
    assert mw._step_counts["conv-1"] == 2


# --- the llm_call event itself ------------------------------------------------ #


async def test_the_llm_call_event_carries_the_per_step_attribution() -> None:
    # This event is per-step, not aggregated: it is what per-user, per-model cost
    # attribution is reconstructed from downstream.
    emitted: list[tuple[str, dict[str, Any]]] = []
    mw = LLMAccountingMiddleware(agent_name="executor_agent")
    config_patch, cost_patch, usage_patch = _accounting_env()
    with (
        config_patch,
        cost_patch,
        usage_patch,
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
        "reasoning_tokens": 0,
        "cost_usd": pytest.approx(0.14),
        "cost_source": "table",
        "step_index": 1,
        "generation_id": None,
    }
    second = emitted[1][1]
    assert second["input_tokens"] == 7  # per step, not a running total
    assert second["step_index"] == 2


async def test_the_llm_call_event_says_whether_the_price_was_the_providers_or_ours() -> None:
    """``cost_usd`` alone cannot be audited: a table guess and a provider
    invoice look identical in the log. They disagree by more than 10x per
    upstream, so the event has to name which one it carries — that flag is what
    makes the coverage number in the true-cost backfill mean anything."""
    emitted: list[tuple[str, dict[str, Any]]] = []
    mw = LLMAccountingMiddleware(agent_name="executor_agent")
    priced = _ai(input_tokens=100, output_tokens=20)
    priced.response_metadata = {"cost": 0.0031}
    config_patch, cost_patch, usage_patch = _accounting_env()
    with (
        config_patch,
        cost_patch,
        usage_patch,
        patch.object(log, "info", lambda message, **kw: emitted.append((message, kw))),
    ):
        await mw.aafter_model(_state(priced), None)
        # No reported price: the pricing table answers instead, and _fixed_cost
        # gives it a figure nothing could confuse with 0.0031.
        await mw.aafter_model(_state(_ai(input_tokens=100, output_tokens=20)), None)

    assert emitted[0][1]["cost_source"] == "provider"
    assert emitted[0][1]["cost_usd"] == pytest.approx(0.0031)
    assert emitted[1][1]["cost_source"] == "table"
    assert emitted[1][1]["cost_usd"] == pytest.approx(0.12)


async def test_the_llm_call_event_carries_the_upstream_generation_id() -> None:
    # `model` above is the lane's CONFIGURED provider, which is always the
    # aggregator — it cannot say which upstream actually served the request. A
    # call reporting zero cached tokens is otherwise ambiguous between "routed to
    # a different upstream holding no warm prefix" and "the prefix broke", and
    # those have opposite fixes. This id resolves the serving provider without
    # spending a model call.
    emitted: list[tuple[str, dict[str, Any]]] = []
    mw = LLMAccountingMiddleware(agent_name="comms_agent")
    config_patch, cost_patch, usage_patch = _accounting_env()
    ai_message = _ai(input_tokens=100, output_tokens=20, cached=40)
    ai_message.response_metadata = {"id": "gen-xyz789"}
    with (
        config_patch,
        cost_patch,
        usage_patch,
        patch.object(log, "info", lambda message, **kw: emitted.append((message, kw))),
    ):
        await mw.aafter_model(_state(ai_message), None)

    assert emitted[0][1]["generation_id"] == "gen-xyz789"


# --- the lane the call is priced against -------------------------------------- #


async def test_the_price_is_looked_up_for_the_lanes_model_and_provider() -> None:
    mw = LLMAccountingMiddleware(agent_name="a")
    model = await _call(mw, _ai())

    assert model["name"] == "gemini-3-pro"
    assert model["provider"] == "gemini"


async def test_a_bag_with_no_lane_says_so_instead_of_undercharging_silently() -> None:
    """Priced as "unknown", which matches no pricing entry, so the call
    undercharges the budget. Any bag written before lanes existed — an in-flight
    queue item, a stored HIL resume_item — lands here for a deploy window, and the
    warning is the only thing that makes the under-billing visible."""
    warned: list[tuple[str, dict[str, Any]]] = []
    config = {"configurable": {"thread_id": "conv-1", "user_id": "user-1"}}
    config_patch, cost_patch, usage_patch = _accounting_env(config)
    mw = LLMAccountingMiddleware(agent_name="executor_agent")
    with (
        config_patch,
        cost_patch,
        usage_patch,
        patch.object(log, "warning", lambda message, **kw: warned.append((message, kw))),
    ):
        await mw.aafter_model(_state(_ai()), None)

    assert len(warned) == 1
    assert warned[0][0] == (
        f"{LogTag.AGENT} No lane on the configurable — the call is priced as "
        "'unknown' and undercharges the budget (pre-lane queue item or HIL resume?)"
    )
    assert warned[0][1] == {"agent_name": "executor_agent", "thread_id": "conv-1"}
    priced = dict(log.get().get("model") or {})
    assert priced["name"] == "unknown"
    assert priced["provider"] == "unknown"


async def test_a_bag_that_does_carry_a_lane_warns_about_nothing() -> None:
    warned: list[str] = []
    config_patch, cost_patch, usage_patch = _accounting_env()
    mw = LLMAccountingMiddleware(agent_name="a")
    with (
        config_patch,
        cost_patch,
        usage_patch,
        patch.object(log, "warning", lambda message, **kw: warned.append(message)),
    ):
        await mw.aafter_model(_state(_ai()), None)

    assert warned == []
