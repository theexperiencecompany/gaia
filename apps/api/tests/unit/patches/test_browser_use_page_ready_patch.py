"""Tests for the page-readiness timeout cap patch.

Browser-Use's _navigate_and_wait defaults timeout to None, which lets a hung
subresource stall a step for the library's full 3s/8s budget. The patch caps
the default to _MAX_READINESS_WAIT_SECONDS while leaving explicit timeouts
untouched. These tests pin exactly what timeout reaches the wrapped original,
plus that apply() really rebinds the method on the class.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from browser_use.browser.session import BrowserSession
import pytest

import app.patches.browser_use_page_ready_patch as patch_module


@pytest.mark.unit
class TestPageReadyPatch:
    async def test_none_timeout_is_capped_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = AsyncMock()
        monkeypatch.setattr(patch_module, "_original_navigate_and_wait", original)
        await patch_module._navigate_and_wait(object(), "https://x", "t1", timeout=None)
        original.assert_awaited_once()
        assert original.await_args.kwargs["timeout"] == patch_module._MAX_READINESS_WAIT_SECONDS

    async def test_omitted_timeout_is_capped_to_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The default value of the parameter is ``None``, so a caller that omits
        # it must get the cap too -- not the library's uncapped budget.
        original = AsyncMock()
        monkeypatch.setattr(patch_module, "_original_navigate_and_wait", original)
        await patch_module._navigate_and_wait(object(), "https://x", "t1")
        assert original.await_args.kwargs["timeout"] == patch_module._MAX_READINESS_WAIT_SECONDS

    async def test_explicit_timeout_passes_through_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = AsyncMock()
        monkeypatch.setattr(patch_module, "_original_navigate_and_wait", original)
        await patch_module._navigate_and_wait(object(), "https://x", "t1", timeout=0.25)
        assert original.await_args.kwargs["timeout"] == 0.25

    async def test_wait_until_and_positional_args_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = AsyncMock()
        monkeypatch.setattr(patch_module, "_original_navigate_and_wait", original)
        session = object()
        await patch_module._navigate_and_wait(
            session, "https://x", "target-9", timeout=1.0, wait_until="domcontentloaded"
        )
        args, kwargs = original.await_args
        assert args == (session, "https://x", "target-9")
        assert kwargs["wait_until"] == "domcontentloaded"

    async def test_omitted_wait_until_forwards_the_cdp_load_lifecycle_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # "load" is the CDP lifecycle event name; any other spelling never fires
        # and every navigation would then burn the full timeout.
        original = AsyncMock()
        monkeypatch.setattr(patch_module, "_original_navigate_and_wait", original)
        await patch_module._navigate_and_wait(object(), "https://x", "t1")
        assert original.await_args.kwargs["wait_until"] == "load"

    def test_import_installed_the_wrapper_on_the_class(self) -> None:
        # apply() runs at import time; the class method must be the wrapper.
        assert BrowserSession._navigate_and_wait is patch_module._navigate_and_wait

    def test_apply_rebinds_the_method(self) -> None:
        sentinel = object()
        type.__setattr__(BrowserSession, "_navigate_and_wait", sentinel)
        try:
            patch_module.apply()
            assert BrowserSession._navigate_and_wait is patch_module._navigate_and_wait
        finally:
            type.__setattr__(BrowserSession, "_navigate_and_wait", patch_module._navigate_and_wait)
