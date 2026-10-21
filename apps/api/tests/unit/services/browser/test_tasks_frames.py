"""Regression: history rebuilt recap URLs it never checked existed.

_frames derived a step image URL for every step, so a step whose screenshot
upload failed still produced a row in Settings, Browser pointing at a 404: a
permanently broken thumbnail.
"""

from __future__ import annotations

import pytest

from app.constants.browser import BrowserSessionStatus
from app.models.browser_task_models import BrowserTaskDocument
from app.services.browser.tasks import _caption, _frames


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
    return BrowserTaskDocument(**base)  # type: ignore[arg-type]  # unpacks a dict[str, object] kwargs bag into the typed BrowserTaskDocument fields


@pytest.mark.unit
def test_a_step_whose_upload_failed_has_no_frame() -> None:
    doc = _doc(step_screenshots=["https://cdn/1.png", "", "https://cdn/3.png"])

    frames = _frames(doc)

    assert [f.url for f in frames] == ["https://cdn/1.png", "https://cdn/3.png"]


@pytest.mark.unit
def test_no_frames_at_all_when_every_upload_failed() -> None:
    assert _frames(_doc(step_screenshots=["", "", ""])) == []


@pytest.mark.unit
def test_captions_follow_the_surviving_frames() -> None:
    doc = _doc(step_screenshots=["https://cdn/1.png", "https://cdn/2.png", ""])

    assert [f.caption for f in _frames(doc)] == ["Opening", "Typing"]


@pytest.mark.unit
def test_caption_out_of_range_index_returns_none() -> None:
    assert _caption(["Opening", "Typing"], 2) is None


@pytest.mark.unit
def test_caption_blank_after_strip_returns_none() -> None:
    assert _caption(["   "], 0) is None
