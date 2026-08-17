"""Unit tests for app/services/llm_metering.py — the one pricing + recording
seam both metering routes share.

Covers ``extract_message_usage`` (the AIMessage -> token counts read, including
every provider-shape fallback), ``record_graph_model_call`` (the agent-graph
route: charges the budget and counts toward the request tree's ceiling), and
``record_llm_call`` itself (the funnel both routes price through).
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.constants.llm import UNKNOWN_MODEL_NAME
from app.models.agent_models import AgentConfigurable
from app.services.llm_metering import (
    extract_message_usage,
    record_graph_model_call,
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


# --- record_graph_model_call -------------------------------------------------- #


@patch("app.services.llm_metering.record_llm_call", new_callable=AsyncMock)
async def test_graph_spend_charges_the_budget_and_the_request_tree(
    mock_record: AsyncMock,
) -> None:
    mock_record.return_value = 0.004
    configurable: AgentConfigurable = {
        "user_id": "u1",
        # The RUN'S LANE is what the call is priced against — the same object
        # the request was bound from, so metering can never disagree with what
        # actually ran.
        "lane": {"provider": "openrouter", "model": "some/model"},
        "root_request_id": "req-1",
    }

    usage, cost = await record_graph_model_call(
        _ai(input_tokens=1_000, output_tokens=50, cached=800), configurable, agent_name="comms"
    )

    assert cost == 0.004
    assert usage == {
        "input_tokens": 1_000,
        "output_tokens": 50,
        "cached_tokens": 800,
        "reasoning_tokens": 0,
    }
    mock_record.assert_awaited_once_with(
        user_id="u1",
        model_name="some/model",
        input_tokens=1_000,
        output_tokens=50,
        cached_tokens=800,
        reasoning_tokens=0,
        root_request_id="req-1",
        charge_to_budget=True,
    )


@patch("app.services.llm_metering.record_llm_call", new_callable=AsyncMock)
async def test_a_bag_with_no_lane_prices_as_unknown_rather_than_guessing(
    mock_record: AsyncMock,
) -> None:
    """LangChain's own binding keys are the lane's EXPANSION, not the decision,
    and a bag written before lanes existed (an in-flight queue item, a stored HIL
    resume) carries them without one. Reading them here would meter a call against
    a key nothing keeps in sync with the lane; ``unknown`` is loud instead."""
    mock_record.return_value = 0.0

    await record_graph_model_call(_ai(), {"model": "legacy/id"}, agent_name="executor")

    assert mock_record.await_args.kwargs["model_name"] == UNKNOWN_MODEL_NAME


@patch("app.services.llm_metering.record_llm_call", new_callable=AsyncMock)
async def test_missing_model_name_is_surfaced_loudly(mock_record: AsyncMock) -> None:
    """An unnamed model prices at DEFAULT_PRICING — ~11x the real rate — so it
    must never pass silently."""
    mock_record.return_value = 0.0

    # A populated configurable that simply lacks the model: the keys it DOES
    # carry are what tells whoever reads the error where the name went missing.
    configurable = {"provider": "openrouter", "thread_id": "t-1"}
    with patch("app.services.llm_metering.log") as mock_log:
        await record_graph_model_call(_ai(), configurable, agent_name="executor")

    mock_log.error.assert_called_once()
    message = mock_log.error.call_args.args[0]
    assert "model name missing from configurable" in message
    assert "mispriced" in message
    assert mock_log.error.call_args.kwargs == {
        "agent_name": "executor",
        "configurable_keys": ["provider", "thread_id"],
    }
    assert mock_record.await_args.kwargs["model_name"] == UNKNOWN_MODEL_NAME
    assert mock_record.await_args.kwargs["user_id"] is None


# --- record_llm_call ---------------------------------------------------------- #
#
# Reached only through the callers above and LLMAccountingMiddleware, all of
# which fill in every counter — so the funnel's own signature has never been
# exercised, and a wrong default silently mis-books real money.


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    new_callable=AsyncMock,
    return_value={"total_cost": 0.25},
)
async def test_the_priced_call_reaches_the_rollup_whole(
    _price: AsyncMock, usage: AsyncMock
) -> None:
    cost = await record_llm_call(
        user_id="u1",
        model_name="deepseek/deepseek-v4-flash",
        input_tokens=100,
        output_tokens=20,
        cached_tokens=40,
        reasoning_tokens=7,
        root_request_id="req-1",
        charge_to_budget=True,
    )

    assert cost == 0.25
    usage.assert_awaited_once_with(
        "u1",
        0.25,
        "req-1",
        input_tokens=100,
        output_tokens=20,
        cached_tokens=40,
        reasoning_tokens=7,
        charge_to_budget=True,
    )


@patch("app.services.llm_metering.record_model_call_usage", new_callable=AsyncMock)
@patch(
    "app.services.llm_metering.calculate_token_cost",
    new_callable=AsyncMock,
    return_value={"total_cost": 0.25},
)
async def test_an_unreported_reasoning_count_is_booked_as_none_of_it(
    _price: AsyncMock, usage: AsyncMock
) -> None:
    # Most providers report no reasoning tokens at all, and those callers omit
    # the argument. Defaulting to anything but zero would invent hidden-thinking
    # usage for every one of them.
    await record_llm_call(
        user_id="u1",
        model_name="deepseek/deepseek-v4-flash",
        input_tokens=100,
        output_tokens=20,
        charge_to_budget=False,
    )

    assert usage.await_args.kwargs["reasoning_tokens"] == 0
    assert usage.await_args.kwargs["cached_tokens"] == 0
