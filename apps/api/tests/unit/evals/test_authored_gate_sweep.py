"""The recorded authored-gate eval, regraded through decide_gate: what GAIA-authored conditions cost.

rules.jsonl is what the real authoring prompts wrote for 30 creation requests; recorded.jsonl is
JEV's answers about each request's labelled emails under its condition. Each recorded answer
is served at JEV's HTTP boundary for its own email, so a prompt edit never fails this suite;
re-record when the measured numbers should reflect it.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
from scripts.evals.suites.authored_gate import (
    AuthoringPath,
    CreationRequest,
    RecordedGate,
    Split,
    gate_of,
    job_of,
    labelled,
    load_mail,
    load_recorded,
    load_requests,
    load_rules,
)

from app.constants.trigger_gates import GateOwner
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.services.triggers.trigger_gate import GatedJob, GateSkip, decide_gate
from app.utils.timezone import Timezone
from tests.helpers import trigger_gate_seams

KOLKATA = Timezone.parse("Asia/Kolkata")
# 14:30 on the user's clock in Kolkata.
AFTERNOON = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
# Unwanted emails run anyway, of 63 holdout and 123 tune; a thread the user wrote in runs unasked.
RECORDED_WASTED_RUNS = {Split.HOLDOUT: 21, Split.TUNE: 42}


@dataclass(frozen=True)
class _Regraded:
    skipped: frozenset[tuple[str, str]]


def _replay(row: RecordedGate) -> Callable[..., httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=row["response"])

    return answer


async def _regrade() -> _Regraded:
    rules, mail = load_rules(), load_mail()
    skipped: set[tuple[str, str]] = set()
    with trigger_gate_seams(KOLKATA, now=AFTERNOON) as seams:
        for row in load_recorded():
            rule = rules[row["request_id"]]
            seams.jev.side_effect = _replay(row)
            seams.wrote.return_value = mail[row["mail_id"]]["wrote_in_thread"]
            verdict = await decide_gate(
                gate_of(rule),
                GatedJob(GateOwner.WORKFLOW, row["request_id"], USER_ID, job_of(rule)),
                trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
                payload=mail[row["mail_id"]]["message"],
            )
            if isinstance(verdict, GateSkip):
                skipped.add((row["request_id"], row["mail_id"]))
    return _Regraded(frozenset(skipped))


@pytest.fixture(scope="module")
def requests() -> dict[str, CreationRequest]:
    return {r["id"]: r for r in load_requests()}


@pytest.fixture(scope="module")
def regraded() -> _Regraded:
    return asyncio.run(_regrade())


def _labelled_in(
    requests: dict[str, CreationRequest], split: Split, *, wanted: bool
) -> set[tuple[str, str]]:
    return {
        (request_id, mail_id)
        for request_id, request in requests.items()
        if request["split"] is split
        for mail_id, is_wanted in labelled(request).items()
        if is_wanted is wanted
    }


def test_gaia_writes_a_condition_exactly_when_the_request_should_have_one(
    requests: dict[str, CreationRequest],
) -> None:
    rules = load_rules()
    assert rules.keys() == requests.keys()
    for request_id, request in requests.items():
        assert (rules[request_id]["rule"] is not None) is request.get("rule", True), request_id


@pytest.mark.parametrize("split", list(Split))
def test_no_authored_condition_skips_an_email_the_user_asked_the_job_to_act_on(
    requests: dict[str, CreationRequest], regraded: _Regraded, split: Split
) -> None:
    assert regraded.skipped & _labelled_in(requests, split, wanted=True) == set()


@pytest.mark.parametrize("split", list(Split))
def test_authored_conditions_run_only_the_recorded_number_of_unwanted_emails(
    requests: dict[str, CreationRequest], regraded: _Regraded, split: Split
) -> None:
    unwanted = _labelled_in(requests, split, wanted=False)
    assert len(unwanted - regraded.skipped) == RECORDED_WASTED_RUNS[split]


def test_both_authoring_paths_are_measured(requests: dict[str, CreationRequest]) -> None:
    paths = {r["path"] for r in requests.values() if r.get("wanted")}
    splits = {r["split"] for r in requests.values()}
    assert paths == set(AuthoringPath)
    assert splits == set(Split)
