"""A patch for an Obscura gap applies to a session on the Obscura host, never to a Chrome one."""

from types import SimpleNamespace

import pytest

from app.config.settings import settings
from app.constants.browser import BrowserEngine
from app.patches.obscura_sessions import on_obscura
from tests.helpers import OBSCURA_TEST_CDP_URL

pytestmark = pytest.mark.unit


def _session(cdp_url: str | None) -> SimpleNamespace:
    return SimpleNamespace(cdp_url=cdp_url)


@pytest.mark.usefixtures("obscura_host")
def test_a_session_on_the_obscura_host_runs_on_obscura() -> None:
    assert on_obscura(_session(OBSCURA_TEST_CDP_URL)) is True  # type: ignore[arg-type]  # the one field read


@pytest.mark.usefixtures("obscura_host")
def test_a_run_moved_to_chrome_keeps_browser_uses_own_behaviour() -> None:
    assert on_obscura(_session("ws://chrome.test:9222/devtools/browser/run-1")) is False  # type: ignore[arg-type]  # the one field read
    assert on_obscura(_session(None)) is False  # type: ignore[arg-type]  # the one field read


@pytest.mark.usefixtures("obscura_host")
def test_chrome_as_the_engine_patches_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)

    assert on_obscura(_session(OBSCURA_TEST_CDP_URL)) is False  # type: ignore[arg-type]  # the one field read
