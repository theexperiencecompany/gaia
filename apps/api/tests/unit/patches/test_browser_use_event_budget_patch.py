"""Browser-Use's screenshot and state-read budgets fit what the engine measures."""

from __future__ import annotations

from collections.abc import Iterator

from browser_use.browser.events import (
    BrowserStateRequestEvent,
    NavigateToUrlEvent,
    ScreenshotEvent,
)
import pytest

from app.config.settings import settings
from app.patches import browser_use_event_budget_patch as patch_mod

pytestmark = pytest.mark.unit

# Slowest first screenshot measured on a very long page, in seconds.
_SLOWEST_MEASURED_SCREENSHOT = 35.0
_PATCHED_EVENTS = (ScreenshotEvent, BrowserStateRequestEvent, NavigateToUrlEvent)
# A budget no real default uses, so a test sees whether apply() replaced it.
_UNPATCHED_BUDGET = 1.5


@pytest.fixture(autouse=True)
def _unpatched_events() -> Iterator[None]:
    """Start each test from a stand-in stock budget, so apply() must install its own."""
    installed = {
        event: event.model_fields["event_timeout"].default_factory for event in _PATCHED_EVENTS
    }
    for event in _PATCHED_EVENTS:
        event.model_fields["event_timeout"].default_factory = lambda: _UNPATCHED_BUDGET
        event.model_rebuild(force=True)
    yield
    for event, factory in installed.items():
        event.model_fields["event_timeout"].default_factory = factory
        event.model_rebuild(force=True)


def test_a_screenshot_is_given_longer_than_the_slowest_one_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIMEOUT_ScreenshotEvent", raising=False)
    patch_mod.apply()

    event = ScreenshotEvent()

    assert event.event_timeout is not None
    assert event.event_timeout > _SLOWEST_MEASURED_SCREENSHOT


def test_the_state_read_outlasts_the_screenshot_it_contains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIMEOUT_ScreenshotEvent", raising=False)
    monkeypatch.delenv("TIMEOUT_BrowserStateRequestEvent", raising=False)
    patch_mod.apply()

    screenshot, state_read = ScreenshotEvent(), BrowserStateRequestEvent()

    assert screenshot.event_timeout is not None
    assert state_read.event_timeout is not None
    assert state_read.event_timeout > screenshot.event_timeout


def test_a_navigation_outlasts_the_engines_own_load_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Obscura answers Page.navigate only once its own deadline has passed, so a
    # shorter budget here would cut the load short.
    monkeypatch.delenv("TIMEOUT_NavigateToUrlEvent", raising=False)
    patch_mod.apply()

    event = NavigateToUrlEvent(url="https://example.test")

    assert event.event_timeout is not None
    assert event.event_timeout > settings.OBSCURA_NAV_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("event_type", "env_var", "kwargs"),
    [
        (ScreenshotEvent, "TIMEOUT_ScreenshotEvent", {}),
        (BrowserStateRequestEvent, "TIMEOUT_BrowserStateRequestEvent", {}),
        (NavigateToUrlEvent, "TIMEOUT_NavigateToUrlEvent", {"url": "https://example.test"}),
    ],
)
def test_an_operators_own_budget_is_left_alone(
    monkeypatch: pytest.MonkeyPatch,
    event_type: type[ScreenshotEvent],
    env_var: str,
    kwargs: dict[str, str],
) -> None:
    monkeypatch.setenv(env_var, "5")
    patch_mod.apply()

    assert event_type(**kwargs).event_timeout == 5.0
