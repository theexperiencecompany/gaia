"""The two ways the Judge is asked: the Decisions request and answer, and the reasoning model's prompt."""

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants.outbox_judge import (
    JUDGE_ANONYMISED_STATE_NOTE,
    JUDGE_CHOICE_CRITERIA,
    JUDGE_DECISIONS_URL,
    JUDGE_FAST_MODEL,
    JUDGE_QUESTIONS,
    JUDGE_REASONING_LABEL,
    JUDGE_REASONING_MODEL,
    JudgeQuestion,
)
from app.services.outbox import judge_clients
from app.services.outbox.judge_clients import (
    JudgeUnconfiguredError,
    ask_decisions,
    ask_reasoning,
    asked_questions,
    decisions_body,
    read_decisions,
    reasoning_system_prompt,
)
from app.services.outbox.judge_models import (
    Authenticity,
    Deadline,
    Moment,
    ReasoningAnswer,
    Relevance,
    Sensitivity,
    UrgencyAnswer,
    YesNo,
)
from app.services.outbox.judge_verdict import JudgeAnswerError

STATE = {"now": "2026-11-10T09:00:00Z", "item": {"facts": ["x"]}}
RUNS = {"workflow:wf_1": "Morning briefing"}


def _answer(question: JudgeQuestion, runs: Mapping[str, str]) -> dict[str, Any]:
    first = next(
        iter(runs if question is JudgeQuestion.WAIT_FOR_RUN else JUDGE_CHOICE_CRITERIA[question])
    )
    return {"choice": first, "probabilities": {first: 0.8}, "confidence": 0.6}


def _body(runs: Mapping[str, str] | None = None) -> dict[str, Any]:
    offered = runs or {}
    return {
        "answers": {q.value: _answer(q, offered) for q in asked_questions(offered)},
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }


def test_every_question_offers_exactly_the_choices_its_enum_names() -> None:
    enums = {
        JudgeQuestion.URGENCY: UrgencyAnswer,
        JudgeQuestion.DEADLINE: Deadline,
        JudgeQuestion.RELEVANCE: Relevance,
        JudgeQuestion.SENSITIVITY: Sensitivity,
        JudgeQuestion.MOMENT: Moment,
        JudgeQuestion.AUTHENTICITY: Authenticity,
        JudgeQuestion.WORTH_TELLING: YesNo,
        JudgeQuestion.WITHIN_MINUTES: YesNo,
        JudgeQuestion.BEFORE_CHECKIN: YesNo,
    }

    for question, enum in enums.items():
        assert set(JUDGE_CHOICE_CRITERIA[question]) == {member.value for member in enum}
    assert set(JUDGE_QUESTIONS) == set(JudgeQuestion)


def test_the_wait_question_is_asked_only_when_runs_are_offered() -> None:
    assert JudgeQuestion.WAIT_FOR_RUN not in asked_questions({})
    assert JudgeQuestion.WAIT_FOR_RUN in asked_questions(RUNS)


def test_the_decisions_request_names_the_model_and_every_question_with_its_choices() -> None:
    body = decisions_body(STATE, {})

    assert body["model"] == JUDGE_FAST_MODEL
    assert json.loads(str(body["input"])) == STATE
    questions = body["questions"]
    assert isinstance(questions, list)
    assert [q["name"] for q in questions] == [q.value for q in asked_questions({})]
    urgency = next(q for q in questions if q["name"] == "urgency")
    assert [c["value"] for c in urgency["choices"]] == [
        "interrupt",
        "timely",
        "routine",
        "background",
    ]
    assert JUDGE_QUESTIONS[JudgeQuestion.URGENCY] in urgency["instructions"]


def test_live_requests_never_tell_the_judge_that_domains_are_anonymised() -> None:
    questions = decisions_body(STATE, {})["questions"]

    assert isinstance(questions, list)
    assert all(JUDGE_ANONYMISED_STATE_NOTE not in q["instructions"] for q in questions)


def test_the_eval_corpus_alone_tells_the_judge_its_domains_are_anonymised() -> None:
    questions = decisions_body(STATE, {}, anonymised_state=True)["questions"]

    assert isinstance(questions, list)
    assert all(JUDGE_ANONYMISED_STATE_NOTE in q["instructions"] for q in questions)


def test_the_wait_question_offers_each_run_and_not_waiting() -> None:
    questions = decisions_body(STATE, RUNS)["questions"]

    assert isinstance(questions, list)
    wait = next(q for q in questions if q["name"] == "wait_for_run")
    assert [c["value"] for c in wait["choices"]] == ["workflow:wf_1", "none"]


