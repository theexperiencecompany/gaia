"""Which cases a run actually executes.

``--only-failed`` shipped selecting zero cases in both of its modes — it ran
after ``--resume`` had already dropped every finished case, and without
``--resume`` it read a journal that did not exist yet. It printed "cases=0" and
exited 0 either way, so every retry since has silently been a full re-run.
Selection is therefore pinned here, against a real journal on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.evals.core.journal import RunJournal
from scripts.evals.core.runner import RunOptions, select_cases
from scripts.evals.core.types import Case


def _cases(*ids: str) -> list[Case]:
    return [Case(id=case_id, ticket="t", prompt="p") for case_id in ids]


def _journal(tmp_path: Path, outcomes: dict[str, str]) -> RunJournal:
    journal = RunJournal(tmp_path, "run-1")
    for case_id, status in outcomes.items():
        journal.append({"case_id": case_id, "status": status})
    return journal


def _ids(cases: list[Case]) -> list[str]:
    return [c.id for c in cases]


def test_only_failed_selects_exactly_the_failed_cases(tmp_path: Path) -> None:
    journal = _journal(tmp_path, {"a": "passed", "b": "failed", "c": "errored", "d": "failed"})
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True)
    assert _ids(select_cases(_cases("a", "b", "c", "d"), opts, journal)) == ["b", "d"]


def test_only_failed_does_not_silently_select_nothing(tmp_path: Path) -> None:
    """The defect's signature: a retry that runs zero cases and exits happy."""
    journal = _journal(tmp_path, {"a": "passed", "b": "failed"})
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True)
    assert select_cases(_cases("a", "b"), opts, journal)


def test_only_failed_ignores_errored_cases(tmp_path: Path) -> None:
    """An errored case never produced an answer, so there is no verdict to retry
    — ``--resume`` already picks those up."""
    journal = _journal(tmp_path, {"a": "errored"})
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True)
    with pytest.raises(SystemExit, match="no failed cases"):
        select_cases(_cases("a"), opts, journal)


def test_only_failed_without_a_journal_fails_loudly(tmp_path: Path) -> None:
    opts = RunOptions(suite="demo", only_failed=True)
    with pytest.raises(SystemExit, match="pass --resume"):
        select_cases(_cases("a", "b"), opts, RunJournal(tmp_path, "fresh"))


def test_only_failed_re_reads_the_latest_attempt(tmp_path: Path) -> None:
    """The journal only appends, so a case retried and fixed must not be picked
    up again from its stale failure."""
    journal = _journal(tmp_path, {"a": "failed", "b": "failed"})
    journal.append({"case_id": "a", "status": "passed"})
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True)
    assert _ids(select_cases(_cases("a", "b"), opts, journal)) == ["b"]


def test_resume_alone_skips_only_terminal_cases(tmp_path: Path) -> None:
    journal = _journal(tmp_path, {"a": "passed", "b": "failed", "c": "errored"})
    opts = RunOptions(suite="demo", resume="run-1")
    assert _ids(select_cases(_cases("a", "b", "c", "d"), opts, journal)) == ["c", "d"]


def test_only_rejects_an_unknown_case_id(tmp_path: Path) -> None:
    opts = RunOptions(suite="demo", only=["a", "typo"])
    with pytest.raises(SystemExit, match="typo"):
        select_cases(_cases("a", "b"), opts, RunJournal(tmp_path, "run-1"))


def test_limit_applies_after_journal_selection(tmp_path: Path) -> None:
    journal = _journal(tmp_path, {"a": "failed", "b": "passed", "c": "failed"})
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True, limit=1)
    assert _ids(select_cases(_cases("a", "b", "c"), opts, journal)) == ["a"]


def test_the_journal_on_disk_is_what_is_read(tmp_path: Path) -> None:
    """A second process reading the same run must see the same selection."""
    _journal(tmp_path, {"a": "failed", "b": "passed"})
    reopened = RunJournal(tmp_path, "run-1")
    assert json.loads((tmp_path / "run-1" / "journal.jsonl").read_text().splitlines()[0])
    opts = RunOptions(suite="demo", resume="run-1", only_failed=True)
    assert _ids(select_cases(_cases("a", "b"), opts, reopened)) == ["a"]
