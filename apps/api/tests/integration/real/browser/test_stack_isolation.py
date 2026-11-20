"""Two browser stacks, one per xdist worker, share no store their app processes use.

Each stack's worker runs the conversation sweeper, which reads every conversation in
its Mongo database and judges a run lost when that run's lock is missing from its own
Redis. On a shared database it marked the other stack's live runs lost, so their
results woke a step in the wrong stack and never reached the user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.constants.browser import BrowserEngine
from tests.integration.real.browser._stack.processes import browser_host
from tests.integration.real.browser._stack.progress import Progress
from tests.integration.real.browser._stack.stack import BrowserStack


def _stores_of(
    worker: str, tmp_path: Path, progress: Progress, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Build (not start) the stack worker would boot; return the Redis and Mongo database its app processes get."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", worker)
    stack = BrowserStack(tmp_path / worker, progress)
    site = ((), tmp_path / "ca.pem")
    stack.chrome = browser_host(BrowserEngine.CHROMIUM, "chrome", stack.host_key, site, tmp_path)
    stack.obscura = browser_host(BrowserEngine.OBSCURA, "obscura", stack.host_key, site, tmp_path)
    env = stack._app_environment()
    return env["REDIS_URL"], env["MONGO_DB_NAME"]


def test_stacks_on_two_workers_share_neither_redis_nor_mongo(
    tmp_path: Path, progress: Progress, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis_a, mongo_a = _stores_of("gw0", tmp_path, progress, monkeypatch)
    redis_b, mongo_b = _stores_of("gw1", tmp_path, progress, monkeypatch)

    assert redis_a != redis_b
    assert mongo_a != mongo_b
