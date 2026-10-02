"""The browser stack tier: one whole stack per module, on that module's own event loop.

The stack's servers and clients in this process (the fake models, the fixture
site, the observer, the Redis and Motor clients its helpers use) live on the
module's loop, so every test here runs on it too
(``pytest.mark.asyncio(loop_scope="module")``). Real services only, like the
rest of tests/integration/real; Chrome is required (CHROMIUM_BIN or
google-chrome on PATH) and so is OBSCURA_BIN: a missing binary fails the tier.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator

import pytest
import pytest_asyncio

from tests.integration.real.browser._stack.stack import BrowserStack


@pytest.fixture(autouse=True)
def _autouse_hil_approvals_collection() -> None:
    """Replace the real tier's per-test approvals collection, which this tier must not use.

    That fixture repoints this process's repository layer at a per-worker database
    on the test's own loop; the stack's processes use the app's own database, which
    the users this process seeds must share, and every scenario's user is new.
    """


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stack(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[BrowserStack]:
    """Boot the whole browser stack once for the module, and tear every process down after it."""
    browser_stack = BrowserStack(tmp_path_factory.mktemp("browser-stack"))
    try:
        await browser_stack.start()
        yield browser_stack
    finally:
        await browser_stack.stop()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None]:
    """Attach every stack process's log tail and the fake models' refusals to a failed scenario's report."""
    outcome = yield
    report = outcome.get_result()
    stack = getattr(item, "funcargs", {}).get("stack")
    if report.when == "call" and report.failed and isinstance(stack, BrowserStack):
        report.sections.append(
            ("browser stack", f"{stack.logs()}\nfake model errors: {stack.models.errors}")
        )
