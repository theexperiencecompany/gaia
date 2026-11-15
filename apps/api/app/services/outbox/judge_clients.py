"""The two ways the Judge is asked: OpenAI's Decisions API, and a reasoning model answering the same questions.

Both read the OpenAI key the credential store or the environment holds. Failure raises: the
Judge decides what a failed pass means, never this module.
"""

from collections.abc import Mapping
import json

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm, metered_config
from app.constants.outbox_judge import (
    JUDGE_ANONYMISED_STATE_NOTE,
    JUDGE_CHOICE_CRITERIA,
    JUDGE_DECISIONS_LABEL,
    JUDGE_DECISIONS_TIMEOUT_SECONDS,
    JUDGE_DECISIONS_URL,
    JUDGE_FAST_MODEL,
    JUDGE_INSTRUCTIONS,
    JUDGE_NO_WAIT,
    JUDGE_QUESTIONS,
    JUDGE_REASONING_EFFORT,
    JUDGE_REASONING_LABEL,
    JUDGE_REASONING_MODEL,
    JUDGE_REASONING_TIMEOUT_SECONDS,
    JUDGE_RUBRIC,
    JudgeQuestion,
)
from app.constants.providers import CredentialProviderName
from app.services.llm_metering import LLMCallContext, TokenUsage, record_llm_call
from app.services.outbox.judge_models import ReasoningAnswer
from app.services.outbox.judge_verdict import (
    ChoiceAnswer,
    JudgeAnswerError,
    PassAnswers,
    answers_from_reasoning,
)
from app.services.providers.provider_credentials_service import ProviderConfig, resolve

#: Run id -> what it is, for the runs the Judge may be told to wait for.
OfferedRuns = Mapping[str, str]


class JudgeUnconfiguredError(RuntimeError):
    """No OpenAI key is saved or set, so the Judge cannot be asked at all."""


async def _openai_key() -> str:
    config: ProviderConfig | None = await resolve(CredentialProviderName.OPENAI)
    key = config.api_key if config else None
    if not key:
        raise JudgeUnconfiguredError("No OpenAI key saved or set; cannot reach the Judge")
    return key


def _choices(question: JudgeQuestion, runs: OfferedRuns) -> dict[str, str]:
    if question is JudgeQuestion.WAIT_FOR_RUN:
        return {
            **runs,
            JUDGE_NO_WAIT: "Tell the user now; none of the listed runs is worth waiting for.",
        }
    return JUDGE_CHOICE_CRITERIA[question]


def asked_questions(runs: OfferedRuns) -> list[JudgeQuestion]:
    """Return the questions put to the Judge: every one, and the wait question only when runs are offered."""
    return [
        question for question in JudgeQuestion if question is not JudgeQuestion.WAIT_FOR_RUN or runs
    ]


def _instructions(question: str, anonymised_state: bool) -> str:
    template = JUDGE_INSTRUCTIONS
    if anonymised_state:
        template = template.replace("Question:", f"{JUDGE_ANONYMISED_STATE_NOTE} Question:")
    return template.format(question=question)


def decisions_body(
    state: Mapping[str, object], runs: OfferedRuns, *, anonymised_state: bool = False
) -> dict[str, object]:
    """Return the Decisions request for one state; anonymised_state is for the eval corpus alone."""
    return {
        "model": JUDGE_FAST_MODEL,
        "input": json.dumps(state, ensure_ascii=False),
        "questions": [
            {
                "name": question.value,
                "type": "choice",
                "instructions": _instructions(JUDGE_QUESTIONS[question], anonymised_state),
                "choices": [
                    {"value": value, "description": text}
                    for value, text in _choices(question, runs).items()
                ],
            }
            for question in asked_questions(runs)
        ],
    }


class _ChoiceProbability(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str
    probability: float


class _DecisionsAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choice: str
    probabilities: list[_ChoiceProbability] = Field(default_factory=list)
    confidence: float | None = None


class _DecisionsUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = 0
    output_tokens: int = 0


class _DecisionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, _DecisionsAnswer]
    usage: _DecisionsUsage = Field(default_factory=_DecisionsUsage)

    @field_validator("answers", mode="before")
    @classmethod
    def _keyed_by_question(cls, answers: object) -> object:
        """Accept the answers as a list of named answers as well as a map by name."""
        if isinstance(answers, list):
            if not all(isinstance(answer, dict) and "name" in answer for answer in answers):
                raise ValueError("a listed answer names its question")
            return {answer["name"]: answer for answer in answers}
        return answers


