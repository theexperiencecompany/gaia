"""An unavailable backend must abort the run, never be graded as a wrong answer.

Regression cover for the LongMemEval run in which PostgreSQL shut down mid-run:
every remaining case raised ``RuntimeError: PostgreSQL engine not available`` in
~0.01s, the run loop journaled each one as a ``failed`` case, and the report
turned 64 never-asked questions into ``single-session-user 0/64``. An
infrastructure outage must never be published as a quality score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scripts.evals.core import runner as runner_mod
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import RunOptions, Suite, run_suite
from scripts.evals.core.types import Case, CaseRun, InfraError, ProviderHealth

CASE_COUNT = 5


def _config() -> EvalConfig:
    provider = ProviderConfig(
        name="fake",
        lane="custom",
        base_url="http://localhost:9",
        api_key="test-key",
        model="fake-model",
        budget_usd=1.0,
        price_in_per_1m=0.0,
        price_out_per_1m=0.0,
    )
    return EvalConfig(
        providers={"fake": provider},
        rotation_order=["fake"],
        default_max_usd=1.0,
        judge={"base_url_env": "X", "api_key_env": "Y"},
    )


def _cases() -> list[Case]:
    return [
        Case(
            id=f"case-{i}",
            ticket=f"ticket {i}",
            prompt="q?",
            expected={"category": "single-session-user", "score": {"gates": ["gaia_exact"]}},
            tags=["single-session-user"],
        )
        for i in range(CASE_COUNT)
    ]


class _DeadBackendSuite(Suite):
    """Stands in for any suite whose datastore has gone away mid-run."""

    name = "dead-backend"
    project = "test-project"
    label = "Dead Backend"

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self.attempts = 0

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        return _cases()

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: object, provider: object
    ) -> CaseRun:
        del case, cfg, tracker, provider
        self.attempts += 1
        raise InfraError("postgres", "PostgreSQL engine not available")

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case, run
        return {}


@pytest.fixture
def isolated_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _DeadBackendSuite:
    """Point the run loop at a temp runs dir with no network and no Opik."""
    suite = _DeadBackendSuite(_config())
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
    monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
    monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_flush_traces", lambda *a, **k: None)
    monkeypatch.setitem(runner_mod.SUITE_REGISTRY, "dead-backend", lambda cfg: suite)
    return suite


async def test_dead_backend_aborts_the_run_instead_of_grading_every_case(
    isolated_runner: _DeadBackendSuite,
) -> None:
    """The run must stop at the first infra failure, not march through the suite."""
    suite = isolated_runner
    run_dir = await run_suite(_config(), RunOptions(suite="dead-backend", no_finalize=True))

    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    records = journal.records()

    # The bug: all CASE_COUNT cases were journaled as `failed`, in milliseconds,
    # without a single question being asked.
    assert records == [], f"infra outage was graded as {len(records)} failed cases: {records}"
    assert suite.attempts == 1, (
        f"run kept calling the dead backend {suite.attempts} times instead of stopping"
    )

    meta = journal.load_meta()
    assert meta is not None
    assert meta.status == "aborted", f"run reported status {meta.status!r}, hiding the outage"


async def test_aborted_run_publishes_no_category_accuracy(
    isolated_runner: _DeadBackendSuite,
) -> None:
    """No journal records means the report cannot invent a 0% for the category."""
    del isolated_runner
    run_dir = await run_suite(_config(), RunOptions(suite="dead-backend", no_finalize=True))

    from scripts.evals.core.report import _case_passed

    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    per_category: dict[str, list[float]] = {}
    for record in journal.records():
        category = record.get("category")
        if category:
            per_category.setdefault(category, []).append(1.0 if _case_passed(record) else 0.0)

    assert per_category == {}, (
        f"report would publish a fabricated score for a run that never ran: {per_category}"
    )


class _LiveBackendSuite(_DeadBackendSuite):
    """Control: a healthy suite must still run and grade every case."""

    name = "live-backend"

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: object, provider: object
    ) -> CaseRun:
        del cfg, tracker, provider
        self.attempts += 1
        return CaseRun(case_id=case.id, text="an answer", end_state={"gaia_exact": 1.0})

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case
        return {"gaia_exact": float((run.end_state or {}).get("gaia_exact", 0.0))}


async def test_healthy_suite_still_grades_every_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation guard: the abort path must not swallow ordinary runs."""
    suite = _LiveBackendSuite(_config())
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
    monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
    monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_flush_traces", lambda *a, **k: None)
    monkeypatch.setitem(runner_mod.SUITE_REGISTRY, "live-backend", lambda cfg: suite)

    run_dir = await run_suite(_config(), RunOptions(suite="live-backend", no_finalize=True))
    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    records = journal.records()

    assert len(records) == CASE_COUNT
    assert all(r["status"] == "passed" for r in records)
    meta = journal.load_meta()
    assert meta is not None
    assert meta.status == "finished"


