"""Regression: history rebuilt recap URLs it never checked existed.

`_frames` derived `{R2}/browser_steps/{session}/step_{i}.png` for every step, so
a step whose screenshot upload failed still produced a row in Settings → Browser
pointing at a 404 — a permanently broken thumbnail.
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
    return BrowserTaskDocument(**base)  # type: ignore[arg-type]


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
def test_older_tasks_without_stored_urls_still_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows recorded before the URLs were stored must keep working."""
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    frames = _frames(_doc(step_screenshots=[]))

    assert [f.url for f in frames] == [
        "https://cdn/browser_steps/sess1/step_1.png",
        "https://cdn/browser_steps/sess1/step_2.png",
        "https://cdn/browser_steps/sess1/step_3.png",
    ]


@pytest.mark.unit
def test_derived_frames_use_captions_shifted_back_one_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step i's image (1-indexed) is captioned by step_goals[i - 1] (0-indexed)."""
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "https://cdn")
    doc = _doc(step_screenshots=[], steps=2, step_goals=["Opening", "Typing"])

    frames = _frames(doc)

    assert [f.caption for f in frames] == ["Opening", "Typing"]


@pytest.mark.unit
def test_no_derived_frames_without_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """No R2_PUBLIC_BASE_URL configured means no guessed URLs, not a crash."""
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "")

    assert _frames(_doc(step_screenshots=[])) == []


@pytest.mark.unit
def test_no_derived_frames_when_steps_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    assert _frames(_doc(step_screenshots=[], steps=0)) == []


@pytest.mark.unit
def test_derived_base_url_trailing_slash_is_not_doubled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.browser.tasks.settings.R2_PUBLIC_BASE_URL", "https://cdn/")

    frames = _frames(_doc(step_screenshots=[], steps=1))

    assert frames[0].url == "https://cdn/browser_steps/sess1/step_1.png"


@pytest.mark.unit
def test_caption_out_of_range_index_returns_none() -> None:
    assert _caption(["Opening", "Typing"], 2) is None


@pytest.mark.unit
def test_caption_in_range_returns_stripped_text() -> None:
    assert _caption(["  Opening  "], 0) == "Opening"


@pytest.mark.unit
def test_caption_blank_after_strip_returns_none() -> None:
    assert _caption(["   "], 0) is None
