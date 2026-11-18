"""The browser stack tier: one whole stack per module, on that module's own event loop.

The stack's servers and clients in this process (the fake models, the fixture
site, the observer, the Redis and Motor clients its helpers use) live on the
module's loop, so every test here runs on it too
(pytest.mark.asyncio(loop_scope="module")). Real services only, like the
rest of tests/integration/real; Chrome is required (CHROMIUM_BIN or
google-chrome on PATH), and so are OBSCURA_BIN, the self-host proxy (CADDY_BIN
or caddy on PATH) and, on Linux, FORTRESS_BIN for Fortress's identity test: a
missing binary fails the tier.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator
import time

import pytest
import pytest_asyncio

from tests.integration.real.browser._stack.progress import Progress
from tests.integration.real.browser._stack.stack import BrowserStack


@pytest.fixture(autouse=True)
def _autouse_hil_approvals_collection() -> None:
    """Replace the real tier's per-test approvals collection, which this tier must not use.

    That fixture repoints this process's repository layer at a per-worker database
    on the test's own loop; the stack's processes use the app's own database, which
    the users this process seeds must share, and every scenario's user is new.
    """


@pytest.fixture(scope="session")
def progress(pytestconfig: pytest.Config) -> Progress:
    return Progress(pytestconfig)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def stack(
    tmp_path_factory: pytest.TempPathFactory, progress: Progress
) -> AsyncIterator[BrowserStack]:
    """Boot the whole browser stack once for the module, and tear every process down after it."""
    browser_stack = BrowserStack(tmp_path_factory.mktemp("browser-stack"), progress)
    try:
        await browser_stack.start()
        yield browser_stack
    finally:
        await browser_stack.stop()


@pytest.fixture(autouse=True)
def _scenario_errors(request: pytest.FixtureRequest) -> None:
    """Give each scenario a fresh view of the fake models' errors: an earlier failure is not its own."""
    if "stack" in request.fixturenames:
        request.getfixturevalue("stack").models.begin_scenario()


#: How much of a failure's message a progress line carries; a settle's message ends in every log.
_FAILURE_SAID_CHARS = 1500


@pytest.fixture(autouse=True)
def _said(request: pytest.FixtureRequest, progress: Progress) -> Iterator[None]:
    """Say when each scenario starts and how long it took, past the output capture."""
    started = time.monotonic()
    progress.say(f"{request.node.name} started")
    yield
    progress.say(f"{request.node.name} ended after {time.monotonic() - started:.0f}s")


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Say why a scenario failed as it fails, and attach every stack process's log tail and the fake models' refusals.

    Said live because a lane cut at its cap never prints the failure summary.
    """
    report = yield
    funcargs = getattr(item, "funcargs", {})
    progress = funcargs.get("progress")
    if report.failed and isinstance(progress, Progress):
        crash = getattr(report.longrepr, "reprcrash", None)
        why = crash.message if crash is not None else str(report.longrepr)
        progress.say(f"{item.name} failed in {report.when}: {why[:_FAILURE_SAID_CHARS]}")
    stack = funcargs.get("stack")
    if report.when == "call" and report.failed and isinstance(stack, BrowserStack):
        report.sections.append(
            ("browser stack", f"{stack.logs()}\nfake model errors: {stack.models.errors}")
        )
    return report
