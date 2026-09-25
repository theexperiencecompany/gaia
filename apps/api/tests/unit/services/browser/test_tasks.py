"""Coverage for the browser-task history service's persistence functions.

record_browser_task, delete_browser_task and list_browser_tasks had no tests
at all. Frames and caption regression coverage lives in test_tasks_frames.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.constants.browser import BrowserSessionStatus
from app.models.browser_task_models import BrowserTaskDocument
from app.schemas.browser import BrowserResultSnapshot
from app.services.browser.tasks import (
    BrowserTaskRecord,
    delete_browser_task,
    list_browser_tasks,
    record_browser_task,
)


def _result(**kw: object) -> BrowserResultSnapshot:
    """Return a valid result snapshot, with any field overridden by kw."""
    return BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED,
        success=True,
        summary="done",
        steps=2,
        replay_url="https://cdn/replay.mp4",
    ).model_copy(update=kw)


def _doc(**kw: object) -> BrowserTaskDocument:
    """Return a valid task document, with any field overridden by kw."""
    return BrowserTaskDocument(
        user_id="u1",
        conversation_id="c1",
        task="find a keyboard",
        status=BrowserSessionStatus.COMPLETED,
        success=True,
        session_id="sess1",
        steps=1,
        step_goals=["Opening"],
        step_screenshots=["https://cdn/1.png"],
    ).model_copy(update=kw)


@pytest.mark.unit
async def test_record_browser_task_persists_every_field(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_create = AsyncMock(return_value=_doc())
    monkeypatch.setattr("app.services.browser.tasks.browser_task_repository.create", mock_create)

    await record_browser_task(
        BrowserTaskRecord(
            user_id="u1",
            conversation_id="c1",
            task="find a keyboard",
            session_id="sess1",
            source="telegram",
        ),
        _result(
            status=BrowserSessionStatus.FAILED,
            success=False,
            steps=4,
            replay_url="https://cdn/r.mp4",
        ),
        actions=17,
        step_goals=["Opening", "Typing"],
        step_screenshots=["https://cdn/1.png", ""],
    )

    saved = mock_create.await_args.args[0]
    assert saved.user_id == "u1"
    assert saved.conversation_id == "c1"
    assert saved.task == "find a keyboard"
    assert saved.session_id == "sess1"
    assert saved.status == BrowserSessionStatus.FAILED
    assert saved.success is False
    assert saved.steps == 4
    assert saved.actions == 17
    assert saved.step_goals == ["Opening", "Typing"]
    assert saved.step_screenshots == ["https://cdn/1.png", ""]
    assert saved.source == "telegram"
    assert saved.replay_url == "https://cdn/r.mp4"


@pytest.mark.unit
async def test_record_browser_task_defaults_goals_screenshots_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """step_goals and step_screenshots default to an empty list, not None, and source to an empty string."""
    mock_create = AsyncMock(return_value=_doc())
    monkeypatch.setattr("app.services.browser.tasks.browser_task_repository.create", mock_create)

    await record_browser_task(
        BrowserTaskRecord(
            user_id="u1",
            conversation_id="c1",
            task="find a keyboard",
            session_id="sess1",
        ),
        _result(),
        actions=0,
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
            created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
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
    assert first.created_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
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
