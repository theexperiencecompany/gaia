"""The first-text gate: optional writes spawned in an attempt wait for its first text, or its end."""

import asyncio

from app.utils.hot_path import after_first_text, first_text_gate, first_text_shown


async def test_a_writer_inside_an_attempt_waits_for_its_first_text() -> None:
    with first_text_gate():
        writer = asyncio.create_task(after_first_text())
        await asyncio.sleep(0)
        assert not writer.done()

        first_text_shown()
        async with asyncio.timeout(1):
            await writer


async def test_an_attempt_that_ends_without_text_releases_its_writers() -> None:
    with first_text_gate():
        writer = asyncio.create_task(after_first_text())
        await asyncio.sleep(0)
        assert not writer.done()
    async with asyncio.timeout(1):
        await writer


async def test_outside_any_attempt_a_writer_runs_at_once_and_shown_is_a_no_op() -> None:
    first_text_shown()
    async with asyncio.timeout(1):
        await after_first_text()
