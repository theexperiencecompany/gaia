"""The process browser: one launch shared by every render, a context each, and a cap on renders at once."""

import asyncio

from playwright._impl._errors import TargetClosedError
from playwright.async_api import ViewportSize
import pytest

from app.constants.log_tags import LogTag
from app.constants.render import (
    CHROMIUM_DEAD_DRIVER_MESSAGE,
    CHROMIUM_LAUNCH_ARGS,
    CHROMIUM_MAX_CONCURRENT_RENDERS,
)
from app.services.render import chromium as chromium_module
from app.services.render.chromium import chromium_page, close_chromium, renders_waiting
from tests.helpers import captured_wide_event
from tests.unit.services.render.conftest import FakeChromium

_VIEWPORT: ViewportSize = {"width": 800, "height": 600}


async def test_renders_share_one_browser_each_in_a_context_closed_after_it(
    chromium: FakeChromium,
) -> None:
    for _ in range(3):
        async with chromium_page(_VIEWPORT, 2):
            pass

    [browser] = chromium.browsers
    assert len(browser.contexts) == 3
    assert all(context.closed for context in browser.contexts)
    assert browser.contexts[0].options == {
        "viewport": _VIEWPORT,
        "device_scale_factor": 2,
    }


async def test_a_context_is_closed_when_the_render_inside_it_fails(chromium: FakeChromium) -> None:
    with pytest.raises(ValueError, match="boom"):
        async with chromium_page(_VIEWPORT):
            raise ValueError("boom")

    [context] = chromium.browsers[0].contexts
    assert context.closed


async def test_a_browser_that_died_is_replaced_on_the_next_render(chromium: FakeChromium) -> None:
    async with chromium_page(_VIEWPORT):
        pass
    chromium.browsers[0].connected = False

    async with chromium_page(_VIEWPORT):
        pass

    dead, fresh = chromium.browsers
    assert dead.closed and chromium.playwrights[0].stopped
    assert len(fresh.contexts) == 1 and not fresh.closed


async def test_a_connected_browser_that_cannot_open_a_context_is_replaced_for_the_render(
    chromium: FakeChromium,
) -> None:
    async with chromium_page(_VIEWPORT):
        pass
    chromium.browsers[0].context_error = Exception(CHROMIUM_DEAD_DRIVER_MESSAGE)

    async with captured_wide_event() as event, chromium_page(_VIEWPORT, 2):
        pass

    dead, fresh = chromium.browsers
    assert dead.closed and chromium.playwrights[0].stopped
    [context] = fresh.contexts
    assert not fresh.closed
    assert context.options == {"viewport": _VIEWPORT, "device_scale_factor": 2}
    [warning] = event["warnings"]
    assert (warning["msg"], warning["error_type"], warning["error"]) == (
        f"{LogTag.BROWSER} Render browser is dead; relaunching",
        "Exception",
        CHROMIUM_DEAD_DRIVER_MESSAGE,
    )


async def test_a_render_fails_loud_when_the_fresh_browser_cannot_open_a_context_either(
    chromium: FakeChromium,
) -> None:
    chromium.context_error = TargetClosedError("Connection closed while reading from the driver")

    with pytest.raises(TargetClosedError, match="Connection closed"):
        async with chromium_page(_VIEWPORT):
            pass

    first, retried = chromium.browsers
    assert first.closed and retried.closed


async def test_a_live_browser_that_refuses_a_context_is_kept_and_the_error_raised(
    chromium: FakeChromium,
) -> None:
    async with chromium_page(_VIEWPORT):
        pass
    chromium.browsers[0].context_error = ValueError("bad viewport")

    with pytest.raises(ValueError, match="bad viewport"):
        async with chromium_page(_VIEWPORT):
            pass

    [browser] = chromium.browsers
    assert not browser.closed
    assert chromium_module._chromium._current is not None
    assert chromium_module._chromium._current.renders == 0


async def test_a_render_cancelled_while_opening_its_context_gives_the_browser_back(
    chromium: FakeChromium,
) -> None:
    chromium.context_error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        async with chromium_page(_VIEWPORT):
            pass

    assert chromium_module._chromium._current is not None
    assert chromium_module._chromium._current.renders == 0


async def test_a_browser_past_its_age_is_replaced_and_closes_once_its_last_render_ends(
    chromium: FakeChromium, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium_module, "CHROMIUM_RECYCLE_AGE_SECONDS", 0)

    async with chromium_page(_VIEWPORT):
        async with chromium_page(_VIEWPORT):
            old, new = chromium.browsers
            assert not old.closed
        assert not new.closed
    assert old.closed and chromium.playwrights[0].stopped


