"""An expected value with a capital letter must not silently become unpassable.

Three capability projections lowercased only the value they read out of the
database and compared it against the raw YAML term, so any expectation carrying
an uppercase letter could never match no matter what the agent did:

* ``_matched_title`` — ``hard-compose-birthday-plan`` asserts a tracked todo
  titled ``"Sam's birthday"``. The agent created exactly that title and the case
  still scored ``end_state=0.0``.
* ``_project_reminders`` — same comparison for a reminder's payload title.
* ``answer_contains`` — ``fact in text.lower()``, so ``answer_contains: "Lisbon"``
  can never hold.

This is worse than a wrong answer: the run looks like an agent failure, and the
hard tier's numbers were reported that way. Both sides must be normalized.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.evals.core.types import Case
from scripts.evals.suites.capability import (
    _compute_end_state,
    _matched_title,
    _project_reminders,
)


class _Doc:
    """Stands in for a stored todo/tracked-todo document."""

    def __init__(self, title: str) -> None:
        self.title = title


def _case(end_state: dict[str, object]) -> Case:
    return Case(id="c", ticket="t", prompt="p", expected={"end_state": end_state})


def test_mixed_case_title_matches_the_stored_document() -> None:
    """The exact bug: the agent stored "Sam's birthday" and the gate said no."""
    docs = [_Doc("Sam's birthday")]
    match, matched_on = _matched_title(docs, "Sam's birthday", None)
    assert match is not None, "an exactly-correct title failed to match because of its capital S"
    assert matched_on == "Sam's birthday"


def test_mixed_case_title_still_rejects_a_different_document() -> None:
    """Mutation guard: normalizing case must not make every title match."""
    docs = [_Doc("Alex's birthday")]
    match, _ = _matched_title(docs, "Sam's birthday", None)
    assert match is None, "case normalization turned the title check into a pass-everything gate"


def test_title_match_ignores_surrounding_whitespace_on_both_sides() -> None:
    docs = [_Doc("  book the London flight  ")]
    match, _ = _matched_title(docs, "book the London flight", None)
    assert match is not None


async def test_answer_contains_is_case_insensitive() -> None:
    """A capitalized fact must be findable in the agent's prose."""
    projected = await _compute_end_state(
        _case({"answer_contains": "Lisbon"}), "user-1", "The capital of Portugal is Lisbon."
    )
    assert projected["answer_contains"] == "Lisbon", (
        "a correct answer failed because the expectation was capitalized"
    )


async def test_answer_contains_still_fails_when_the_fact_is_absent() -> None:
    """Mutation guard: the gate must still be able to fail."""
    projected = await _compute_end_state(
        _case({"answer_contains": "Lisbon"}), "user-1", "The capital of Portugal is Madrid."
    )
    assert projected["answer_contains"] == ""


async def test_reminder_title_match_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same asymmetry, same fix, on the reminder projection."""
    from app.services import reminder_service

    async def _list(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        del user_id, limit
        return [
            {
                "payload": {"title": "Order the cake"},
                "status": "scheduled",
                "scheduled_at": "2026-08-12 09:00:00",
            }
        ]

    monkeypatch.setattr(reminder_service.reminder_scheduler, "list_user_reminders", _list)

    matched = await _project_reminders("user-1", [{"title": "Order the cake"}])
    assert matched == [{"title": "Order the cake"}], "a correctly titled reminder did not match"

    missing = await _project_reminders("user-1", [{"title": "Book the venue"}])
    assert missing == [{"title": ""}], "reminder title matching stopped being able to fail"
