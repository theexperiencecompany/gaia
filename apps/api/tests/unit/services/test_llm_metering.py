"""Unit tests for app/services/llm_metering.py — the one pricing + recording
seam both metering routes share.

Covers ``extract_message_usage`` (the AIMessage -> token counts read, including
every provider-shape fallback) and ``record_graph_model_call`` (the agent-graph
route: charges the budget and counts toward the request tree's ceiling).
"""

from typing import Any
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from app.constants.llm import UNKNOWN_MODEL_NAME
from app.models.agent_models import AgentConfigurable
from app.services.llm_metering import extract_message_usage, record_graph_model_call


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
        "model_name": "some/model",
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
async def test_model_field_is_read_when_model_name_is_absent(mock_record: AsyncMock) -> None:
    mock_record.return_value = 0.0

    await record_graph_model_call(_ai(), {"model": "legacy/id"}, agent_name="executor")

    assert mock_record.await_args.kwargs["model_name"] == "legacy/id"


@patch("app.services.llm_metering.record_llm_call", new_callable=AsyncMock)
async def test_missing_model_name_is_surfaced_loudly(mock_record: AsyncMock) -> None:
    """An unnamed model prices at DEFAULT_PRICING — ~11x the real rate — so it
    must never pass silently."""
    mock_record.return_value = 0.0

    with patch("app.services.llm_metering.log") as mock_log:
        await record_graph_model_call(_ai(), {}, agent_name="executor")

    mock_log.error.assert_called_once()
    assert mock_record.await_args.kwargs["model_name"] == UNKNOWN_MODEL_NAME
    assert mock_record.await_args.kwargs["user_id"] is None
