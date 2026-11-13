"""The browser eval's cases build against the app's current browser job API, and its actors fail loud.

The suite only runs against live hosts and real models, so an API change used to
surface mid-run: a required BrowserJobRequest field failed every case, and an
actor whose import had gone died inside a swallowed task while its case passed.
"""

from __future__ import annotations

import asyncio

import pytest
from scripts.evals.core.providers import EvalConfig
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites import browser as browser_suite
from scripts.evals.suites.browser import (
    Actor,
    ActorFailedError,
    BrowserSuite,
    CasePlan,
    job_request,
    outcome_failures,
)

from app.constants.browser import BrowserSessionStatus
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.ledger import BurstRecord, RunLedger


def _cases() -> list[Case]:
    cfg = EvalConfig(
        providers={},
        rotation_order=[],
        default_max_usd=0.0,
        judge={"base_url_env": "X", "api_key_env": "Y"},
    )
    return BrowserSuite(cfg).load_cases(cfg)


def test_every_case_builds_the_jobs_it_would_run() -> None:
    cases = _cases()
    assert cases
    for case in cases:
        plan = CasePlan.of(case)
        request = job_request("eval-user", plan.prompt, plan.secrets)
        assert not request.in_background, f"{case.id}: an eval job must land in no inbox"
        assert set(request.secrets) == set(plan.secrets)
        if plan.reuse_prompt is not None:
            assert job_request("eval-user", plan.reuse_prompt, {}).task == plan.reuse_prompt


def test_a_case_naming_an_unknown_actor_fails_to_load() -> None:
    case = _cases()[0]
    with pytest.raises(ValueError, match="'phone_a_friend' is not a valid Actor"):
        CasePlan.of(
            Case(id=case.id, ticket="", prompt=case.prompt, setup={"actor": "phone_a_friend"})
        )


async def test_an_actor_that_raises_ends_the_job_and_fails_the_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_cancelled = asyncio.Event()

    async def run_until_cancelled(_request: BrowserJobRequest, _ledger: RunLedger) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            job_cancelled.set()

    async def broken_actor(_actor: Actor, _run: object, _message: str | None) -> None:
        raise ImportError("cannot import name 'read_cards'")

    monkeypatch.setattr(browser_suite, "execute_browser_job", run_until_cancelled)
    monkeypatch.setattr(browser_suite, "_act", broken_actor)
    request = job_request("eval-user", "Use the browser. Go to https://example.com.", {})

    with pytest.raises(ActorFailedError, match="read_cards"):
        await browser_suite._one_job(request, Actor.STOP, None)
    assert job_cancelled.is_set()


def test_a_run_its_actor_never_acted_on_fails_its_gate() -> None:
    stop_case = next(c for c in _cases() if c.setup.get("actor") == Actor.STOP.value)
    stopped = {"summary": "Stopped.", "success": False, "status": "stopped", "steps": 3}

    acted = CaseRun(case_id=stop_case.id, end_state={**stopped, "actor_missed": None})
    never = CaseRun(case_id=stop_case.id, end_state={**stopped, "actor_missed": "stop"})

    assert outcome_failures(stop_case, acted) == []
    assert outcome_failures(stop_case, never) == ["the run ended before its stop actor acted"]


def test_the_journal_keeps_each_jev_burst_and_step_card_of_a_job() -> None:
    burst = BurstRecord(
        goal="fill the form with <secret>password</secret>",
        done_when="the form is sent",
        stop="done",
        detail="",
        actions=('TYPE_TEXT Password = "<secret>password</secret>"',),
        url="https://site.test/sent?pw=<secret>password</secret>",
    )
    run = browser_suite._Run(
        job_id="j", user_id="u", reply_to="c", ledger=RunLedger(bursts=[burst])
    )
    run.steps = [{"index": 1, "goal": "Filling the form", "actions": [], "url": burst.url}]
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, summary="Sent.", success=True, steps=1
    )

    state = browser_suite._state(result, run, Actor.DECLINE)

    assert state["jev_bursts"] == [
        {
            "goal": burst.goal,
            "done_when": burst.done_when,
            "stop": "done",
            "detail": "",
            "actions": burst.actions,
            "url": burst.url,
        }
    ]
    assert state["step_cards"] == run.steps
