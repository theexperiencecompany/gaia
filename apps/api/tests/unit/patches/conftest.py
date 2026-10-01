"""Browser-Use patch fixtures: the patches that work around Obscura gaps apply to Obscura sessions only."""

from collections.abc import Iterator

import pytest

from app.constants.browser import BrowserEngine
from app.patches.obscura_sessions import driving


@pytest.fixture
def obscura_host() -> Iterator[None]:
    """Run the test as a run driving an Obscura session."""
    with driving(BrowserEngine.OBSCURA):
        yield