def test_a_decisions_answer_is_read_by_question() -> None:
    answers = read_decisions(_body(), {})

    urgency = answers.get(JudgeQuestion.URGENCY)
    assert (urgency.choice, urgency.confidence) == ("interrupt", 0.6)
    assert urgency.probability("interrupt") == 0.8


def test_answers_listed_by_name_are_read_like_answers_keyed_by_name() -> None:
    keyed = _body()
    listed = {"answers": [{"name": name, **answer} for name, answer in keyed["answers"].items()]}

    assert read_decisions(listed, {}).answers == read_decisions(keyed, {}).answers


def test_a_missing_question_raises() -> None:
    body = _body()
    del body["answers"]["moment"]

    with pytest.raises(JudgeAnswerError, match="moment"):
        read_decisions(body, {})


def test_a_choice_that_was_not_offered_raises() -> None:
    body = _body()
    body["answers"]["urgency"]["choice"] = "panic"

    with pytest.raises(JudgeAnswerError, match="urgency"):
        read_decisions(body, {})


def test_a_malformed_body_raises() -> None:
    with pytest.raises(ValueError):
        read_decisions({"nothing": 1}, {})


class _Client:
    """Stands in for the httpx client: records the request and answers with what it was given."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.posted: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        self.posted.append((url, json, headers))
        return self.response


def _response(status: int, body: object) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("POST", JUDGE_DECISIONS_URL))


async def test_the_decisions_api_is_asked_with_the_saved_key() -> None:
    client = _Client(_response(200, _body()))
    with (
        patch.object(judge_clients, "_openai_key", AsyncMock(return_value="sk-test")),
        patch("app.services.outbox.judge_clients.httpx.AsyncClient", return_value=client),
    ):
        answers = await ask_decisions(STATE, {})

    url, sent, headers = client.posted[0]
    assert (url, headers) == (JUDGE_DECISIONS_URL, {"Authorization": "Bearer sk-test"})
    assert sent == decisions_body(STATE, {})
    assert answers.get(JudgeQuestion.URGENCY).choice == "interrupt"


async def test_a_failed_decisions_call_raises() -> None:
    client = _Client(_response(500, {"error": "down"}))
    with (
        patch.object(judge_clients, "_openai_key", AsyncMock(return_value="sk-test")),
        patch("app.services.outbox.judge_clients.httpx.AsyncClient", return_value=client),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await ask_decisions(STATE, {})


async def test_without_an_openai_key_the_judge_cannot_be_asked() -> None:
    with (
        patch.object(judge_clients, "resolve", AsyncMock(return_value=None)),
        pytest.raises(JudgeUnconfiguredError),
    ):
        await ask_decisions(STATE, {})


def test_the_reasoning_prompt_carries_the_rubric_every_question_and_the_runs() -> None:
    prompt = reasoning_system_prompt(RUNS)

    assert "# Policy" in prompt and "`interrupt`: the user loses something real" in prompt
    assert all(q.value in prompt for q in asked_questions(RUNS))
    assert "workflow:wf_1 = Morning briefing" in prompt
    assert "wait_for_run" not in reasoning_system_prompt({})


def _reasoned() -> ReasoningAnswer:
    return ReasoningAnswer(
        urgency=UrgencyAnswer.TIMELY,
        deadline=Deadline.WITHIN_TODAY,
        relevance=Relevance.NEW,
        sensitivity=Sensitivity.NONE,
        moment=Moment.OK,
        authenticity=Authenticity.GENUINE,
        worth_telling=YesNo.YES,
        within_minutes=YesNo.NO,
        before_checkin=YesNo.YES,
        wait_for_run=None,
        reason="r",
        relevance_ref=None,
        same_fact_key=None,
        corrects=None,
        valid_until=datetime(2026, 11, 11, tzinfo=UTC),
        topics=[],
        rules_applied=[],
    )


async def test_the_reasoning_model_is_asked_the_same_state_on_its_own_model() -> None:
    model = MagicMock()
    invoke = AsyncMock(return_value=_reasoned())
    with (
        patch.object(judge_clients, "_openai_key", AsyncMock(return_value="sk-test")),
        patch.object(judge_clients, "ChatOpenAI", return_value=model) as chat,
        patch.object(judge_clients, "ainvoke_llm", invoke),
    ):
        answers = await ask_reasoning(STATE, {}, user_id="u1")

    assert chat.call_args.kwargs["model"] == JUDGE_REASONING_MODEL
    messages = invoke.await_args.args[1]
    assert json.loads(messages[1].content) == STATE
    assert invoke.await_args.kwargs["label"] == JUDGE_REASONING_LABEL
    assert invoke.await_args.kwargs["config"] == {"configurable": {"user_id": "u1"}}
    assert answers.get(JudgeQuestion.URGENCY).choice == "timely"
    assert answers.free_form is not None
