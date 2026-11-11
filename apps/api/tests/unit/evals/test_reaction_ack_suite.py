"""The reaction-ack suite grades JEV's answer through the production rule, and fails any tap on a must_not_react case."""

from __future__ import annotations

import pytest
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import reaction_ack
from scripts.evals.suites.reaction_ack import ReactionTransport, reaction_expect

from app.models.jev_models import JevDecisionsResponse
from app.services.conversation.ack import reaction_request
from tests.helpers import reaction_answers

from .conftest import eval_config


def _case(expect: str, emojis: list[str] | None = None) -> Case:
    return Case(
        id="c",
        ticket="t",
        prompt="find my flight email",
        setup={"message": "find my flight email", "previous_assistant": "Hi!"},
        expected={"expect": expect, "emojis": emojis or []},
    )


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    case: Case,
    *,
    upset: float = 0.0,
    task: float = 1.0,
    emoji: str = "🔎",
) -> CaseRun:
    sent: list[object] = []

    async def _post(*request: object) -> JevDecisionsResponse:
        sent.append(request)
        return JevDecisionsResponse.model_validate(
            reaction_answers(upset=upset, task=task, emoji=emoji)
        )

    monkeypatch.setattr(reaction_ack, "post_decisions", _post)
    cfg = eval_config()
    provider = cfg.providers["fake"]
    run = await ReactionTransport().run(
        case, cfg, EvalCostTracker(cfg.providers, cfg.default_max_usd), provider
    )
    assert sent == [reaction_request("find my flight email", "Hi!")]
    return run


async def test_a_tap_on_a_must_not_react_case_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case("must_not_react")

    run = await _run(monkeypatch, case, upset=0.0, task=0.9)

    assert reaction_expect(case, run) == 0.0


async def test_an_upset_answer_is_no_tap_and_passes_must_not_react(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _case("must_not_react")

    run = await _run(monkeypatch, case, upset=0.9, task=0.9)

    assert reaction_expect(case, run) == 1.0
    assert (run.end_state or {})["decision"]["reason"] == "upset"


async def test_should_react_needs_an_acceptable_emoji(monkeypatch: pytest.MonkeyPatch) -> None:
    fits, misfits = _case("should_react", ["📥"]), _case("should_react", ["📅"])

    run = await _run(monkeypatch, fits, emoji="📥")

    assert reaction_expect(fits, run) == 1.0
    assert reaction_expect(misfits, run) == 0.0


async def test_an_out_of_palette_emoji_grades_as_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case("should_react", ["📥"])

    run = await _run(monkeypatch, case, emoji="🍕")

    assert (run.end_state or {})["decision"]["reason"] == "malformed"
    assert reaction_expect(case, run) == 0.0
