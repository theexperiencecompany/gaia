"""Importing app.patches installs every Browser-Use patch the browser run relies on."""

from browser_use.browser.session import BrowserSession
from browser_use.tools.registry.service import Registry
import pytest

from app.patches import browser_use_page_ready_patch, browser_use_secret_scope_patch

pytestmark = pytest.mark.unit


def test_the_secret_scope_and_page_wait_patches_are_installed() -> None:
    assert Registry.execute_action is browser_use_secret_scope_patch._execute_action
    assert BrowserSession._navigate_and_wait is browser_use_page_ready_patch._navigate_and_wait
