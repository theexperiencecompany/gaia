"""The two ways the Judge is asked: OpenAI's Decisions API, and a reasoning model answering the same questions.

Both read the OpenAI key the credential store or the environment holds. Failure raises: the
Judge decides what a failed pass means, never this module.
"""

from collections.abc import Mapping
import json
from typing import cast

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.agents.llm.client import LLMInvokeOptions, ainvoke_llm
from app.constants.outbox_judge import (
    JUDGE_ANONYMISED_STATE_NOTE,
    JUDGE_CHOICE_CRITERIA,
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


class _DecisionsAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None


class _DecisionsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, _DecisionsAnswer]

    @field_validator("answers", mode="before")
    @classmethod
    def _keyed_by_question(cls, answers: object) -> object:
        """Accept the answers as a list of named answers as well as a map by name."""
        if isinstance(answers, list):
            return {answer["name"]: answer for answer in answers}
        return answers


def read_decisions(body: object, runs: OfferedRuns) -> PassAnswers:
    """Read a Decisions response body; raise JudgeAnswerError when it misses a question or answers outside the choices."""
    response = _DecisionsResponse.model_validate(body)
    answers: dict[JudgeQuestion, ChoiceAnswer] = {}
    for question in asked_questions(runs):
        answer = response.answers.get(question.value)
        if answer is None:
            raise JudgeAnswerError(f"the Decisions answer has no {question.value}")
        if answer.choice not in _choices(question, runs):
            raise JudgeAnswerError(f"{question.value}={answer.choice!r} is not one of its choices")
        answers[question] = ChoiceAnswer(answer.choice, answer.probabilities, answer.confidence)
    return PassAnswers(answers=answers)


async def ask_decisions(
    state: Mapping[str, object], runs: OfferedRuns, *, anonymised_state: bool = False
) -> PassAnswers:
    """Ask the Decisions API every question about one state; raises on a missing key, transport failure or unreadable answer.

    anonymised_state is for the eval corpus alone.
    """
    key = await _openai_key()
    async with httpx.AsyncClient(timeout=JUDGE_DECISIONS_TIMEOUT_SECONDS) as client:
        response = await client.post(
            JUDGE_DECISIONS_URL,
            json=decisions_body(state, runs, anonymised_state=anonymised_state),
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        return read_decisions(response.json(), runs)


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
        config=cast(RunnableConfig, {"configurable": {"user_id": user_id}}),
        label=JUDGE_REASONING_LABEL,
        options=LLMInvokeOptions(timeout=JUDGE_REASONING_TIMEOUT_SECONDS, max_attempts=1),
    )
    return answers_from_reasoning(ReasoningAnswer.model_validate(answer))
