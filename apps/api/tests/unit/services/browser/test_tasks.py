"""Coverage for the browser-task history service's persistence functions.

`record_browser_task`, `delete_browser_task`, and `list_browser_tasks` had no
tests at all — every mutation on their lines survived silently because
nothing ever exercised the module. `_frames`/`_caption` regression coverage
lives in ``test_tasks_frames.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.constants.browser import BrowserSessionStatus
from app.models.browser_task_models import BrowserTaskDocument
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.tasks import (
    delete_browser_task,
    list_browser_tasks,
    record_browser_task,
)


def _result(**kw: object) -> BrowserResultSnapshot:
    base: dict[str, object] = {
        "status": BrowserSessionStatus.COMPLETED,
        "success": True,
        "summary": "done",
        "steps": 2,
        "replay_url": "https://cdn/replay.mp4",
    }
    base.update(kw)
    return BrowserResultSnapshot(**base)  # type: ignore[arg-type]


def _doc(**kw: object) -> BrowserTaskDocument:
    base: dict[str, object] = {
        "user_id": "u1",
        "conversation_id": "c1",
        "task": "find a keyboard",
        "status": BrowserSessionStatus.COMPLETED,
        "success": True,
        "session_id": "sess1",
        "steps": 1,
        "step_goals": ["Opening"],
        "step_screenshots": ["https://cdn/1.png"],
    }
    base.update(kw)
    return BrowserTaskDocument(**base)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_record_browser_task_persists_every_field(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_create = AsyncMock(return_value=_doc())
    monkeypatch.setattr("app.services.browser.tasks.browser_task_repository.create", mock_create)

    await record_browser_task(
        user_id="u1",
        conversation_id="c1",
        task="find a keyboard",
        session_id="sess1",
        result=_result(
            status=BrowserSessionStatus.FAILED,
            success=False,
            steps=4,
            replay_url="https://cdn/r.mp4",
        ),
        step_goals=["Opening", "Typing"],
        step_screenshots=["https://cdn/1.png", ""],
        source="telegram",
    )

    saved = mock_create.await_args.args[0]
    assert saved.user_id == "u1"
    assert saved.conversation_id == "c1"
    assert saved.task == "find a keyboard"
    assert saved.session_id == "sess1"
    assert saved.status == BrowserSessionStatus.FAILED
    assert saved.success is False
    assert saved.steps == 4
    assert saved.step_goals == ["Opening", "Typing"]
    assert saved.step_screenshots == ["https://cdn/1.png", ""]
    assert saved.source == "telegram"
    assert saved.replay_url == "https://cdn/r.mp4"


@pytest.mark.unit
async def test_record_browser_task_defaults_goals_screenshots_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`step_goals`/`step_screenshots` default to `[]`, not `None`, and `source` to `""`."""
    mock_create = AsyncMock(return_value=_doc())
    monkeypatch.setattr("app.services.browser.tasks.browser_task_repository.create", mock_create)

    await record_browser_task(
        user_id="u1",
        conversation_id="c1",
        task="find a keyboard",
        session_id="sess1",
        result=_result(),
    )

    saved = mock_create.await_args.args[0]
    assert saved.step_goals == []
    assert saved.step_screenshots == []
    assert saved.source == ""


@pytest.mark.unit
async def test_delete_browser_task_scopes_by_user_and_returns_repository_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_delete = AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.browser.tasks.browser_task_repository.delete", mock_delete)

    deleted = await delete_browser_task("u1", "task-123")

    assert deleted is True
    mock_delete.assert_awaited_once_with("task-123", user_id="u1")


@pytest.mark.unit
async def test_delete_browser_task_returns_false_when_repository_reports_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.browser.tasks.browser_task_repository.delete", AsyncMock(return_value=False)
    )

    assert await delete_browser_task("u1", "missing") is False


@pytest.mark.unit
async def test_list_browser_tasks_maps_every_field_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = [
        _doc(
            id="a",
            task="first",
            steps=1,
            step_goals=["Opening"],
            step_screenshots=["https://cdn/1.png"],
            source="web",
        ),
        _doc(
            id="b",
            task="second",
            status=BrowserSessionStatus.FAILED,
            success=False,
            steps=0,
            step_goals=[],
            step_screenshots=[],
        ),
    ]
    mock_list = AsyncMock(return_value=docs)
    monkeypatch.setattr(
        "app.services.browser.tasks.browser_task_repository.list_recent_for_user", mock_list
    )

    results = await list_browser_tasks("u1", limit=7)

    mock_list.assert_awaited_once_with("u1", limit=7)
    assert [r.id for r in results] == ["a", "b"]
    first, second = results
    assert first.task == "first"
    assert first.status == BrowserSessionStatus.COMPLETED
    assert first.success is True
    assert first.steps == 1
    assert first.conversation_id == "c1"
    assert first.source == "web"
    assert [f.url for f in first.frames] == ["https://cdn/1.png"]
    assert second.status == BrowserSessionStatus.FAILED
    assert second.success is False
    assert second.frames == []


@pytest.mark.unit
async def test_list_browser_tasks_uses_the_caller_supplied_limit_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_list = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.services.browser.tasks.browser_task_repository.list_recent_for_user", mock_list
    )

    await list_browser_tasks("u1")

    mock_list.assert_awaited_once_with("u1", limit=20)
