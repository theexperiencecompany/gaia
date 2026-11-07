"""The recorded email-verdict eval, regraded: the bucket the Inbox desk reads for each email, as a CI fact.

Each recorded day answer is read back through production's read_verdict, and each request
hash, by day and in quiet hours, must match what verdict_request sends today, so a criteria edit without a re-recorded run
fails here. The desk gate's arrival decisions on the same answers are regraded in
test_trigger_gate_sweep.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path

import httpx
import pytest
from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.types import Case, ProviderError
from scripts.evals.suites.trigger_gate import (
    BUCKET_GATE,
    DATA_DIR,
    UNBUCKETED,
    VERDICTS_RECORDED_DIR,
    EmailVerdictSuite,
    GateMode,
    VerdictJournalFields,
    VerdictTransport,
    graded_bucket,
    jev_body,
    request_sha,
    verdict_requests,
)

from app.constants.desk_buckets import DeskBucket
from app.models.jev_models import JevDecisionsResponse
from app.utils.timezone import Timezone
from tests.helpers import email_verdict_answers, trigger_gate_seams

from .conftest import eval_config

# Each bucket's share of its labelled emails JEV puts back in it, in every recorded pass.
# junk is low by design: a junk under P 0.95 goes unbucketed and the desk judges it.
# The corpus labels no waiting email, so waiting has no floor to keep.
RECALL_FLOORS: Mapping[DeskBucket, float] = {
    DeskBucket.REPLY: 0.67,
    DeskBucket.ACT: 0.95,
    DeskBucket.FYI: 0.89,
    DeskBucket.JUNK: 0.42,
}
# Needs-you emails some pass buckets junk, so the desk never reads them.
RECORDED_LOST_TO_JUNK: frozenset[str] = frozenset()
# The routine sign-in notices some pass buckets other than fyi.
RECORDED_SIGN_IN_NOT_FYI: frozenset[str] = frozenset()
SIGN_IN_NOTICE_TAG = "sign_in_notice"
SECURITY_PROBLEM_TAG = "security_problem"
_NEEDS_THE_USER = frozenset({DeskBucket.REPLY, DeskBucket.WAITING, DeskBucket.ACT})


class RecordedVerdictRow(VerdictJournalFields):
    """One email's line in a recorded verdict pass."""

    case_id: str


@dataclass(frozen=True)
class _Pass:
    run_id: str
    rows: Mapping[str, RecordedVerdictRow]

    def bucket(self, case_id: str) -> str:
        asked = self.rows[case_id]["requests"][GateMode.DAY]
        return graded_bucket(JevDecisionsResponse.model_validate(asked["response"]))


def _read(path: Path) -> _Pass:
    rows: list[RecordedVerdictRow] = [json.loads(line) for line in path.read_text().splitlines()]
    return _Pass(path.stem, {row["case_id"]: row for row in rows})


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    cfg = eval_config()
    return {case.id: case for case in EmailVerdictSuite(cfg).load_cases(cfg)}


@pytest.fixture(scope="module")
def passes() -> list[_Pass]:
    recorded = [_read(path) for path in sorted(VERDICTS_RECORDED_DIR.glob("*.jsonl"))]
    assert len(recorded) >= 3, f"fewer than 3 recorded passes under {VERDICTS_RECORDED_DIR}"
    return recorded


def _labelled(cases: Mapping[str, Case], bucket: DeskBucket) -> set[str]:
    return {c for c, case in cases.items() if case.expected["bucket"] == bucket}


def test_every_email_in_the_corpus_is_labelled_with_a_bucket() -> None:
    for case in load_case_files(DATA_DIR, EmailVerdictSuite.name, EmailVerdictSuite.extra):
        assert DeskBucket(case.expected["bucket"]), case.id


def test_the_suite_gates_every_case_on_its_bucket_alone(cases: dict[str, Case]) -> None:
    assert {tuple(case.gates) for case in cases.values()} == {(BUCKET_GATE,)}


def test_every_recorded_pass_answers_every_email_in_the_corpus(
    cases: dict[str, Case], passes: list[_Pass]
) -> None:
    for p in passes:
        assert set(p.rows) == set(cases), p.run_id


def test_the_recorded_answers_are_to_the_requests_production_sends_today(
    cases: dict[str, Case], passes: list[_Pass]
) -> None:
    for p in passes:
        for case_id, row in p.rows.items():
            built = verdict_requests(cases[case_id].setup["message"])
            for mode, (state, questions) in built.items():
                sha = request_sha(jev_body(state, questions))
                assert sha == row["requests"][mode]["request_sha"], f"{p.run_id}: {case_id}/{mode}"


