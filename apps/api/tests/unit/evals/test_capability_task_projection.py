"""The capability tasks end_state: notes_contains reads notes.md only, and assignee narrows.

The old projection matched canvas and activity text combined, so an agent writing a
fact anywhere but the canvas still passed canvas cases; notes_contains keeps that
separation for a GAIA task's notes.md.
"""

from __future__ import annotations

import pytest
from scripts.evals.suites.capability import _project_tasks

from app.constants.tasks import Assignee
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument, TaskPage, TaskQuery


def _gaia_task(title: str, *, body: str = "", notes: str | None = None) -> TaskDocument:
    return TaskDocument(
        user_id="user-1", title=title, body=body, assignee=Assignee.GAIA, notes=notes
    )


def _todo(title: str, *, completed: bool = False) -> TaskDocument:
    return TaskDocument(user_id="user-1", title=title, assignee=Assignee.USER, completed=completed)


async def _project(
    monkeypatch: pytest.MonkeyPatch, tasks: list[TaskDocument], want: list[object]
) -> list[dict[str, object]]:
    async def _list_page(*, user_id: str, query: TaskQuery) -> TaskPage:
        del user_id, query
        return TaskPage(items=tasks, total=len(tasks))

    monkeypatch.setattr(task_repository, "list_page", _list_page)
    return await _project_tasks("user-1", want)


async def test_notes_contains_matches_the_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = await _project(
        monkeypatch,
        [_gaia_task("Campervan MOT", notes="## Key Details\nMOT runs out in November")],
        [{"title_contains": "campervan", "notes_contains": "november"}],
    )
    assert entries[0]["notes_contains"] == "november"


async def test_notes_contains_ignores_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fact in the task's details, not its notes, must not satisfy a notes claim."""
    entries = await _project(
        monkeypatch,
        [_gaia_task("Campervan MOT", body="MOT runs out in November", notes="## Key Details\n")],
        [{"title_contains": "campervan", "notes_contains": "november"}],
    )
    assert entries[0]["notes_contains"] is None


async def test_text_contains_reads_the_body_too(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = await _project(
        monkeypatch,
        [_gaia_task("Berlin move", body="international relocation")],
        [{"title_contains": "berlin", "text_contains": "relocation"}],
    )
    assert entries[0]["text_contains"] == "relocation"


async def test_assignee_narrows_the_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """A to-do with the right title must not stand in for the GAIA task the case asked for."""
    entries = await _project(
        monkeypatch,
        [_todo("Renew passport")],
        [{"title_contains": "passport", "assignee": "gaia"}],
    )
    assert entries[0] == {"title_contains": None, "assignee": None}


async def test_count_by_assignee_leaves_out_system_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = _gaia_task("Daily briefing")
    system.system_key = "daily_briefing"
    entries = await _project(
        monkeypatch,
        [_todo("Buy milk"), _todo("Call mum", completed=True), _gaia_task("Visa"), system],
        [{"count": 2, "assignee": "user"}, {"count": 1, "assignee": "gaia"}, {"count": 3}],
    )
    assert entries == [
        {"count": 2, "assignee": "user"},
        {"count": 1, "assignee": "gaia"},
        {"count": 3},
    ]
