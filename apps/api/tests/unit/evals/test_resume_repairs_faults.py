"""A run contaminated by an outage has to be repairable.

The publish gate now refuses a run whose `failed` records never actually ran.
That verdict is only useful if it can be worked off: `failed` is a terminal
status, so `--resume` used to skip exactly the cases that needed re-running, and
the journal is append-only so the record cannot be edited. The run was stuck —
blocked from publishing, unable to be repaired, re-run from scratch or nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.evals.core.journal import RunJournal
from scripts.evals.core.runner import RunOptions, select_cases
from scripts.evals.core.types import Case


def _never_ran(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "failed",
        "text": "",
        "messages": [],
        "tool_calls": [],
        "scores": {},
        "tokens": {"input": 0, "output": 0},
        "duration_s": 0.01,
        "error": "RuntimeError: PostgreSQL engine not available",
    }


def _answered_wrongly(case_id: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "failed",
        "text": "Berlin",
        "messages": [{"role": "assistant", "content": "Berlin"}],
        "tool_calls": [],
        "scores": {"gaia_exact": 0.0},
        "tokens": {"input": 12000, "output": 40},
        "duration_s": 18.0,
        "error": None,
    }


def test_a_case_that_never_ran_is_picked_back_up_by_resume(tmp_path: Path) -> None:
    journal = RunJournal(tmp_path, "run-1")
    journal.append(_never_ran("outage"))
    assert not journal.has_terminal("outage")


def test_a_case_that_answered_wrongly_stays_done(tmp_path: Path) -> None:
    """A real miss is a verdict. Re-running it on resume would erase the finding."""
    journal = RunJournal(tmp_path, "run-1")
    journal.append(_answered_wrongly("wrong"))
    assert journal.has_terminal("wrong")


def test_resume_selects_the_outage_and_leaves_the_verdicts(tmp_path: Path) -> None:
    journal = RunJournal(tmp_path, "run-1")
    journal.append(_answered_wrongly("wrong"))
    journal.append(_never_ran("outage"))
    journal.append({"case_id": "good", "status": "passed", "text": "Paris", "scores": {"g": 1.0}})
    opts = RunOptions(suite="demo", resume="run-1")
    cases = [Case(id=cid, ticket="t", prompt="p") for cid in ("wrong", "outage", "good")]
    assert [c.id for c in select_cases(cases, opts, journal)] == ["outage"]


def test_a_repaired_case_is_terminal_again(tmp_path: Path) -> None:
    """The journal appends, so the re-run's real record supersedes the fault."""
    journal = RunJournal(tmp_path, "run-1")
    journal.append(_never_ran("outage"))
    journal.append(_answered_wrongly("outage"))
    assert journal.has_terminal("outage")
