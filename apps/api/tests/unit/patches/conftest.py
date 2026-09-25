"""Browser-Use patch fixtures: the patches that work around Obscura gaps apply to Obscura sessions only."""

import pytest

from app.config.settings import settings
from app.constants.browser import BrowserEngine
from tests.helpers import OBSCURA_TEST_HOST_URL


@pytest.fixture
def obscura_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure Obscura as the engine on OBSCURA_TEST_HOST_URL."""
    monkeypatch.setattr(settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)
    monkeypatch.setattr(settings, "BROWSER_HOST_URL", OBSCURA_TEST_HOST_URL)
