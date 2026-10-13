"""canvas_contains must read canvas.md only; activity_contains reads activity.md only.

_canvas text and activity text used to be matched combined, so an agent writing
canvas content into activity.md still passed canvas cases — a broken gate that
read as agent competence.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from scripts.evals.suites.capability import _project_tracked_todos


def _doc(canvas: str | None, activity: str | None) -> SimpleNamespace:
    return SimpleNamespace(title="Campervan", canvas_content=canvas, activity_content=activity)


async def _project(
    monkeypatch: pytest.MonkeyPatch, doc: SimpleNamespace, want: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from app.db.repositories.todos import todo_repository

    async def _list(user_id: str, limit: int = 100) -> list[SimpleNamespace]:
        del user_id, limit
        return [doc]

    monkeypatch.setattr(todo_repository, "list_active_tracked", _list)
    return await _project_tracked_todos("user-1", want)


async def test_canvas_contains_matches_canvas_content(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = await _project(
        monkeypatch,
        _doc("MOT runs out in November", "scheduled run finished"),
        [{"title_contains": "campervan", "canvas_contains": "november"}],
    )
    assert entries[0]["canvas_contains"] == "november"


async def test_canvas_contains_ignores_activity_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug: the term lived only in activity.md and still satisfied the gate."""
    entries = await _project(
        monkeypatch,
        _doc("unrelated canvas", "MOT runs out in November"),
        [{"title_contains": "campervan", "canvas_contains": "november"}],
    )
    assert entries[0]["canvas_contains"] is None


async def test_activity_contains_matches_activity_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = await _project(
        monkeypatch,
        _doc("unrelated canvas", "scheduled run finished"),
        [{"title_contains": "campervan", "activity_contains": "finished"}],
    )
    assert entries[0]["activity_contains"] == "finished"


async def test_activity_contains_ignores_canvas_content(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = await _project(
        monkeypatch,
        _doc("MOT runs out in November", "scheduled run finished"),
        [{"title_contains": "campervan", "activity_contains": "november"}],
    )
    assert entries[0]["activity_contains"] is None
