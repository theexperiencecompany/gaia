"""Regression: the recap slideshow derived image URLs it never checked existed.

`render_replay_page` built `{R2}/browser_steps/{session}/step_{i}.png` for every
step from a count, so any step whose screenshot upload failed showed a broken
image in the shared recap link. Same root cause as the task-history thumbnails.
"""

from __future__ import annotations

import pytest

from app.schemas.browser import ReplayRecord
from app.services.browser.replay import render_replay_page


@pytest.mark.unit
@pytest.mark.regression
def test_page_shows_only_the_screenshots_that_uploaded() -> None:
    record = ReplayRecord(
        session_id="s1", steps=3, shots=["https://cdn/1.png", "https://cdn/3.png"]
    )

    page = render_replay_page(record)

    assert "https://cdn/1.png" in page
    assert "https://cdn/3.png" in page
    # The step that never uploaded must not be conjured from the session id.
    assert "browser_steps/s1/step_2.png" not in page


@pytest.mark.unit
def test_codes_minted_before_urls_were_stored_still_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.services.browser.replay.settings.R2_PUBLIC_BASE_URL", "https://cdn")

    page = render_replay_page(ReplayRecord(session_id="s1", steps=2))

    assert "browser_steps/s1/step_1.png" in page
    assert "browser_steps/s1/step_2.png" in page


@pytest.mark.unit
def test_no_placeholder_survives_rendering() -> None:
    page = render_replay_page(ReplayRecord(session_id="s1", steps=1, shots=["https://cdn/1.png"]))

    assert "__URLS__" not in page