def _parse_decisions(body: object) -> _DecisionsResponse:
    try:
        return _DecisionsResponse.model_validate(body)
    except ValidationError as e:
        raise JudgeAnswerError(f"the Decisions answer is not in the shape asked for: {e}") from e


def _read_answers(response: _DecisionsResponse, runs: OfferedRuns) -> PassAnswers:
    answers: dict[JudgeQuestion, ChoiceAnswer] = {}
    for question in asked_questions(runs):
        answer = response.answers.get(question.value)
        if answer is None:
            raise JudgeAnswerError(f"the Decisions answer has no {question.value}")
        if answer.choice not in _choices(question, runs):
            raise JudgeAnswerError(f"{question.value}={answer.choice!r} is not one of its choices")
        probabilities = {entry.value: entry.probability for entry in answer.probabilities}
        answers[question] = ChoiceAnswer(answer.choice, probabilities, answer.confidence)
    return PassAnswers(
        answers=answers,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def read_decisions(body: object, runs: OfferedRuns) -> PassAnswers:
    """Read a Decisions response body; raise JudgeAnswerError when it is malformed, misses a question or answers outside the choices."""
    return _read_answers(_parse_decisions(body), runs)


async def _meter_decisions(answers: PassAnswers, user_id: str) -> None:
    await record_llm_call(
        user_id=user_id,
        model_name=JUDGE_FAST_MODEL,
        usage=TokenUsage(
            input_tokens=answers.input_tokens,
            output_tokens=answers.output_tokens,
            cached_tokens=0,
            reasoning_tokens=0,
        ),
        context=LLMCallContext(
            agent_name=JUDGE_DECISIONS_LABEL, background=True, charge_to_budget=False
        ),
    )


async def ask_decisions(
    state: Mapping[str, object],
    runs: OfferedRuns,
    *,
    user_id: str,
    anonymised_state: bool = False,
) -> PassAnswers:
    """Ask the Decisions API every question about one state; raises on a missing key, transport failure or unreadable answer.

    The call is metered to user_id once its answer reads; anonymised_state is True for the eval corpus alone.
    """
    key = await _openai_key()
    async with httpx.AsyncClient(timeout=JUDGE_DECISIONS_TIMEOUT_SECONDS) as client:
        response = await client.post(
            JUDGE_DECISIONS_URL,
            json=decisions_body(state, runs, anonymised_state=anonymised_state),
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        parsed = _parse_decisions(response.json())
        answers = _read_answers(parsed, runs)
    await _meter_decisions(answers, user_id)
    return answers


def reasoning_system_prompt(runs: OfferedRuns, *, anonymised_state: bool = False) -> str:
    """Return the prompt that makes the reasoning model answer the Decisions questions, with the rubric."""
    questions = "\n".join(
        f"- {question.value}: {JUDGE_QUESTIONS[question]} "
        + "; ".join(f"{value} = {text}" for value, text in _choices(question, runs).items())
        for question in asked_questions(runs)
    )
    return (
        _instructions("answer every question below.", anonymised_state)
        + f"\n\n# Policy\n{JUDGE_RUBRIC}\n# Questions\n{questions}"
    )


async def ask_reasoning(
    state: Mapping[str, object],
    runs: OfferedRuns,
    *,
    user_id: str,
    anonymised_state: bool = False,
) -> PassAnswers:
    """Have the reasoning model answer the same questions about the same state; raises on a failed call or unreadable answer.

    anonymised_state is for the eval corpus alone.
    """
    model = ChatOpenAI(
        model=JUDGE_REASONING_MODEL,
        api_key=SecretStr(await _openai_key()),
        reasoning_effort=JUDGE_REASONING_EFFORT,
        max_retries=0,
    )
    messages: list[BaseMessage] = [
        SystemMessage(content=reasoning_system_prompt(runs, anonymised_state=anonymised_state)),
        HumanMessage(content=json.dumps(state, ensure_ascii=False)),
    ]
    answer = await ainvoke_llm(
        model.with_structured_output(ReasoningAnswer, method="json_schema"),
        messages,
        config=metered_config(user_id),
        label=JUDGE_REASONING_LABEL,
        options=LLMInvokeOptions(timeout=JUDGE_REASONING_TIMEOUT_SECONDS, max_attempts=1),
    )
    return answers_from_reasoning(ReasoningAnswer.model_validate(answer))
