"""OpenAI's Decisions API as a judge transport, for calibration runs only.

Prod's judge asks JEV (app/services/hil/jev_judge.py). This lets the hil-judge
suite put the same questions to OpenAI's model for comparison: it translates the
repo's question shape to OpenAI's wire (choice -> choices, noul -> predicate) and
the answers back into JevDecisionsResponse. Failure raises.
"""

from collections.abc import Mapping
from typing import Literal

import httpx
from pydantic import BaseModel

from app.constants.llm import OPENAI_API_URL
from app.constants.providers import CredentialProviderName
from app.models.jev_models import JevDecisionsResponse
from app.services.providers.provider_credentials_service import ProviderConfig, resolve

OPENAI_DECISIONS_MODEL_NAME = "gpt-6-luna"
OPENAI_DECISIONS_URL = f"{OPENAI_API_URL}/decisions"
OPENAI_DECISIONS_TIMEOUT_SECONDS = 15


class OpenAIDecisionsUnconfiguredError(RuntimeError):
    """No OpenAI key is saved or set, so the Decisions API cannot be asked at all."""


class _Question(BaseModel):
    """One question as prompts.py writes it."""

    type: Literal["choice", "noul"]
    instructions: str
    criteria: dict[str, str]


class _WireProbability(BaseModel):
    value: str | bool
    probability: float


class _WireAnswer(BaseModel):
    """One OpenAI answer: a choice, a predicate, or a refusal."""

    type: Literal["choice", "predicate", "refusal"]
    name: str | None = None
    choice: str | bool | None = None
    confidence: float | None = None
    probabilities: list[_WireProbability] | None = None
    probability: float | None = None


class _WireUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class _WireResponse(BaseModel):
    answers: list[_WireAnswer]
    usage: _WireUsage | None = None


async def post_openai_decisions(
    state: Mapping[str, object], questions: Mapping[str, Mapping[str, object]]
) -> JevDecisionsResponse:
    """One Decisions call on the saved or env OpenAI key, every question over the same state.

    Raises on a missing key, a transport failure, a refused question, or a malformed body.
    """
    config: ProviderConfig | None = await resolve(CredentialProviderName.OPENAI)
    key = config.api_key if config else None
    if not key:
        raise OpenAIDecisionsUnconfiguredError(
            "No OpenAI key saved or set; cannot reach the Decisions API"
        )
    body = {
        "model": OPENAI_DECISIONS_MODEL_NAME,
        "input": [{"role": "user", "content": [{"type": "input_json", "data": dict(state)}]}],
        "questions": [
            _wire_question(name, _Question.model_validate(question))
            for name, question in questions.items()
        ],
    }
    async with httpx.AsyncClient(timeout=OPENAI_DECISIONS_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            OPENAI_DECISIONS_URL, json=body, headers={"Authorization": f"Bearer {key}"}
        )
        resp.raise_for_status()
        return _answers(_WireResponse.model_validate(resp.json()))


def _wire_question(name: str, question: _Question) -> dict[str, object]:
    """Translate one question: a choice keeps its options, a noul becomes a two-sided predicate."""
    if question.type == "choice":
        return {
            "name": name,
            "type": "choice",
            "instructions": question.instructions,
            "choices": [
                {"value": value, "description": description}
                for value, description in question.criteria.items()
            ],
        }
    return {
        "name": name,
        "type": "predicate",
        "instructions": (
            f"{question.instructions}\n"
            f"True when: {question.criteria['true']}\n"
            f"False when: {question.criteria['false']}"
        ),
    }


def _answers(wire: _WireResponse) -> JevDecisionsResponse:
    answers: dict[str, dict[str, object]] = {}
    for answer in wire.answers:
        if answer.type == "refusal" or answer.name is None:
            raise ValueError(f"Decisions API refused question {answer.name!r}")
        if answer.type == "choice":
            answers[answer.name] = {
                "type": "choice",
                "choice": str(answer.choice),
                "confidence": answer.confidence,
                "probabilities": {
                    str(item.value): item.probability for item in answer.probabilities or []
                },
            }
        else:
            answers[answer.name] = {"type": "noul", "noul": answer.probability}
    usage = wire.usage or _WireUsage()
    return JevDecisionsResponse.model_validate(
        {
            "answers": answers,
            "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
        }
    )
