"""OpenAI Decisions transport for calibration runs (scripts/evals/core/openai_decisions.py).

httpx is mocked — the network boundary. The question translation and the answer
parsing are the production code under test and run for real.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.evals.core.openai_decisions import post_openai_decisions

from app.constants.providers import CredentialProviderName
from app.services.providers.provider_credentials_service import ProviderConfig

MODULE = "scripts.evals.core.openai_decisions"

CHOICE_QUESTION: dict[str, object] = {
    "type": "choice",
    "instructions": "Which describes it?",
    "criteria": {"authorized": "asked for", "unclear": "anything else"},
}
NOUL_QUESTION: dict[str, object] = {
    "type": "noul",
    "instructions": "Is it contained?",
    "criteria": {"true": "stays with the user", "false": "reaches others"},
}


@contextmanager
def _serving(body: dict[str, Any]) -> Iterator[AsyncMock]:
    response = MagicMock()
    response.json.return_value = body
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.return_value = response

    async def resolve(provider: str) -> ProviderConfig | None:
        return (
            ProviderConfig(api_key="oa-key") if provider == CredentialProviderName.OPENAI else None
        )

    with (
        patch(f"{MODULE}.httpx.AsyncClient", return_value=client),
        patch(f"{MODULE}.resolve", AsyncMock(side_effect=resolve)),
    ):
        yield client


async def test_a_noul_is_asked_as_a_predicate_stating_both_sides() -> None:
    body = {"answers": [{"type": "predicate", "name": "contained", "probability": 0.9}]}
    with _serving(body) as client:
        await post_openai_decisions({"a": 1}, {"contained": NOUL_QUESTION})

    [question] = client.post.await_args.kwargs["json"]["questions"]
    assert question == {
        "name": "contained",
        "type": "predicate",
        "instructions": (
            "Is it contained?\nTrue when: stays with the user\nFalse when: reaches others"
        ),
    }


async def test_a_choice_keeps_each_option_and_its_criterion() -> None:
    body = {"answers": [{"type": "choice", "name": "decision", "choice": "unclear"}]}
    with _serving(body) as client:
        await post_openai_decisions({"a": 1}, {"decision": CHOICE_QUESTION})

    [question] = client.post.await_args.kwargs["json"]["questions"]
    assert question["choices"] == [
        {"value": "authorized", "description": "asked for"},
        {"value": "unclear", "description": "anything else"},
    ]


async def test_answers_come_back_keyed_by_question_with_their_distribution() -> None:
    body = {
        "answers": [
            {
                "type": "choice",
                "name": "decision",
                "choice": "authorized",
                "confidence": 0.7,
                "probabilities": [
                    {"value": "authorized", "probability": 0.8},
                    {"value": "unclear", "probability": 0.2},
                ],
            },
            {"type": "predicate", "name": "contained", "probability": 0.95},
        ],
        "usage": {"input_tokens": 120, "output_tokens": 0},
    }
    with _serving(body):
        result = await post_openai_decisions(
            {"a": 1}, {"decision": CHOICE_QUESTION, "contained": NOUL_QUESTION}
        )

    answer = result.choice("decision", ("authorized", "unclear"))
    assert (answer.choice, answer.confidence) == ("authorized", 0.7)
    assert answer.probabilities == {"authorized": 0.8, "unclear": 0.2}
    assert result.noul("contained") == 0.95
    assert result.tokens() == (120, 0)


async def test_a_refused_question_raises_rather_than_reading_as_an_answer() -> None:
    body = {"answers": [{"type": "refusal", "name": "decision"}]}
    with _serving(body), pytest.raises(ValueError, match="refused question 'decision'"):
        await post_openai_decisions({"a": 1}, {"decision": CHOICE_QUESTION})


async def test_a_question_outside_the_two_shapes_is_refused_before_any_request() -> None:
    with _serving({"answers": []}) as client, pytest.raises(ValueError):
        await post_openai_decisions(
            {"a": 1}, {"x": {"type": "score", "instructions": "?", "criteria": {}}}
        )

    client.post.assert_not_awaited()
