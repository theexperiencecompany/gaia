"""Unit tests for app/services/llm_metering.py — the one pricing + recording
seam both metering routes share.

Covers ``extract_message_usage`` (the AIMessage -> token counts read, including
every provider-shape fallback), ``extract_message_model`` (the model the
provider says served the call), and ``record_llm_call`` itself (the funnel every
metering route prices through).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage

from app.constants.llm import UNKNOWN_MODEL_NAME
from app.db.repositories.usage_daily import UsageDailyIncrement
from app.services.llm_metering import (
    TokenUsage,
    extract_generation_id,
    extract_message_cost,
    extract_message_model,
    extract_message_usage,
    record_llm_call,
)


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


# --- extract_message_usage ---------------------------------------------------- #


def test_canonical_usage_metadata_is_read_verbatim() -> None:
    assert extract_message_usage(_ai(input_tokens=100, output_tokens=20, cached=40)) == {
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 40,
        "reasoning_tokens": 0,
    }


def test_message_without_any_usage_reports_zeros() -> None:
    assert extract_message_usage(AIMessage(content="x")) == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
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
    assert extract_message_usage(message) == {
        "input_tokens": 500,
        "output_tokens": 70,
        "cached_tokens": 200,
        "reasoning_tokens": 0,
    }


def test_langchain_normalised_keys_in_response_metadata_are_accepted() -> None:
    message = AIMessage(
        content="x",
        response_metadata={"usage_metadata": {"input_tokens": 11, "output_tokens": 3}},
    )
    assert extract_message_usage(message) == {
        "input_tokens": 11,
        "output_tokens": 3,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }


def test_reasoning_tokens_are_read_from_output_token_details() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "output_token_details": {"reasoning": 30},
        },
    )
    assert extract_message_usage(message)["reasoning_tokens"] == 30


def test_missing_output_token_details_does_not_raise() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    )
    assert extract_message_usage(message)["reasoning_tokens"] == 0


def test_output_tokens_fall_back_even_when_input_tokens_are_present() -> None:
    # Regression: the output fallback used to be nested inside the "no input
    # tokens" branch, so a message reporting only its input count silently
    # billed zero output tokens.
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
        response_metadata={"usage_metadata": {"candidates_token_count": 70}},
    )
    assert extract_message_usage(message)["output_tokens"] == 70


def test_input_tokens_fall_back_even_when_output_tokens_are_present() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 0, "output_tokens": 20, "total_tokens": 20},
        response_metadata={"usage_metadata": {"prompt_token_count": 640}},
    )
    assert extract_message_usage(message)["input_tokens"] == 640


def test_cached_tokens_fall_back_to_the_provider_specific_key() -> None:
    message = _ai(cached=0)
    message.response_metadata = {"usage_metadata": {"cached_content_token_count": 33}}
    assert extract_message_usage(message)["cached_tokens"] == 33


def test_canonical_cache_read_wins_over_the_provider_specific_key() -> None:
    message = _ai(cached=40)
    message.response_metadata = {"usage_metadata": {"cached_content_token_count": 999}}
    assert extract_message_usage(message)["cached_tokens"] == 40


def test_missing_input_token_details_does_not_raise() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
    )
    assert extract_message_usage(message)["cached_tokens"] == 0


# --- extract_message_model ----------------------------------------------------- #


def test_the_model_is_read_from_what_the_provider_reported() -> None:
    """The response is the only account of what actually RAN. A provider that
    fell back serves a different model than the lane asked for, and the spend
    belongs to the one that answered."""
    message = AIMessage(content="hi", response_metadata={"model_name": "served/model"})

    assert extract_message_model(message) == "served/model"


def test_a_response_with_no_model_is_unknown_rather_than_guessed() -> None:
    """``unknown`` prices at DEFAULT_PRICING instead of a real rate, so the
    metering seams log it loudly; silently substituting a plausible default
    would hide the miss."""
    assert extract_message_model(AIMessage(content="hi")) == UNKNOWN_MODEL_NAME
    assert extract_message_model(AIMessage(content="hi", response_metadata={})) == (
        UNKNOWN_MODEL_NAME
    )
    assert (
        extract_message_model(AIMessage(content="hi", response_metadata={"model_name": ""}))
        == UNKNOWN_MODEL_NAME
    )


# --- record_llm_call ---------------------------------------------------------- #
#
# Reached only through the callers above and LLMAccountingMiddleware, all of
# which fill in every counter — so the funnel's own signature has never been
# exercised, and a wrong default silently mis-books real money.


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    return_value={"total_cost": 0.25},
)
async def test_the_priced_call_reaches_the_rollup_whole(
    _price: MagicMock, usage: AsyncMock
) -> None:
    cost = await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=40, reasoning_tokens=7),
        model_name="deepseek/deepseek-v4-flash",
        root_request_id="req-1",
        charge_to_budget=True,
    )

    assert cost == 0.25
    usage.assert_awaited_once_with(
        "u1",
        UsageDailyIncrement(
            cost=0.25, input_tokens=100, output_tokens=20, cached_tokens=40, reasoning_tokens=7
        ),
        "req-1",
        charge_to_budget=True,
    )


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    return_value={"total_cost": 0.25},
)
async def test_an_unreported_reasoning_count_is_booked_as_none_of_it(
    _price: MagicMock, usage: AsyncMock
) -> None:
    # Most providers report no reasoning tokens at all, and those callers omit
    # the argument. Defaulting to anything but zero would invent hidden-thinking
    # usage for every one of them.
    await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=0, reasoning_tokens=0),
        model_name="deepseek/deepseek-v4-flash",
        charge_to_budget=False,
    )

    assert usage.await_args.args[1].reasoning_tokens == 0
    assert usage.await_args.args[1].cached_tokens == 0


# --- extract_generation_id ------------------------------------------------------ #


def test_the_generation_id_is_read_from_the_response() -> None:
    """The id is the only handle on WHICH UPSTREAM served the call: ChatOpenRouter
    keeps the aggregator's own name (``model_provider="openrouter"``) and drops the
    upstream's ``provider`` field, and this id resolves to the serving upstream
    through the generation-metadata endpoint without spending a model call."""
    message = AIMessage(content="hi", response_metadata={"id": "gen-abc123"})

    assert extract_generation_id(message) == "gen-abc123"


def test_a_response_with_no_generation_id_is_none_rather_than_empty() -> None:
    """``None`` drops the key from the wide event; an empty string would land in
    the logs as a real-looking id that resolves to nothing."""
    assert extract_generation_id(AIMessage(content="hi")) is None
    assert extract_generation_id(AIMessage(content="hi", response_metadata={})) is None
    assert extract_generation_id(AIMessage(content="hi", response_metadata={"id": ""})) is None


# --- the price the provider reported ------------------------------------------ #
#
# MODEL_PRICING holds ONE rate per model, but OpenRouter routes each call to
# whichever upstream is free and the pool for a single model id spans
# 0.030-0.440 USD per million input tokens. Pricing from the table mis-states
# every call; measured across 1,486 calls it under-stated real spend by 44%.
# So when the provider says what it charged, that figure has to win.


def test_the_reported_price_is_read_from_the_response() -> None:
    assert (
        extract_message_cost(AIMessage(content="hi", response_metadata={"cost": 0.0037})) == 0.0037
    )


def test_a_reported_price_of_zero_is_a_real_answer_not_a_missing_one() -> None:
    # Free and promotional routes exist. Returning None here would send the
    # caller back to the pricing table and invent a charge that never happened.
    assert extract_message_cost(AIMessage(content="hi", response_metadata={"cost": 0})) == 0.0


def test_a_response_with_no_price_reports_none_so_the_table_is_used() -> None:
    assert extract_message_cost(AIMessage(content="hi")) is None
    assert extract_message_cost(AIMessage(content="hi", response_metadata={})) is None


def test_an_unparseable_price_falls_back_rather_than_raising() -> None:
    assert extract_message_cost(AIMessage(content="hi", response_metadata={"cost": "n/a"})) is None


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    return_value={"total_cost": 0.25},
)
async def test_the_provider_price_wins_over_the_table(price: MagicMock, usage: AsyncMock) -> None:
    cost = await record_llm_call(
        user_id="u1",
        usage=TokenUsage(
            input_tokens=73_093, output_tokens=390, cached_tokens=0, reasoning_tokens=0
        ),
        model_name="deepseek/deepseek-v4-flash",
        charge_to_budget=True,
        provider_cost=0.0037,
    )

    assert cost == 0.0037
    price.assert_not_called()
    assert usage.await_args is not None
    assert usage.await_args.args[1].cost == 0.0037


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    return_value={"total_cost": 0.25},
)
async def test_a_free_call_is_booked_as_free_not_repriced(
    price: MagicMock, usage: AsyncMock
) -> None:
    cost = await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=0, reasoning_tokens=0),
        model_name="deepseek/deepseek-v4-flash",
        charge_to_budget=False,
        provider_cost=0.0,
    )

    assert cost == 0.0
    price.assert_not_called()
    assert usage.await_args is not None
    assert usage.await_args.args[1].cost == 0.0


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    return_value={"total_cost": 0.25},
)
async def test_a_lane_that_reports_no_price_still_uses_the_table(
    price: MagicMock, usage: AsyncMock
) -> None:
    # Direct Gemini and the sim lane never report a price; they must keep
    # working exactly as before.
    cost = await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=0, reasoning_tokens=0),
        model_name="gemini-3.1-flash-lite",
        charge_to_budget=True,
        provider_cost=None,
    )

    assert cost == 0.25
    price.assert_called_once()
    assert usage.await_args is not None
    assert usage.await_args.args[1].cost == 0.25


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch("app.services.llm_metering.calculate_token_cost", return_value={"total_cost": 0.25})
async def test_the_provider_priced_path_records_against_the_same_call_as_the_table_one(
    price: MagicMock, usage: AsyncMock
) -> None:
    """Only the dollar figure differs between the two paths. Who the spend is
    booked to, which request tree it belongs to, and whether it counts against
    the allowance are the same facts either way — dropping any of them books
    real money to nobody, or bills background work to a user's budget."""
    await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=0, reasoning_tokens=0),
        model_name="deepseek/deepseek-v4-flash",
        root_request_id="req-42",
        charge_to_budget=False,
        provider_cost=0.0037,
    )

    price.assert_not_called()
    assert usage.await_args is not None
    assert usage.await_args.args[0] == "u1"
    assert usage.await_args.args[2] == "req-42"
    assert usage.await_args.kwargs["charge_to_budget"] is False


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch("app.services.llm_metering.calculate_token_cost", return_value={"total_cost": 0.25})
async def test_the_provider_priced_path_charges_the_budget_when_the_caller_says_so(
    price: MagicMock, usage: AsyncMock
) -> None:
    await record_llm_call(
        user_id="u1",
        usage=TokenUsage(input_tokens=100, output_tokens=20, cached_tokens=0, reasoning_tokens=0),
        model_name="deepseek/deepseek-v4-flash",
        charge_to_budget=True,
        provider_cost=0.0037,
    )

    assert usage.await_args is not None
    assert usage.await_args.kwargs["charge_to_budget"] is True
