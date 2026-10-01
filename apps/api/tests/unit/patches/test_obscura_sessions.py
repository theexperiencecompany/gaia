"""A patch for an Obscura gap applies to a run driving an Obscura session, never to a Chrome one."""

import asyncio

import pytest

from app.constants.browser import BrowserEngine
from app.patches.obscura_sessions import driving, on_obscura

pytestmark = pytest.mark.unit


async def test_the_engine_a_run_drives_reaches_the_tasks_it_starts() -> None:
    async def _seen() -> bool:
        return on_obscura()

    with driving(BrowserEngine.OBSCURA):
        on_the_run = await asyncio.ensure_future(_seen())
    with driving(BrowserEngine.CHROMIUM):
        on_chrome = await asyncio.ensure_future(_seen())

    assert (on_the_run, on_chrome, on_obscura()) == (True, False, False)