class _MixedSuite(_DeadBackendSuite):
    """A crash, a timeout, a wrong answer, and two correct ones.

    The two non-answers must not be averaged in with the wrong answer — only the
    wrong answer says anything about the agent's quality. The crash and the
    timeout reach the run loop by different routes (a raised exception vs a
    CaseRun carrying ``error``), and both must land on ``errored``.
    """

    name = "mixed"

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: object, provider: object
    ) -> CaseRun:
        del cfg, tracker, provider
        self.attempts += 1
        if case.id == "case-0":
            raise RuntimeError("transient boom")
        if case.id == "case-3":
            return CaseRun(case_id=case.id, error="question timed out after 420s")
        correct = 0.0 if case.id == "case-1" else 1.0
        return CaseRun(case_id=case.id, text="answer", end_state={"gaia_exact": correct})

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case
        return {"gaia_exact": float((run.end_state or {}).get("gaia_exact", 0.0))}


async def test_a_crash_is_recorded_as_errored_not_as_a_wrong_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed case must not be scored, and must not dilute the accuracy."""
    suite = _MixedSuite(_config())
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(runner_mod, "health_check", lambda p: ProviderHealth(True))
    monkeypatch.setattr(runner_mod, "pin_settings", lambda p: None)
    monkeypatch.setattr(runner_mod, "_log_trace", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_flush_traces", lambda *a, **k: None)
    monkeypatch.setitem(runner_mod.SUITE_REGISTRY, "mixed", lambda cfg: suite)

    run_dir = await run_suite(_config(), RunOptions(suite="mixed", no_finalize=True))
    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    by_id = {r["case_id"]: r for r in journal.records()}

    assert by_id["case-0"]["status"] == "errored", "a crash was graded as a wrong answer"
    assert by_id["case-3"]["status"] == "errored", "a timeout was graded as a wrong answer"
    assert by_id["case-1"]["status"] == "failed"
    assert by_id["case-2"]["status"] == "passed"

    # A graded-but-wrong case is not an error, so it must carry no error text.
    assert by_id["case-1"]["error"] is None, "a wrong answer was labelled an error"
    assert by_id["case-0"]["error"]

    # No phantom scores: an unanswered case must not feed the metric averages.
    assert by_id["case-0"]["scores"] == {}
    assert by_id["case-3"]["scores"] == {}, "a timeout contributed a 0.0 to the metrics"

    from scripts.evals.core.report import _case_errored, _case_passed

    graded = [r for r in journal.records() if not _case_errored(r)]
    passed = [r for r in graded if _case_passed(r)]
    assert len(graded) == CASE_COUNT - 2, "a non-answer was counted in the denominator"
    assert len(passed) / len(graded) == pytest.approx(2 / 3)


async def test_errored_cases_are_retried_on_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An error is not a verdict, so --resume must pick the case back up."""
    monkeypatch.setattr(runner_mod, "RUNS_DIR", tmp_path / "runs")
    journal = runner_mod.RunJournal(tmp_path / "runs", "run-1")
    journal.append({"case_id": "case-0", "status": "errored"})
    journal.append({"case_id": "case-1", "status": "failed"})
    journal.append({"case_id": "case-2", "status": "passed"})

    assert journal.has_terminal("case-1")
    assert journal.has_terminal("case-2")
    assert not journal.has_terminal("case-0"), "an errored case was frozen into the run"

    # Re-reading from disk must reach the same conclusion.
    reloaded = runner_mod.RunJournal(tmp_path / "runs", "run-1")
    assert not reloaded.has_terminal("case-0")
    assert reloaded.has_terminal("case-2")


async def test_longmemeval_reports_infra_error_when_postgres_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suite must translate a dead datastore into InfraError, not a 0 score.

    Without this the transport returns/raises a plain RuntimeError, which the run
    loop grades as the agent answering wrongly.
    """
    from scripts.evals.suites import longmemeval as suite_mod

    from app.db import postgresql

    async def _dead_engine() -> Any:
        raise RuntimeError("PostgreSQL engine not available")

    monkeypatch.setattr(postgresql, "get_postgresql_engine", _dead_engine)

    suite = suite_mod.LongMemEvalSuite(_config())
    suite._backend_ready = True  # skip registration; the outage is what's under test
    case = _cases()[0]

    with pytest.raises(InfraError) as excinfo:
        await suite.transport(case, _config(), tracker=None, provider=None)

    assert "postgres" in str(excinfo.value).lower()


def test_a_provider_disconnect_is_not_an_api_outage() -> None:
    """httpx.RemoteProtocolError's TYPE cannot say which peer dropped: the
    remote LLM gateway's hiccup looks identical to our API dying. Three
    LongMemEval runs aborted on a healthy API before the accused backend was
    probed. A transport fault with a healthy API is a retryable case error."""
    from unittest.mock import MagicMock, patch

    import httpx
    from scripts.evals.core import faults

    fault = faults.classify(httpx.RemoteProtocolError("Server disconnected"))
    assert fault is not None and fault.backend == "api"

    healthy = MagicMock(status_code=200)
    with patch.object(faults.httpx, "get", return_value=healthy):
        assert faults.confirmed_down(fault) is False

    with patch.object(faults.httpx, "get", side_effect=httpx.ConnectError("down")):
        assert faults.confirmed_down(fault) is True

    # Signature-matched faults name their backend unambiguously — never probed.
    postgres = faults.classify(RuntimeError("PostgreSQL engine not available"))
    assert postgres is not None
    assert faults.confirmed_down(postgres) is True
