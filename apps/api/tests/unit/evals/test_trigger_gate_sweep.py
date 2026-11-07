"""The recorded trigger-gate and email-verdict evals, regraded through decide_gate: the gates' accuracy as a CI fact.

JEV is served at its HTTP boundary from data/trigger-gate, so each verdict comes from the
production gate view, builder, client and settle order. The desk gate is regraded from the
email-verdict passes, the authored template from the trigger-gate pass. A request production
no longer sends finds no recorded answer, so a prompt edit without a re-recorded run fails here.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

import httpx
import pytest
from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.types import Case, CaseRun, ProviderError
from scripts.evals.suites.trigger_gate import (
    AUTHORED_DESK_GATE,
    DATA_DIR,
    DESK_GATE,
    EXTRA,
    RECORDED_DIR,
    USER_WROTE_IN_THREAD,
    VERDICTS_RECORDED_DIR,
    AskedRequest,
    GateJournalFields,
    GateMode,
    GateTransport,
    TriggerGateSuite,
    gate_requests,
    jev_body,
    quiet_wakes,
    record,
    request_sha,
    verdict_requests,
)
import time_machine

from app.constants.desk_buckets import DESK_AUTOMATION
from app.constants.trigger_gates import ENFORCED_GATE_KINDS, GateKind, GateOwner
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.jev_models import JevDecisionsResponse
from app.models.trigger_gate_models import TriggerGate
from app.services.triggers.trigger_gate import (
    GateBypass,
    GatedJob,
    GateSkip,
    GateVerdict,
    decide_gate,
)
from app.utils.timezone import Timezone
from tests.helpers import trigger_gate_seams

from .conftest import eval_config

KOLKATA = Timezone.parse("Asia/Kolkata")
# 14:30 and 02:30 on the user's clock in Kolkata.
AFTERNOON = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
NIGHT = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
_GATES: Mapping[GateKind, TriggerGate] = {
    GateKind.SYSTEM: DESK_GATE,
    GateKind.AUTHORED: AUTHORED_DESK_GATE,
}
_RECORDED = {GateKind.SYSTEM: VERDICTS_RECORDED_DIR, GateKind.AUTHORED: RECORDED_DIR}
_BUILDERS = {GateKind.SYSTEM: verdict_requests, GateKind.AUTHORED: gate_requests}
# The needs_you emails the desk gate skips by day in some pass, bucketed fyi or junk; the
# yes/no gate the verdict replaced skipped mail-245 and mail-353.
RECORDED_DAY_FALSE_SKIPS = frozenset({"mail-048", "mail-049", "mail-353"})
# The same inside quiet hours; the yes/no gate skipped mail-245, mail-313 and mail-353.
RECORDED_QUIET_FALSE_SKIPS = frozenset({"mail-048", "mail-049", "mail-313", "mail-353"})
# The two service-down emails; mail-151 sits near P(urgent) 0.80, so a pass may hold it.
RECORDED_WAKES = frozenset({"mail-094", "mail-151"})
NOISE_SKIP_FLOOR = 0.70
SIGN_IN_NOTICE_TAG = "sign_in_notice"
# needs_you emails the authored template skips by day and the desk gate runs; enforced anyway by
# founder decision, so a change to this set is a change to what authored gates cost the user.
# mail-245 the yes/no desk gate skipped too; the email verdict runs it.
RECORDED_AUTHORED_ONLY_FALSE_SKIPS = frozenset({"mail-245"})


class RecordedRow(GateJournalFields):
    """One email's line in a recorded authored-gate pass; a verdict row carries the same requests."""

    case_id: str


def read_recorded(path: Path) -> dict[str, RecordedRow]:
    """Return one recorded pass, keyed by case id."""
    rows: list[RecordedRow] = [json.loads(line) for line in path.read_text().splitlines()]
    return {row["case_id"]: row for row in rows}


@dataclass(frozen=True)
class _Pass:
    """One recorded run, regraded: every email's verdict in each mode."""

    run_id: str
    kind: GateKind
    rows: Mapping[str, RecordedRow]
    verdicts: Mapping[tuple[str, GateMode], GateVerdict]
    unanswered: tuple[str, ...]