def test_the_live_suite_graded_each_bucket_as_production_reads_it(passes: list[_Pass]) -> None:
    for p in passes:
        for case_id, row in p.rows.items():
            assert row["bucket"] == p.bucket(case_id), f"{p.run_id}: {case_id}"


@pytest.mark.parametrize("bucket", list(RECALL_FLOORS), ids=[b.value for b in RECALL_FLOORS])
def test_each_bucket_keeps_its_recall_floor_in_every_pass(
    cases: dict[str, Case], passes: list[_Pass], bucket: DeskBucket
) -> None:
    labelled = _labelled(cases, bucket)
    assert labelled, bucket
    for p in passes:
        kept = {c for c in labelled if p.bucket(c) == bucket}
        assert len(kept) / len(labelled) >= RECALL_FLOORS[bucket], p.run_id


def test_no_pass_buckets_junk_an_email_that_needs_the_user_but_the_recorded_few(
    cases: dict[str, Case], passes: list[_Pass]
) -> None:
    needs = {c for c, case in cases.items() if case.expected["bucket"] in _NEEDS_THE_USER}
    lost = {c for p in passes for c in needs if p.bucket(c) == DeskBucket.JUNK}
    assert lost == RECORDED_LOST_TO_JUNK


def test_a_routine_sign_in_notice_is_fyi_never_act(
    cases: dict[str, Case], passes: list[_Pass]
) -> None:
    """Regression: an Infisical new-device login became an action todo on the Inbox desk."""
    notices = {c for c, case in cases.items() if SIGN_IN_NOTICE_TAG in case.tags}
    assert notices
    not_fyi = {c for p in passes for c in notices if p.bucket(c) != DeskBucket.FYI}
    assert not_fyi == RECORDED_SIGN_IN_NOT_FYI
    assert {c for p in passes for c in notices if p.bucket(c) == DeskBucket.ACT} == set()


def test_a_security_problem_is_act_in_every_pass(
    cases: dict[str, Case], passes: list[_Pass]
) -> None:
    problems = {c for c, case in cases.items() if SECURITY_PROBLEM_TAG in case.tags}
    assert problems
    for p in passes:
        assert {c for c in problems if p.bucket(c) != DeskBucket.ACT} == set(), p.run_id


def _answer(choice: str) -> httpx.Response:
    return httpx.Response(200, json=email_verdict_answers(choice))


async def test_the_live_suite_journals_the_request_it_sent_and_the_bucket_it_read(
    cases: dict[str, Case],
) -> None:
    cfg = eval_config()
    with trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as seams:
        seams.jev.mock(return_value=_answer("junk"))
        run = await VerdictTransport().run(
            cases["mail-001"], cfg, EvalCostTracker(cfg.providers, 1.0), cfg.providers["fake"]
        )
        sent = json.loads(seams.jev.calls.last.request.content)

    end_state = run.end_state or {}
    assert end_state["bucket"] == "junk"
    assert end_state["requests"][GateMode.QUIET]["request_sha"] == request_sha(sent)
    assert list(sent["questions"]) == ["bucket", "urgent"]
    assert EmailVerdictSuite.extra[BUCKET_GATE](cases["mail-001"], run) == (
        1.0 if cases["mail-001"].expected["bucket"] == "junk" else 0.0
    )


async def test_an_answer_naming_no_bucket_is_journaled_unbucketed(
    cases: dict[str, Case],
) -> None:
    cfg = eval_config()
    with trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as seams:
        seams.jev.mock(return_value=_answer("not_a_bucket"))
        run = await VerdictTransport().run(
            cases["mail-001"], cfg, EvalCostTracker(cfg.providers, 1.0), cfg.providers["fake"]
        )

    assert (run.end_state or {})["bucket"] == UNBUCKETED
    assert EmailVerdictSuite.extra[BUCKET_GATE](cases["mail-001"], run) == 0.0


async def test_a_jev_outage_in_the_live_suite_is_a_provider_error_not_a_bucket(
    cases: dict[str, Case],
) -> None:
    cfg = eval_config()
    with trigger_gate_seams(Timezone.parse("Asia/Kolkata")) as seams:
        seams.jev.mock(return_value=httpx.Response(503))
        with pytest.raises(ProviderError, match="503"):
            await VerdictTransport().run(
                cases["mail-001"], cfg, EvalCostTracker(cfg.providers, 1.0), cfg.providers["fake"]
            )
