"""Tests for the Obscura navigation patch.

Under Obscura, Page.navigate returns only once the page has loaded, so the patch
gives the call the engine's own deadline plus a margin and skips Browser-Use's
lifecycle polling. Under any other engine it is Browser-Use's own path. CDP is
faked at the session boundary; the patch's own logic runs for real.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from browser_use.browser.session import BrowserSession
import pytest

from app.constants.browser import BrowserEngine
import app.patches.browser_use_obscura_navigate_patch as patch_module

_URL = "https://example.test/slow"


def _session(navigate: AsyncMock) -> tuple[Any, AsyncMock]:
    """Return a BrowserSession stand-in whose CDP session answers Page.navigate with navigate."""
    cdp_session = SimpleNamespace(
        session_id="cdp-1",
        cdp_client=SimpleNamespace(send=SimpleNamespace(Page=SimpleNamespace(navigate=navigate))),
    )
    get_cdp = AsyncMock(return_value=cdp_session)
    return SimpleNamespace(get_or_create_cdp_session=get_cdp), get_cdp


@pytest.fixture
def original(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    stand_in = AsyncMock()
    monkeypatch.setattr(patch_module, "_original_navigate_and_wait", stand_in)
    return stand_in


@pytest.fixture
def obscura(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(patch_module.settings, "BROWSER_ENGINE", BrowserEngine.OBSCURA)


@pytest.mark.unit
class TestObscuraNavigatePatch:
    async def test_another_engine_takes_browser_uses_own_path_with_every_argument(
        self, monkeypatch: pytest.MonkeyPatch, original: AsyncMock
    ) -> None:
        monkeypatch.setattr(patch_module.settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
        session, get_cdp = _session(AsyncMock())

        await patch_module._navigate_and_wait(
            session, _URL, "t1", timeout=3.0, wait_until="domcontentloaded"
        )

        original.assert_awaited_once_with(
            session, _URL, "t1", timeout=3.0, wait_until="domcontentloaded"
        )
        get_cdp.assert_not_awaited()

    async def test_a_caller_that_omits_the_wait_gets_browser_uses_own_defaults(
        self, monkeypatch: pytest.MonkeyPatch, original: AsyncMock
    ) -> None:
        monkeypatch.setattr(patch_module.settings, "BROWSER_ENGINE", BrowserEngine.CHROMIUM)
        session, _ = _session(AsyncMock())

        await patch_module._navigate_and_wait(session, _URL, "t1")

        # browser-use 0.11.13 waits for the full "load" when no wait is named.
        original.assert_awaited_once_with(session, _URL, "t1", timeout=None, wait_until="load")

    @pytest.mark.usefixtures("obscura")
    async def test_obscura_navigates_its_target_once_and_skips_lifecycle_polling(
        self, original: AsyncMock
    ) -> None:
        navigate = AsyncMock(return_value={"frameId": "f1"})
        session, get_cdp = _session(navigate)

        await patch_module._navigate_and_wait(session, _URL, "t1")

        get_cdp.assert_awaited_once_with("t1", focus=False)
        navigate.assert_awaited_once_with(
            params={"url": _URL, "transitionType": "address_bar"}, session_id="cdp-1"
        )
        original.assert_not_awaited()

    @pytest.mark.usefixtures("obscura")
    async def test_a_navigation_obscura_reports_as_failed_raises_with_its_error(self) -> None:
        session, _ = _session(AsyncMock(return_value={"errorText": "net::ERR_NAME_NOT_RESOLVED"}))

        with pytest.raises(RuntimeError, match=r"^Navigation failed: net::ERR_NAME_NOT_RESOLVED$"):
            await patch_module._navigate_and_wait(session, _URL, "t1")

    @pytest.mark.usefixtures("obscura")
    async def test_a_navigation_past_the_engine_deadline_raises_naming_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(patch_module.settings, "OBSCURA_NAV_TIMEOUT_SECONDS", 0)
        monkeypatch.setattr(patch_module, "_NAVIGATE_MARGIN_SECONDS", 0.01)
        never = asyncio.get_running_loop().create_future()
        session, _ = _session(MagicMock(return_value=never))

        with pytest.raises(
            RuntimeError, match=rf"^Page\.navigate\(\) timed out after 0\.01s for {_URL}$"
        ):
            await patch_module._navigate_and_wait(session, _URL, "t1")

    def test_the_engine_deadline_gets_a_ten_second_margin(self) -> None:
        # Obscura's own nav timeout must fire first, so its error, not ours, names the cause.
        assert patch_module._NAVIGATE_MARGIN_SECONDS == 10.0

    def test_apply_rebinds_the_method(self) -> None:
        installed = BrowserSession._navigate_and_wait
        type.__setattr__(BrowserSession, "_navigate_and_wait", object())
        try:
            patch_module.apply()
            assert BrowserSession._navigate_and_wait is patch_module._navigate_and_wait
        finally:
            type.__setattr__(BrowserSession, "_navigate_and_wait", installed)
