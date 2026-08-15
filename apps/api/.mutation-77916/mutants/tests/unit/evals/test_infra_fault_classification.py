"""An outage must abort the run and must leave the accuracy denominator.

Companion to ``test_infra_failure_not_graded``, which proves the run loop stops
when a suite *hand-wraps* a dead backend into ``InfraError``. That wrapper is the
weak point: LongMemEval wraps exactly one call, every other suite and backend
wraps none, so the same outage arriving from anywhere else was invisible.

The forensics behind these tests, read off the journals on disk: 157 records are
``failed`` while carrying an infrastructure fault, an empty transcript, no tool
calls, no scores and ~0.01s of duration — cases that never executed, averaged
into accuracy as wrong answers. 64 of them are the whole ``single-session-user``
category, published as 0/64 without one of those questions being asked, and 128
more are a gaia_bench run that kept going for 128 cases after the API it talks to
stopped accepting connections.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from scripts.evals.core import faults, runner as runner_mod
from scripts.evals.core.providers import EvalConfig
from scripts.evals.core.runner import RunOptions, Suite, run_suite
from scripts.evals.core.types import Case, CaseRun, InfraError

from tests.unit.evals.conftest import eval_config

CASE_COUNT = 5

# The exact string 74 LongMemEval records carry. It arrives as a bare
# RuntimeError from deep inside the memory engine — not from the one call the
# suite wrapped — which is precisely why nothing caught it.
POSTGRES_DOWN = "PostgreSQL engine not available"


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


class _RaisingSuite(Suite):
    """A suite whose transport raises whatever the test hands it."""

    name = "raising"
    project = "test-project"
    label = "Raising"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.attempts = 0

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        return _cases()

    async def transport(
        self, case: Case, cfg: EvalConfig, tracker: object, provider: object
    ) -> CaseRun:
        del case, cfg, tracker, provider
        self.attempts += 1
        raise self._exc

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case, run
        return {}


async def test_unwrapped_database_outage_aborts_instead_of_burning_the_suite(
    register_suite: Callable[[str, Suite], Suite],
) -> None:
    """A dead datastore reaching the loop unwrapped must stop the run at case 1.

    Recording these as ``errored`` keeps them out of accuracy, but it still lets
    the run march through every remaining case measuring the outage. Only the
    abort makes "an outage became a score" structurally impossible, and it must
    not depend on a suite author having wrapped the right call.
    """
    suite = _RaisingSuite(RuntimeError(POSTGRES_DOWN))
    register_suite("raising", suite)

    run_dir = await run_suite(eval_config(), RunOptions(suite="raising", no_finalize=True))
    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    records = journal.records()

    assert suite.attempts == 1, (
        f"the run called the dead backend {suite.attempts} times; an outage recognised only "
        "where a suite hand-wrapped it lets the whole suite burn against a dead database"
    )
    assert records == [], f"an outage was journaled as {len(records)} case record(s): {records}"

    meta = journal.load_meta()
    assert meta is not None
    assert meta.status == "aborted", f"run reported {meta.status!r}, hiding the outage"


async def test_an_outage_is_never_graded_and_never_counted(
    register_suite: Callable[[str, Suite], Suite],
) -> None:
    """No record may be ``failed``, and the accuracy denominator must be empty."""
    suite = _RaisingSuite(RuntimeError(POSTGRES_DOWN))
    register_suite("raising", suite)

    run_dir = await run_suite(eval_config(), RunOptions(suite="raising", no_finalize=True))

    from scripts.evals.core.report import _case_errored

    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    records = journal.records()

    assert [r for r in records if r.get("status") == "failed"] == [], (
        "an outage was graded as the agent answering wrongly"
    )
    graded = [r for r in records if not _case_errored(r)]
    assert graded == [], "a case that never ran entered the accuracy denominator"


async def test_a_harness_bug_still_errors_and_the_run_continues(
    register_suite: Callable[[str, Suite], Suite],
) -> None:
    """Mutation guard: classification must not turn every crash into an abort.

    Our own defects (a ``NameError`` in the runner, a bad provider key) are not
    outages. They must stay ``errored`` and let the rest of the suite run, or the
    abort becomes a way to hide harness bugs behind "the database was down".
    """
    suite = _RaisingSuite(NameError("name 'asyncio' is not defined"))
    register_suite("raising", suite)

    run_dir = await run_suite(eval_config(), RunOptions(suite="raising", no_finalize=True))
    journal = runner_mod.RunJournal(run_dir.parent, run_dir.name)
    records = journal.records()

    assert suite.attempts == CASE_COUNT, "a harness bug aborted the run"
    assert len(records) == CASE_COUNT
    assert all(r["status"] == "errored" for r in records)

    meta = journal.load_meta()
    assert meta is not None
    assert meta.status == "finished"


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError(POSTGRES_DOWN),
        RuntimeError("CannotConnectNowError: the database system is shutting down"),
        InfraError("postgres", POSTGRES_DOWN),
        OSError("Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432, 0, 0)"),
        BrokenPipeError(32, "Broken pipe"),
        RuntimeError('dev executor endpoint failed: HTTP 500: {"error":"internal_server_error"}'),
    ],
)
def test_real_journal_faults_are_recognised_as_outages(exc: Exception) -> None:
    """Every one of these was read off a journal record graded ``failed``."""
    fault = faults.classify(exc)
    assert fault is not None, f"{exc!r} would still be graded as a wrong answer"
    assert fault.backend


@pytest.mark.parametrize(
    ("message", "raised_by"),
    [
        ("PostgreSQL engine not available", "app/db/postgresql.py:147"),
        ("ChromaDB client not initialized", "app/db/chroma/chromadb.py:50"),
        ("ChromaDB client could not be initialized", "app/db/chroma/chromadb.py:44"),
        ("ChromaDB connection failed: timed out", "app/db/chroma/chromadb.py:285"),
        ("Failed to establish RabbitMQ connection", "app/db/rabbitmq.py:85"),
    ],
)
def test_the_datastore_messages_the_app_actually_raises_are_recognised(
    message: str, raised_by: str
) -> None:
    """Each signature is copied from a real ``raise`` — none of them is invented.

    An entry that matches nothing the app can emit is worse than no entry: it
    reads as coverage while never firing. These strings are matched against
    another module's wording, so if that wording changes this test is what says
    so rather than an outage quietly being graded again.
    """
    assert faults.classify(RuntimeError(message)) is not None, (
        f"the fault raised at {raised_by} is not recognised as an outage"
    )


@pytest.mark.parametrize(
    "exc",
    [
        NameError("name 'asyncio' is not defined"),
        KeyError("Provider 'tool_registry' not found in registry"),
        TypeError("object LazyLoader can't be used in 'await' expression"),
        ValueError("Invalid preferred_provider 'opencode'"),
        AssertionError("the agent booked the wrong room"),
    ],
)
def test_our_own_bugs_are_not_mistaken_for_outages(exc: Exception) -> None:
    """The classifier must stay narrow, or it hides harness defects as outages."""
    assert faults.classify(exc) is None, f"{exc!r} was misread as an infrastructure outage"


def _never_ran_record(error: str) -> dict[str, Any]:
    """The exact shape of all 157 contaminated records."""
    return {
        "case_id": "lme-x",
        "status": "failed",
        "error": error,
        "text": "",
        "messages": [],
        "tool_calls": [],
        "scores": {},
        "duration_s": 0.01,
    }


def test_a_record_with_a_fault_and_no_transcript_never_ran() -> None:
    assert faults.never_conducted(_never_ran_record(f"RuntimeError: {POSTGRES_DOWN}"))
    # Not every un-conducted case is an outage we anticipated; the record shape
    # is what proves it, so our own crashes are caught by the same rule.
    assert faults.never_conducted(_never_ran_record("NameError: name 'asyncio' is not defined"))


def test_a_record_with_no_fault_is_never_touched() -> None:
    """The error field is the gate. Without one, the case reached a real verdict."""
    assert not faults.never_conducted(dict(_never_ran_record(""), error=None))
    assert not faults.never_conducted(dict(_never_ran_record(""), error=""))


@pytest.mark.parametrize(
    ("evidence", "value"),
    [
        ("text", "The meeting is on Tuesday."),
        ("messages", [{"role": "assistant", "content": "Tuesday"}]),
        ("tool_calls", [{"name": "search_memory", "args": {}}]),
        ("scores", {"gaia_exact": 0.0}),
    ],
)
def test_any_single_piece_of_evidence_means_the_case_ran(evidence: str, value: object) -> None:
    """Each clause must be independently load-bearing, or the rule is too eager.

    ``scores`` is the subtle one: a case can be graded 0.0 and still have hit a
    fault on the way out, and a re-grade that erased it would be laundering real
    failures instead of correcting an outage — the opposite defect, and a much
    harder one to notice because the number moves the flattering way.
    """
    record = _never_ran_record(f"RuntimeError: {POSTGRES_DOWN}")
    record[evidence] = value
    assert not faults.never_conducted(record), (
        f"a record carrying {evidence} was written off as never having run"
    )


def test_a_real_wrong_answer_is_never_called_un_conducted() -> None:
    """Mutation guard: the re-grade must not quietly erase genuine failures."""
    graded_wrong = _never_ran_record("gate score below threshold")
    graded_wrong |= {
        "text": "The meeting is on Tuesday.",
        "messages": [{"role": "assistant", "content": "The meeting is on Tuesday."}],
        "scores": {"gaia_exact": 0.0},
        "duration_s": 12.4,
    }
    assert not faults.never_conducted(graded_wrong)

    passing = dict(graded_wrong, status="passed", error=None, scores={"gaia_exact": 1.0})
    assert not faults.never_conducted(passing)


def test_a_case_that_errored_after_answering_keeps_its_evidence() -> None:
    """A crash mid-way through a case still has a transcript worth reading."""
    record = _never_ran_record("TimeoutError: ")
    record |= {"messages": [{"role": "assistant", "content": "partial"}], "duration_s": 420.0}
    assert not faults.never_conducted(record)