async def test_no_more_than_the_cap_render_at_once_and_the_rest_wait(
    chromium: FakeChromium,
) -> None:
    release = asyncio.Event()
    running = 0
    most_running = 0

    async def render() -> None:
        nonlocal running, most_running
        async with chromium_page(_VIEWPORT):
            running += 1
            most_running = max(most_running, running)
            await release.wait()
            running -= 1

    tasks = [asyncio.create_task(render()) for _ in range(CHROMIUM_MAX_CONCURRENT_RENDERS + 2)]
    for _ in range(5):
        await asyncio.sleep(0)
    assert (running, renders_waiting()) == (CHROMIUM_MAX_CONCURRENT_RENDERS, 2)

    release.set()
    await asyncio.gather(*tasks)

    assert most_running == CHROMIUM_MAX_CONCURRENT_RENDERS
    assert renders_waiting() == 0
    assert len(chromium.browsers) == 1


async def test_closing_the_process_browser_stops_it_and_the_next_render_launches_anew(
    chromium: FakeChromium,
) -> None:
    async with chromium_page(_VIEWPORT):
        pass

    await close_chromium()

    assert chromium.browsers[0].closed and chromium.playwrights[0].stopped
    async with chromium_page(_VIEWPORT):
        pass
    assert len(chromium.browsers) == 2


async def test_closing_with_no_browser_launched_does_nothing(chromium: FakeChromium) -> None:
    await close_chromium()

    assert chromium.browsers == []


async def test_a_browser_left_idle_closes_and_the_next_render_launches_anew(
    chromium: FakeChromium, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium_module, "CHROMIUM_IDLE_CLOSE_SECONDS", 0)
    async with chromium_page(_VIEWPORT):
        pass

    for _ in range(3):
        await asyncio.sleep(0)

    assert chromium.browsers[0].closed and chromium.playwrights[0].stopped
    async with chromium_page(_VIEWPORT):
        pass
    assert len(chromium.browsers) == 2


async def test_a_render_inside_the_idle_window_keeps_the_browser(
    chromium: FakeChromium, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium_module, "CHROMIUM_IDLE_CLOSE_SECONDS", 0)
    async with chromium_page(_VIEWPORT):
        pass
    async with chromium_page(_VIEWPORT):
        for _ in range(3):
            await asyncio.sleep(0)

        assert not chromium.browsers[0].closed
    assert len(chromium.browsers) == 1


async def test_chromium_launches_headless_with_the_shared_launch_args(
    chromium: FakeChromium,
) -> None:
    async with chromium_page(_VIEWPORT):
        pass

    assert chromium.launches == [{"headless": True, "args": CHROMIUM_LAUNCH_ARGS}]


async def test_a_failed_relaunch_leaves_the_next_render_to_launch_again(
    chromium: FakeChromium,
) -> None:
    async with chromium_page(_VIEWPORT):
        pass
    chromium.browsers[0].connected = False
    chromium.launch_error = RuntimeError("chromium would not start")

    with pytest.raises(RuntimeError, match="would not start"):
        async with chromium_page(_VIEWPORT):
            pass
    chromium.launch_error = None
    async with chromium_page(_VIEWPORT):
        pass

    assert len(chromium.browsers) == 2


async def test_a_browser_is_not_idle_while_an_overlapping_render_still_runs(
    chromium: FakeChromium, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium_module, "CHROMIUM_IDLE_CLOSE_SECONDS", 0)
    second_started = asyncio.Event()
    first_done = asyncio.Event()

    async def second() -> None:
        async with chromium_page(_VIEWPORT):
            second_started.set()
            await first_done.wait()
            for _ in range(3):
                await asyncio.sleep(0)
            assert not chromium.browsers[0].closed

    task = asyncio.create_task(second())
    async with chromium_page(_VIEWPORT):
        await second_started.wait()
    first_done.set()
    await task


async def test_a_render_starting_as_the_idle_close_fires_keeps_the_browser(
    chromium: FakeChromium, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chromium_module, "CHROMIUM_IDLE_CLOSE_SECONDS", 0)
    async with chromium_page(_VIEWPORT):
        pass
    # Two loop turns: the zero-delay timer fires and queues the close, which has not run yet.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    async with chromium_page(_VIEWPORT):
        for _ in range(3):
            await asyncio.sleep(0)

        assert not chromium.browsers[0].closed
