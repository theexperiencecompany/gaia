"""Regression: history rebuilt recap URLs it never checked existed.

`_frames` derived `{R2}/browser_steps/{session}/step_{i}.png` for every step, so
a step whose screenshot upload failed still produced a row in Settings → Browser
pointing at a 404 — a permanently broken thumbnail.
"""

from __future__ import annotations

import pytest

from app.constants.browser import BrowserSessionStatus
from app.models.browser_task_models import BrowserTaskDocument
from app.services.browser.tasks import _frames


def _doc(**kw: object) -> BrowserTaskDocument:
    base: dict[str, object] = {
        "user_id": "u1",
        "conversation_id": "c1",
        "task": "find a keyboard",
        "status": BrowserSessionStatus.COMPLETED,
        "success": True,
        "session_id": "sess1",
        "steps": 3,
        "step_goals": ["Opening", "Typing", "Reading"],
    }
    base.update(kw)
    return BrowserTaskDocument(**base)  # type: ignore[arg-type]


@pytest.mark.unit
@pytest.mark.regression
def test_a_step_whose_upload_failed_has_no_frame() -> None:
    doc = _doc(step_screenshots=["https://cdn/1.png", "", "https://cdn/3.png"])

    frames = _frames(doc)

    assert [f.url for f in frames] == ["https://cdn/1.png", "https://cdn/3.png"]


@pytest.mark.unit
@pytest.mark.regression
def test_no_frames_at_all_when_every_upload_failed() -> None:
    assert _frames(_doc(step_screenshots=["", "", ""])) == []


@pytest.mark.unit
def test_captions_follow_the_surviving_frames() -> None:
    doc = _doc(step_screenshots=["https://cdn/1.png", "https://cdn/2.png", ""])

    assert [f.caption for f in _frames(doc)] == ["Opening", "Typing"]


@pytest.mark.unit
def test_older_tasks_without_stored_urls_still_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows recorded before the URLs were stored must keep working."""
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    frames = _frames(_doc(step_screenshots=[]))

    assert [f.url for f in frames] == [
        "https://cdn/browser_steps/sess1/step_1.png",
        "https://cdn/browser_steps/sess1/step_2.png",
        "https://cdn/browser_steps/sess1/step_3.png",
    ]