def _replay(asked: AskedRequest, unanswered: list[str], key: str) -> Callable[..., httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        if request_sha(json.loads(request.content)) != asked["request_sha"]:
            unanswered.append(key)
            return httpx.Response(500, text="no recorded answer to this request")
        return httpx.Response(200, json=asked["response"])

    return answer


async def _regrade(cases: Mapping[str, Case]) -> list[_Pass]:
    passes = []
    with trigger_gate_seams(KOLKATA, now=AFTERNOON) as seams:
        for kind, directory in _RECORDED.items():
            for path in sorted(directory.glob("*.jsonl")):
                rows = read_recorded(path)
                verdicts: dict[tuple[str, GateMode], GateVerdict] = {}
                unanswered: list[str] = []
                for mode, now in ((GateMode.DAY, AFTERNOON), (GateMode.QUIET, NIGHT)):
                    with time_machine.travel(now, tick=False):
                        for case_id, row in rows.items():
                            asked = row["requests"][mode]
                            seams.jev.side_effect = _replay(asked, unanswered, f"{case_id}/{mode}")
                            wrote = cases[case_id].setup.get(USER_WROTE_IN_THREAD, True)
                            seams.wrote.return_value = wrote
                            verdicts[case_id, mode] = await decide_gate(
                                _GATES[kind],
                                GatedJob(GateOwner.TODO, case_id, USER_ID, DESK_AUTOMATION),
                                trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
                                payload=cases[case_id].setup["message"],
                            )
                passes.append(_Pass(path.stem, kind, rows, verdicts, tuple(unanswered)))
    return passes


@pytest.fixture(scope="module")
def cases() -> dict[str, Case]:
    return {case.id: case for case in load_case_files(DATA_DIR, TriggerGateSuite.name, EXTRA)}


@pytest.fixture(scope="module")
def regraded(cases: dict[str, Case]) -> list[_Pass]:
    return asyncio.run(_regrade(cases))


def _passes(regraded: list[_Pass], kind: GateKind) -> list[_Pass]:
    chosen = [p for p in regraded if p.kind is kind]
    assert chosen, f"no recorded {kind} pass under {_RECORDED[kind]}"
    return chosen


def _decided(
    cases: Mapping[str, Case],
    p: _Pass,
    mode: GateMode,
    kind: type[GateVerdict],
    *,
    label: str | None = None,
    split: str | None = None,
) -> set[str]:
    """Return the emails one pass decided as kind in mode, of one label and split when given."""
    return {
        case_id
        for (case_id, at), verdict in p.verdicts.items()
        if at is mode
        and isinstance(verdict, kind)
        and label in (None, cases[case_id].expected["label"])
        and split in (None, cases[case_id].expected["split"])
    }


def _needs_you_skipped(cases: Mapping[str, Case], passes: list[_Pass], mode: GateMode) -> set[str]:
    """Return every needs_you email any of the passes skipped in mode."""
    return set().union(*(_decided(cases, p, mode, GateSkip, label="needs_you") for p in passes))


def test_the_desk_gate_is_regraded_from_three_verdict_passes(regraded: list[_Pass]) -> None:
    assert len(_passes(regraded, GateKind.SYSTEM)) >= 3


def test_every_recorded_pass_answers_every_email_in_the_corpus(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    for p in regraded:
        assert {case_id for case_id, _ in p.verdicts} == set(cases), p.run_id


def test_the_recorded_answers_are_to_the_requests_production_sends_today(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    for p in regraded:
        assert p.unanswered == (), f"{p.run_id}: production now sends other requests; re-record"
        for case_id, row in p.rows.items():
            built = _BUILDERS[p.kind](cases[case_id].setup["message"])
            for mode, (state, questions) in built.items():
                sha = request_sha(jev_body(state, questions))
                assert sha == row["requests"][mode]["request_sha"], f"{case_id}/{mode}"


def test_the_live_suite_graded_each_authored_email_by_day_as_decide_gate_does(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    for p in _passes(regraded, GateKind.AUTHORED):
        skipped = _decided(cases, p, GateMode.DAY, GateSkip)
        assert {c for c, row in p.rows.items() if row["outcome"] == "skip"} == skipped, p.run_id


def test_the_live_suite_graded_each_quiet_hours_wake_as_decide_gate_does(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    for p in regraded:
        woken = _decided(cases, p, GateMode.QUIET, GateBypass)
        answers = {c: row["requests"][GateMode.QUIET]["response"] for c, row in p.rows.items()}
        graded = {
            c for c, a in answers.items() if quiet_wakes(JevDecisionsResponse.model_validate(a))
        }
        assert graded == woken, p.run_id


def test_by_day_the_desk_gate_skips_no_needs_you_email_but_the_recorded_misses(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    skipped = _needs_you_skipped(cases, _passes(regraded, GateKind.SYSTEM), GateMode.DAY)
    assert skipped == RECORDED_DAY_FALSE_SKIPS


def test_by_day_the_holdout_loses_no_needs_you_email_in_any_pass(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    for p in _passes(regraded, GateKind.SYSTEM):
        assert (
            _decided(cases, p, GateMode.DAY, GateSkip, label="needs_you", split="holdout") == set()
        )


def test_by_day_a_thread_the_user_wrote_in_is_never_skipped(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    wrote = {c for c, case in cases.items() if case.setup.get(USER_WROTE_IN_THREAD)}
    assert wrote
    for p in _passes(regraded, GateKind.SYSTEM):
        assert _decided(cases, p, GateMode.DAY, GateSkip) & wrote == set(), p.run_id


@pytest.mark.parametrize("split", [None, "holdout"], ids=["all", "holdout"])
def test_by_day_the_desk_gate_skips_at_least_70_percent_of_noise_in_every_pass(
    cases: dict[str, Case], regraded: list[_Pass], split: str | None
) -> None:
    noise = [c for c in cases.values() if c.expected["label"] == "noise"]
    noise = [c for c in noise if split in (None, c.expected["split"])]
    for p in _passes(regraded, GateKind.SYSTEM):
        skipped = _decided(cases, p, GateMode.DAY, GateSkip, label="noise", split=split)
        assert len(skipped) / len(noise) >= NOISE_SKIP_FLOOR, p.run_id


def test_in_quiet_hours_only_the_service_down_emails_wake_the_user(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    urgent = {case_id for case_id, case in cases.items() if case.expected["urgent"]}
    assert urgent >= RECORDED_WAKES
    woken = [
        _decided(cases, p, GateMode.QUIET, GateBypass) for p in _passes(regraded, GateKind.SYSTEM)
    ]
    assert all(pass_woken <= RECORDED_WAKES for pass_woken in woken), woken
    assert set().union(*woken) == RECORDED_WAKES


def test_a_routine_sign_in_notice_never_wakes_the_desk(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    """Regression: an Infisical new-device login became an action todo on the Inbox desk."""
    notices = {c for c, case in cases.items() if SIGN_IN_NOTICE_TAG in case.tags}
    assert notices
    for p in _passes(regraded, GateKind.SYSTEM):
        assert notices - _decided(cases, p, GateMode.DAY, GateSkip) == set(), p.run_id
        assert notices & _decided(cases, p, GateMode.QUIET, GateBypass) == set(), p.run_id


def test_in_quiet_hours_no_needs_you_email_is_skipped_but_the_recorded_misses(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    skipped = _needs_you_skipped(cases, _passes(regraded, GateKind.SYSTEM), GateMode.QUIET)
    assert skipped == RECORDED_QUIET_FALSE_SKIPS


def test_authored_gates_skip_and_lose_only_the_recorded_needs_you_emails_the_desk_gate_runs(
    cases: dict[str, Case], regraded: list[_Pass]
) -> None:
    desk = _needs_you_skipped(cases, _passes(regraded, GateKind.SYSTEM), GateMode.DAY)
    authored = _needs_you_skipped(cases, _passes(regraded, GateKind.AUTHORED), GateMode.DAY)
    assert GateKind.AUTHORED in ENFORCED_GATE_KINDS
    assert authored - desk == RECORDED_AUTHORED_ONLY_FALSE_SKIPS


async def test_the_live_suite_journals_the_hash_of_the_request_it_sent_and_the_answer(
    cases: dict[str, Case],
) -> None:
    cfg = eval_config()
    sent: list[dict[str, object]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        urgent = {"type": "choice", "choice": "can_wait", "probabilities": {"can_wait": 1.0}}
        gate = {"type": "choice", "choice": "not_needed", "probabilities": {"not_needed": 0.99}}
        return httpx.Response(200, json={"answers": {"gate": gate, "urgent": urgent}})

    with trigger_gate_seams(KOLKATA, now=AFTERNOON) as seams:
        seams.jev.side_effect = answer
        run = await GateTransport().run(
            cases["mail-001"], cfg, EvalCostTracker(cfg.providers, 1.0), cfg.providers["fake"]
        )

    requests = (run.end_state or {})["requests"]
    assert [requests[mode]["request_sha"] for mode in GateMode] == [request_sha(b) for b in sent]
    assert requests[GateMode.DAY]["response"]["answers"]["gate"]["probabilities"] == {
        "not_needed": 0.99
    }
    assert (run.end_state or {})["outcome"] == "skip"


async def test_a_jev_outage_in_the_live_suite_is_a_provider_error_not_a_verdict(
    cases: dict[str, Case],
) -> None:
    cfg = eval_config()
    with trigger_gate_seams(KOLKATA, now=AFTERNOON) as seams:
        seams.jev.mock(return_value=httpx.Response(503))
        with pytest.raises(ProviderError, match="503"):
            await GateTransport().run(
                cases["mail-001"], cfg, EvalCostTracker(cfg.providers, 1.0), cfg.providers["fake"]
            )


def _quiet_run(case_id: str, *, can_wait: float) -> CaseRun:
    urgent = {"can_wait": can_wait, "service_down": 1 - can_wait}
    answer = {"type": "choice", "choice": "can_wait", "probabilities": urgent}
    asked = AskedRequest(request_sha="", response={"answers": {"urgent": answer}})
    fields = GateJournalFields(outcome="run", requests={GateMode.QUIET: asked})
    return CaseRun(case_id=case_id, end_state=dict(fields))


@pytest.mark.parametrize(
    ("case_id", "can_wait", "score"),
    [("mail-001", 0.0, 0.0), ("mail-001", 1.0, 1.0), ("mail-094", 0.0, 1.0)],
    ids=["noise-woken", "noise-held", "service-down-woken"],
)
def test_the_live_suite_fails_a_quiet_hours_wake_for_mail_that_can_wait(
    cases: dict[str, Case], case_id: str, can_wait: float, score: float
) -> None:
    assert cases[case_id].expected["urgent"] is (case_id == "mail-094")
    assert EXTRA["quiet_wake"](cases[case_id], _quiet_run(case_id, can_wait=can_wait)) == score


def test_a_live_case_with_no_quiet_hours_answer_fails_the_wake_gate(
    cases: dict[str, Case],
) -> None:
    assert EXTRA["quiet_wake"](cases["mail-094"], CaseRun(case_id="mail-094")) == 0.0


def _run_dir(tmp_path: Path, *end_states: GateJournalFields | None) -> Path:
    run_dir = tmp_path / "runs" / "trigger-gate-run"
    run_dir.mkdir(parents=True)
    rows = [
        {"case_id": f"mail-{i:03d}", "status": "passed" if es else "errored", "end_state": es}
        for i, es in enumerate(end_states, start=1)
    ]
    (run_dir / "journal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return run_dir


def test_recording_a_run_keeps_each_emails_gate_outcome_and_answers(tmp_path: Path) -> None:
    end_state = GateJournalFields(outcome="run", requests={})
    path = record(_run_dir(tmp_path, end_state), tmp_path / "recorded")
    assert read_recorded(path) == {"mail-001": {"case_id": "mail-001", **end_state}}


def test_a_run_with_an_unanswered_email_cannot_be_recorded(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path, {"outcome": "run", "requests": {}}, None)
    with pytest.raises(SystemExit, match="mail-002"):
        record(run_dir, tmp_path / "recorded")
