"""A page's window.open must reach somewhere, because Obscura opens no window for it."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from browser_use.browser.session import BrowserSession
import pytest

import app.patches.browser_use_window_open_patch as patch_module
from tests.helpers import OBSCURA_TEST_CDP_URL

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("obscura_host")]


class _FakeCdp:
    """A CDP client that, like the real one, acts only on the session it is addressed to."""

    def __init__(
        self, *, fails: bool = False, sessions: tuple[str, ...] = ("t1-s", "t2-s")
    ) -> None:
        self.sources: list[str] = []
        self.evaluated: list[str] = []
        # Scripts armed on the document already open, as Chrome does for runImmediately.
        self.armed_now: list[str] = []
        outer = self

        def _addressed(session: str) -> None:
            if session not in sessions:
                raise RuntimeError(f"Session with given id not found: {session}")

        class _Page:
            @staticmethod
            async def addScriptToEvaluateOnNewDocument(
                params: dict[str, Any], session_id: str
            ) -> dict[str, Any]:
                if fails:
                    raise RuntimeError("no such target")
                _addressed(session_id)
                outer.sources.append(params["source"])
                if params.get("runImmediately") is True:
                    outer.armed_now.append(params["source"])
                return {"identifier": "1"}

        class _Runtime:
            @staticmethod
            async def evaluate(params: dict[str, Any], session_id: str) -> dict[str, Any]:
                _addressed(session_id)
                outer.evaluated.append(params["expression"])
                return {"result": {}}

        self.send = SimpleNamespace(Page=_Page(), Runtime=_Runtime())


def _session(target_id: str, cdp: _FakeCdp) -> SimpleNamespace:
    return SimpleNamespace(target_id=target_id, session_id=f"{target_id}-s", cdp_client=cdp)


def _browser_session(*targets: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Build a browser session whose accessor hands out targets in order, recording each ask."""
    queue = list(targets)
    browser = SimpleNamespace(cdp_url=OBSCURA_TEST_CDP_URL, requests=[])

    async def original(self: object, target_id: str | None = None, focus: bool = True) -> object:
        assert self is browser, "Browser-Use's accessor must be asked on the same session"
        browser.requests.append((target_id, focus))
        return queue.pop(0)

    monkeypatch.setattr(patch_module, "_original_get_or_create_cdp_session", original)
    return browser


async def test_the_shim_is_installed_on_a_fresh_target(monkeypatch: pytest.MonkeyPatch) -> None:
    cdp = _FakeCdp()
    session = _browser_session(_session("t1", cdp), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)

    assert cdp.sources == [patch_module.WINDOW_OPEN_SHIM]


async def test_browser_use_is_asked_for_the_same_target_and_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _browser_session(_session("t1", _FakeCdp()), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session, target_id="t1", focus=False)

    assert session.requests == [("t1", False)]


async def test_a_caller_that_names_no_focus_still_focuses_the_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # browser-use 0.11.13's accessor focuses by default; the wrapper keeps that.
    session = _browser_session(_session("t1", _FakeCdp()), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)

    assert session.requests == [(None, True)]


async def test_an_engine_that_honours_run_immediately_arms_the_open_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cdp = _FakeCdp()
    session = _browser_session(_session("t1", cdp), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)

    assert cdp.armed_now == [patch_module.WINDOW_OPEN_SHIM]


async def test_the_shim_also_runs_on_the_document_already_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Obscura accepts runImmediately and ignores it, arming only the next load.
    cdp = _FakeCdp()
    session = _browser_session(_session("t1", cdp), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)

    assert cdp.evaluated == [patch_module.WINDOW_OPEN_SHIM]


async def test_a_target_is_only_shimmed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    cdp = _FakeCdp()
    session = _browser_session(_session("t1", cdp), _session("t1", cdp), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)
    await patch_module._get_or_create_cdp_session(session)

    assert len(cdp.sources) == 1


async def test_every_new_target_gets_its_own_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    cdp = _FakeCdp()
    session = _browser_session(_session("t1", cdp), _session("t2", cdp), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)
    await patch_module._get_or_create_cdp_session(session)

    assert len(cdp.sources) == 2


async def test_a_failed_injection_is_retried_on_the_next_visit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(patch_module, "log", MagicMock())
    failing, working = _FakeCdp(fails=True), _FakeCdp()
    session = _browser_session(
        _session("t1", failing), _session("t1", working), monkeypatch=monkeypatch
    )

    await patch_module._get_or_create_cdp_session(session)
    await patch_module._get_or_create_cdp_session(session)

    assert working.sources == [patch_module.WINDOW_OPEN_SHIM]


async def test_a_failed_injection_never_fails_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(patch_module, "log", logger)
    target = _session("t1", _FakeCdp(fails=True))
    session = _browser_session(target, monkeypatch=monkeypatch)

    assert await patch_module._get_or_create_cdp_session(session) is target
    logger.warning.assert_called_once()


async def test_a_failed_injection_is_logged_with_its_cause_and_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(patch_module, "log", logger)
    session = _browser_session(_session("t2", _FakeCdp(fails=True)), monkeypatch=monkeypatch)

    await patch_module._get_or_create_cdp_session(session)

    (message,), fields = logger.warning.call_args
    assert "window.open shim injection failed" in message
    assert fields == {"error_type": "RuntimeError", "browser": {"target_id": "t2"}}


@pytest.mark.parametrize(
    "url",
    ["", "javascript:alert(1)", "about:blank", "data:text/html,<p>x"],
    ids=["empty", "javascript", "about", "data"],
)
def test_the_shim_refuses_to_navigate_anywhere_but_http(url: str) -> None:
    # The shim runs in the page, so the guard is read off its source: only
    # http(s) may take over the tab Jev is working in.
    assert "'http:'" in patch_module.WINDOW_OPEN_SHIM
    assert "'https:'" in patch_module.WINDOW_OPEN_SHIM
    assert re.search(r"if\s*\(!url\)\s*return null", patch_module.WINDOW_OPEN_SHIM)


def test_the_returned_stub_cannot_close_the_tab() -> None:
    # A page calling w.close() on the real window would close Jev's own tab.
    assert "close() {}" in patch_module.WINDOW_OPEN_SHIM
    assert "return stub" in patch_module.WINDOW_OPEN_SHIM


async def test_apply_rebinds_the_session_accessor() -> None:
    # Applied explicitly: the stealth patch wraps the same funnel, so which
    # wrapper sits outermost depends on import order, and this asserts only that
    # applying ours puts ours there.
    installed = BrowserSession.get_or_create_cdp_session
    type.__setattr__(BrowserSession, "get_or_create_cdp_session", object())
    try:
        patch_module.apply()
        assert BrowserSession.get_or_create_cdp_session is patch_module._get_or_create_cdp_session
    finally:
        type.__setattr__(BrowserSession, "get_or_create_cdp_session", installed)
