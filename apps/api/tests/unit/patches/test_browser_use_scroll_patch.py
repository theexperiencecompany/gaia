"""Scrolling must move the page, which on Obscura means JavaScript, not a synthesized gesture."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
import pytest

from app.constants.log_tags import LogTag
import app.patches.browser_use_scroll_patch as patch_module
from tests.helpers import OBSCURA_TEST_CDP_URL

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("obscura_host")]


class _Input:
    """Input.synthesizeScrollGesture is dropped on Obscura; touching it at all is the bug."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the patched scroll must not call Input.{name}")


class _FakeCdp:
    def __init__(self, *, moved: bool = True) -> None:
        self.moved = moved
        self.expressions: list[str] = []
        self.session_ids: list[str] = []

        class _Runtime:
            @staticmethod
            async def evaluate(params: dict[str, Any], session_id: str) -> dict[str, Any]:
                self.expressions.append(params["expression"])
                self.session_ids.append(session_id)
                return {"result": {"value": self.moved}}

        self.send = SimpleNamespace(Runtime=_Runtime(), Input=_Input())


def _watchdog(cdp: _FakeCdp) -> SimpleNamespace:
    session = SimpleNamespace(session_id="sess", cdp_client=cdp)

    async def get_or_create_cdp_session() -> SimpleNamespace:
        return session

    return SimpleNamespace(
        browser_session=SimpleNamespace(
            cdp_url=OBSCURA_TEST_CDP_URL, get_or_create_cdp_session=get_or_create_cdp_session
        )
    )


async def test_the_page_is_scrolled_by_the_requested_pixels_in_javascript() -> None:
    cdp = _FakeCdp()

    assert await patch_module._scroll_with_cdp_gesture(_watchdog(cdp), 800) is True
    # _Input raises on any attribute, so reaching here proves no gesture was synthesized.
    assert "800" in cdp.expressions[0]
    assert "scrollBy" in cdp.expressions[0]
    # Without the page's own session the script runs on the browser target, not the page.
    assert cdp.session_ids == ["sess"]


async def test_scrolling_up_passes_the_negative_distance_through() -> None:
    cdp = _FakeCdp()

    await patch_module._scroll_with_cdp_gesture(_watchdog(cdp), -400)

    assert "-400" in cdp.expressions[0]


async def test_a_page_that_did_not_move_is_reported_and_warned_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(patch_module, "log", logger)

    assert (
        await patch_module._scroll_with_cdp_gesture(_watchdog(_FakeCdp(moved=False)), 800) is False
    )
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Scroll left the page where it was", browser={"pixels": 800}
    )


def test_apply_routes_the_watchdogs_scroll_through_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DefaultActionWatchdog, "_scroll_with_cdp_gesture", None)

    patch_module.apply()

    assert DefaultActionWatchdog._scroll_with_cdp_gesture is patch_module._scroll_with_cdp_gesture
