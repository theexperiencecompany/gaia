"""Extraction keeps every valid fact the model returns, through the real structured-output parse."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from langchain_core.messages import AIMessage
from pydantic import ValidationError
import pytest

from app.constants.memory import MemoryKind, MemoryShelfLife
from app.memory.extraction import extract_memories
from app.memory.schemas import ExtractedMemoryBatch
from tests.helpers import BindableToolsFakeModel, captured_wide_event

pytestmark = pytest.mark.unit

_CLIENT = "app.agents.llm.client"
_WHEN = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
_TRANSCRIPT = [
    {
        "role": "user",
        "content": "Nadia's birthday is March 12, and I need to book the venue by Friday",
    },
    {"role": "assistant", "content": "Noted."},
]


def _fact(content: str, *, kind: str, shelf_life: str) -> dict[str, Any]:
    return {
        "content": content,
        "kind": kind,
        "shelf_life": shelf_life,
        "category_path": "relationships",
        "importance": 0.8,
    }


async def _extract_from_reply(arguments: dict[str, Any]) -> ExtractedMemoryBatch:
    """Run extract_memories against a model whose one tool call carries these arguments."""
    reply = AIMessage(
        content="",
        tool_calls=[{"name": "ExtractedMemoryBatch", "args": arguments, "id": "call_1"}],
    )
    model = BindableToolsFakeModel(responses=[reply])
    with (
        patch(f"{_CLIENT}.aux_lane_available", return_value=True),
        patch(f"{_CLIENT}.memory_lane_available", return_value=False),
        patch(f"{_CLIENT}.resolve_model", return_value=model),
    ):
        return await extract_memories(
            _TRANSCRIPT,
            user_id="u1",
            user_name="Sam",
            folder_tree="relationships",
            recent_facts=[],
            current_date=_WHEN,
        )


@pytest.mark.regression
async def test_one_fact_with_a_shelf_life_value_as_its_kind_does_not_drop_the_batch() -> None:
    """Regression for GAIA-BACKEND-40J: kind='task' failed the whole batch and lost every fact."""
    batch = await _extract_from_reply(
        {
            "facts": [
                _fact(
                    "Sam's girlfriend Nadia's birthday is March 12.",
                    kind="fact",
                    shelf_life="durable",
                ),
                _fact("Sam must book the venue by Friday.", kind="task", shelf_life="task"),
            ],
            "episode_entries": ["Sam planned Nadia's birthday."],
        }
    )

    assert [fact.content for fact in batch.facts] == [
        "Sam's girlfriend Nadia's birthday is March 12."
    ]
    assert batch.facts[0].kind is MemoryKind.FACT
    assert batch.facts[0].shelf_life is MemoryShelfLife.DURABLE
    assert batch.episode_entries == ["Sam planned Nadia's birthday."]


@pytest.mark.regression
async def test_a_rejected_fact_is_counted_on_the_wide_event_with_its_reason() -> None:
    async with captured_wide_event() as event:
        await _extract_from_reply(
            {"facts": [_fact("Sam must book the venue by Friday.", kind="task", shelf_life="task")]}
        )

    (warning,) = event["warnings"]
    assert warning["msg"] == "memory_facts_rejected"
    assert (warning["rejected_count"], warning["kept_count"]) == (1, 0)
    assert warning["reasons"] == ["facts.0.kind: Input should be 'fact' or 'experience'"]


async def test_a_batch_with_only_valid_facts_rejects_nothing() -> None:
    async with captured_wide_event() as event:
        batch = await _extract_from_reply(
            {"facts": [_fact("Sam lives in Berlin.", kind="fact", shelf_life="durable")]}
        )

    assert [fact.content for fact in batch.facts] == ["Sam lives in Berlin."]
    assert not event.get("warnings")


async def test_a_malformed_batch_outside_the_facts_still_fails_the_extraction() -> None:
    """Only facts are validated one by one; a broken envelope is still a failed call, not an empty success."""
    async with captured_wide_event() as event:
        batch = await _extract_from_reply(
            {"facts": [], "agenda_updates": [{"item": "Book the venue", "resolved": "maybe"}]}
        )

    assert batch == ExtractedMemoryBatch()
    assert [error["msg"] for error in event["errors"]] == [
        "memory_llm_failed",
        "memory_extraction_failed",
    ]


def test_a_non_list_facts_value_is_validated_as_a_whole() -> None:
    fact = _fact("Sam lives in Berlin.", kind="fact", shelf_life="durable")

    assert ExtractedMemoryBatch.model_validate({"facts": (fact,)}).facts[0].content == (
        "Sam lives in Berlin."
    )
    with pytest.raises(ValidationError) as error:
        ExtractedMemoryBatch.model_validate({"facts": "Sam lives in Berlin."})
    assert [detail["loc"] for detail in error.value.errors()] == [("facts",)]


async def test_a_mixed_batch_counts_the_rejected_and_kept_facts_apart() -> None:
    async with captured_wide_event() as event:
        batch = await _extract_from_reply(
            {
                "facts": [
                    _fact("Sam lives in Berlin.", kind="fact", shelf_life="durable"),
                    "Sam must book the venue by Friday.",
                ]
            }
        )

    assert [fact.content for fact in batch.facts] == ["Sam lives in Berlin."]
    (warning,) = event["warnings"]
    assert (warning["rejected_count"], warning["kept_count"]) == (1, 1)
    assert warning["reasons"] == [
        "facts.1: Input should be a valid dictionary or instance of ExtractedFact"
    ]
