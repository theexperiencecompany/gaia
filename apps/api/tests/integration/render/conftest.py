"""Renders through the production Chromium: the process browser app.services.render.chromium launches.

Every test here runs on the package's event loop (each module sets
pytest.mark.asyncio(loop_scope="package")), so one browser, launched with the
production arguments on first use, serves the whole package and is closed after
it. Playwright's Chromium shell must be installed (the integration CI slice does).
"""

from collections.abc import AsyncIterator

import pytest_asyncio

from app.services.render.chromium import close_chromium


@pytest_asyncio.fixture(scope="package", loop_scope="package", autouse=True)
async def process_chromium() -> AsyncIterator[None]:
    yield
    await close_chromium()
