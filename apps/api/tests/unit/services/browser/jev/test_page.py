"""Jev's hands on the tab: every CDP call bounded, no input on a stale or covered target, typing as a person types."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.browser.jev import page as page_mod
from app.services.browser.jev.page import (
    Covered,
    JevPage,
    NavigationFailed,
    PageAction,
    PageState,
    PageUnresponsive,
    StalePage,
)

pytestmark = pytest.mark.unit

FIELD = PageAction(id="e1", node=7, kind="fill", label="Name", role="textbox", value="")
PAGE_KEY = ["key"]
GUARD = ["guard-of-7"]


def _state() -> PageState:
    return PageState(
        url="https://site.test/",
        title="Site",
        text="",
        actions=[FIELD],
        marker=["marker"],
        page_key=PAGE_KEY,
        guards={"7": GUARD},
        frames=[],
        fingerprint="f",
    )


class _Cdp:
    """One page session's CDP connection: scripted evaluate answers, every input recorded."""

    def __init__(self, *, guard: object, point: object, hangs: bool = False) -> None:
        self._guard = guard
        self._point = point
        self._hangs = hangs
        self.focus_calls = 0
        self.inputs: list[dict[str, Any]] = []
        self.send = SimpleNamespace(
            Emulation=SimpleNamespace(setFocusEmulationEnabled=self._focus),
            Runtime=SimpleNamespace(evaluate=self._evaluate),
            Input=SimpleNamespace(dispatchMouseEvent=self._input, dispatchKeyEvent=self._input),
        )

    async def _focus(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
        self.focus_calls += 1
        return {}

    async def _evaluate(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
        if self._hangs:
            await asyncio.Event().wait()
        expression = params["expression"]
        value = self._guard if "c.pageKey()" in expression else self._point
        return {"result": {"value": value}}

    async def _input(self, params: dict[str, Any], session_id: str) -> dict[str, Any]:
        self.inputs.append(params)
        return {}


def _page(cdp: _Cdp, *, navigate_error: Exception | None = None) -> JevPage:
    async def _session() -> Any:
        return SimpleNamespace(session_id="page-1", cdp_client=cdp)

    async def _navigate(url: str) -> None:
        if navigate_error is not None:
            raise navigate_error

    browser = SimpleNamespace(get_or_create_cdp_session=_session, navigate_to=_navigate)
    return JevPage(browser)  # type: ignore[arg-type]  # the two calls JevPage makes of a session


async def test_a_call_the_tab_never_answers_raises_instead_of_holding_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(page_mod, "JEV_CDP_TIMEOUT_SECONDS", 0.05)
    page = _page(_Cdp(guard=None, point=None, hangs=True))

    with pytest.raises(PageUnresponsive, match="Runtime.evaluate"):
        await page.body_text(100)


async def test_the_tab_is_told_to_render_as_focused_once_not_on_every_call() -> None:
    cdp = _Cdp(guard=[PAGE_KEY, GUARD], point="text")
    page = _page(cdp)

    await page.body_text(10)
    await page.body_text(10)

    assert cdp.focus_calls == 1


async def test_a_decision_on_a_page_that_moved_on_sends_no_input() -> None:
    cdp = _Cdp(guard=[PAGE_KEY, ["a different element"]], point={"x": 1, "y": 1})

    with pytest.raises(StalePage):
        await _page(cdp).act(FIELD, _state(), text="Ada")

    assert cdp.inputs == []


async def test_a_covered_target_sends_no_input() -> None:
    cdp = _Cdp(guard=[PAGE_KEY, GUARD], point=None)

    with pytest.raises(Covered):
        await _page(cdp).act(FIELD, _state(), text="Ada")

    assert cdp.inputs == []


async def test_typing_clicks_the_field_selects_it_and_sends_one_key_per_character() -> None:
    cdp = _Cdp(guard=[PAGE_KEY, GUARD], point={"x": 40, "y": 60})

    await _page(cdp).act(FIELD, _state(), text="Ab\n")

    mouse = [event["type"] for event in cdp.inputs[:2]]
    assert mouse == ["mousePressed", "mouseReleased"]
    assert (cdp.inputs[0]["x"], cdp.inputs[0]["y"]) == (40, 60)
    assert cdp.inputs[2]["commands"] == ["selectAll"]
    typed = [(event["type"], event["key"]) for event in cdp.inputs[4:]]
    # A date or time field that parses keystrokes drops a value inserted any other way.
    assert typed == [
        ("keyDown", "A"),
        ("keyUp", "A"),
        ("keyDown", "b"),
        ("keyUp", "b"),
        ("keyDown", "Enter"),
        ("keyUp", "Enter"),
    ]
    assert cdp.inputs[-2]["text"] == "\r"


async def test_an_address_that_cannot_be_opened_is_a_navigation_failure() -> None:
    page = _page(
        _Cdp(guard=None, point=None),
        navigate_error=RuntimeError("Navigation failed: net::ERR_NAME_NOT_RESOLVED"),
    )

    with pytest.raises(NavigationFailed, match="ERR_NAME_NOT_RESOLVED"):
        await page.navigate("https://gone.test/")
