"""Jev's hands on the tab: no input on a moved or unreachable target, reads that wait on the page's own facts, and every CDP call bounded."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import json
import re
from types import SimpleNamespace
from typing import Any, cast

from browser_use.browser.session import BrowserSession
import pytest

from app.constants.browser import JEV_SCREENSHOT_QUALITY
from app.constants.log_tags import LogTag
from app.services.browser.jev import page as page_mod
from app.services.browser.jev.page import (
    Covered,
    DocumentReplaced,
    FieldUnfocused,
    JevPage,
    NavigationFailed,
    PageAction,
    PageScriptError,
    PageState,
    PageUnresponsive,
    StalePage,
    TabUnavailable,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

SESSION = "page-1"
TAB = "tab-1"
FIELD = PageAction(id="e1", node=7, kind="fill", label="Name", role="textbox", value="")
DAY = PageAction(id="e4", node=10, kind="fill", label="Day", input_type="date", value="")
LINK = PageAction(id="e2", node=8, kind="click", label="Docs", role="link", value="")
SIZE_L = PageAction(id="e3", node=9, kind="select", label="Size", value="l")
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down the page", delta=560)
LIST = PageAction(
    id="scroll_down_11", node=11, kind="scroll", label="Scroll down in List", delta=240
)
WAIT = PageAction(id="wait", kind="wait", label="Wait for the page to update")
ENTER = PageAction(id="enter", node=7, kind="enter", label="Press Enter in Name")
BACK = PageAction(id="go_back", kind="back", label="Go back to Home", entry=41)
PAGE_KEY = ["key"]
GUARDS = {str(n): [f"guard-of-{n}"] for n in (7, 8, 9, 10, 11)}
#: What Runtime.evaluate answers for a script that threw in the page.
THROWS = object()
#: What it answers when the document went away under the call.
GONE = object()
#: A call the browser refuses outright (cdp_use raises it with the error object).
REFUSED = object()

SNAPSHOT: dict[str, Any] = {
    "url": "https://site.test/",
    "title": "Site",
    "text": "Welcome",
    "text_cut": False,
    "actions": [FIELD, LINK, SIZE_L, SCROLL, WAIT],
    "page_key": PAGE_KEY,
    "guards": GUARDS,
    "omitted_actions": 3,
    "frames": [{"src": "https://pay.test/frame", "same_origin": False, "visible": True}],
}


def _state(**changes: Any) -> PageState:
    """Return the page as observed when SNAPSHOT was read."""
    fields: dict[str, Any] = {
        "url": SNAPSHOT["url"],
        "title": SNAPSHOT["title"],
        "text": SNAPSHOT["text"],
        "text_cut": False,
        "actions": SNAPSHOT["actions"],
        "page_key": PAGE_KEY,
        "guards": GUARDS,
        "frames": SNAPSHOT["frames"],
        "fingerprint": "f",
    }
    return PageState(**(fields | changes))


def _called(expression: str, script: Any) -> tuple[bool, Any]:
    """Whether expression calls script's function, and the argument it passes."""
    head, tail = script.call(None).rsplit("null", 1)
    if not (expression.startswith(head) and expression.endswith(tail)):
        return False, None
    return True, json.loads(expression[len(head) : len(expression) - len(tail)])


@dataclass
class _Tab:
    """One page's CDP session as Chrome answers it: only commands addressed to the page's session.

    Each field is what one of Jev's scripts reads back; a list is answered one item per call.
    """

    snapshots: list[object] = field(default_factory=lambda: [SNAPSHOT])
    page_key: object = field(default_factory=lambda: PAGE_KEY)
    guards: dict[str, object] = field(default_factory=lambda: dict(GUARDS))
    act: dict[int | None, object] = field(default_factory=dict)
    focused: object = True
    value: object = "Ada"
    set: object = "2026-10-01"
    settle: list[object] = field(default_factory=lambda: [True])
    history: dict[str, Any] = field(default_factory=lambda: {"currentIndex": 0, "entries": []})
    body: object = ""
    hangs: str | None = None
    #: Whether the tab still answers a call after refusing one.
    alive: bool = True
    focus: list[bool] = field(default_factory=list, init=False)
    scripts: list[str] = field(default_factory=list, init=False)
    mouse: list[dict[str, Any]] = field(default_factory=list, init=False)
    keys: list[dict[str, Any]] = field(default_factory=list, init=False)
    entries: list[int] = field(default_factory=list, init=False)
    shots: list[dict[str, Any]] = field(default_factory=list, init=False)
    handlers: dict[str, Callable[..., None]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.snapshots = list(self.snapshots)
        self.settle = list(self.settle)
        self.send = SimpleNamespace(
            Emulation=SimpleNamespace(setFocusEmulationEnabled=self._focus),
            Runtime=SimpleNamespace(evaluate=self._evaluate),
            Input=SimpleNamespace(dispatchMouseEvent=self._mouse, dispatchKeyEvent=self._key),
            Page=SimpleNamespace(
                captureScreenshot=self._screenshot,
                getNavigationHistory=self._history,
                navigateToHistoryEntry=self._go_to_entry,
            ),
        )
        self.register = SimpleNamespace(
            Target=SimpleNamespace(targetCreated=self._on("Target.targetCreated")),
            Network=SimpleNamespace(
                requestWillBeSent=self._on("Network.requestWillBeSent"),
                loadingFinished=self._on("Network.loadingFinished"),
                loadingFailed=self._on("Network.loadingFailed"),
            ),
        )

    def _on(self, method: str) -> Callable[[Callable[..., None]], None]:
        def register(handler: Callable[..., None]) -> None:
            self.handlers[method] = handler

        return register

    def emit(self, method: str, event: dict[str, Any], session_id: str | None = SESSION) -> None:
        self.handlers[method](event, session_id)

    async def _command(self, method: str, session_id: str | None) -> None:
        if self.hangs == method:
            await asyncio.Event().wait()
        if session_id != SESSION:
            raise RuntimeError(f"{method} sent to the browser, not the page")

    async def _focus(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Emulation.setFocusEmulationEnabled", session_id)
        self.focus.append(params["enabled"])
        return {}

    async def _evaluate(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Runtime.evaluate", session_id)
        value = self._run(params["expression"])
        if value is REFUSED or (params["expression"] == "0" and not self.alive):
            raise RuntimeError({"code": -32000, "message": "Inspected target navigated or closed"})
        if value is THROWS:
            return {
                "result": {"type": "object"},
                "exceptionDetails": {"text": "Uncaught", "exception": {"description": "Error: x"}},
            }
        if value is GONE:
            return {"result": {"type": "undefined"}}
        return {"result": {"type": "object", "value": value}}

    @staticmethod
    def _next(answers: list[object]) -> object:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    def _run(self, expression: str) -> object:
        if expression == page_mod._SNAPSHOT_JS:
            self.scripts.append("snapshot")
            return self._next(self.snapshots)
        if expression == "0":
            return 0
        for name, script in [
            ("guard", page_mod._GUARD),
            ("act", page_mod._ACT),
            ("focused", page_mod._FOCUSED),
            ("value", page_mod._VALUE),
            ("set", page_mod._SET),
            ("settle", page_mod._SETTLE),
            ("wait", page_mod._WAIT),
        ]:
            called, argument = _called(expression, script)
            if called:
                self.scripts.append(name)
                if name == "guard":
                    return [
                        self.page_key,
                        None if argument is None else self.guards.get(str(argument)),
                    ]
                if name == "act":
                    return self.act.get(argument.get("node"))
                if name == "settle":
                    return self._next(self.settle)
                if name == "wait":
                    return True
                return getattr(self, name)
        body = re.fullmatch(
            r"\(document\.body \? document\.body\.innerText : ''\)\.slice\(0, (\d+)\)", expression
        )
        assert body is not None, f"the tab was sent a script it does not know: {expression[:80]}"
        return self.body if self.body is GONE else str(self.body)[: int(body.group(1))]

    async def _mouse(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Input.dispatchMouseEvent", session_id)
        self.mouse.append(params)
        return {}

    async def _key(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Input.dispatchKeyEvent", session_id)
        self.keys.append(params)
        return {}

    async def _history(self, session_id: str | None) -> dict[str, Any]:
        await self._command("Page.getNavigationHistory", session_id)
        return self.history

    async def _go_to_entry(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Page.navigateToHistoryEntry", session_id)
        self.entries.append(params["entryId"])
        return {}

    async def _screenshot(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Page.captureScreenshot", session_id)
        self.shots.append(params)
        return {"data": "c2hvdA=="}


class _Browser:
    """The Browser-Use session JevPage drives: its page session, navigation and tab switching."""

    def __init__(self, tab: _Tab, *, navigate_error: Exception | None = None) -> None:
        self._tab = tab
        self._navigate_error = navigate_error
        self.cdp_url = ""
        self.navigated: list[str] = []
        self.switched: list[str] = []
        self.event_bus = SimpleNamespace(dispatch=self._dispatch)

    async def get_or_create_cdp_session(self) -> Any:
        if self._tab.hangs == "session":
            await asyncio.Event().wait()
        if self._tab.hangs == "gone":
            raise ValueError("No valid agent focus available")
        return SimpleNamespace(session_id=SESSION, target_id=TAB, cdp_client=self._tab)

    async def navigate_to(self, url: str) -> None:
        self.navigated.append(url)
        if self._navigate_error is not None:
            raise self._navigate_error

    def _dispatch(self, event: Any) -> Awaitable[None]:
        self.switched.append(event.target_id)
        return asyncio.sleep(0)


def _page(tab: _Tab, **browser: Any) -> tuple[JevPage, _Browser]:
    session = _Browser(tab, **browser)
    return JevPage(cast("BrowserSession", session)), session


# --- reading the page --------------------------------------------------------------------


async def test_a_snapshot_is_read_into_the_page_state_with_going_back_when_the_tab_has_history() -> (
    None
):
    tab = _Tab(
        history={
            "currentIndex": 1,
            "entries": [{"id": 41, "url": "https://h.test/", "title": "Home"}, {}],
        }
    )
    page, _ = _page(tab)

    state = await page.observe()

    assert state.actions == [*SNAPSHOT["actions"], BACK]
    assert (state.url, state.text, state.omitted_actions) == ("https://site.test/", "Welcome", 3)
    tab.history = {"currentIndex": 0, "entries": [{}]}
    assert BACK not in (await page.observe()).actions


@pytest.mark.parametrize(
    "moved",
    [
        {"url": "https://site.test/next", "page_key": ["next"]},
        {"text": "Welcome back"},
        {"actions": [FIELD]},
    ],
)
async def test_the_fingerprint_changes_with_what_a_person_sees_never_with_where_a_control_sits(
    moved: dict[str, Any],
) -> None:
    shifted = [
        {**action, "rect": {"x": 1, "y": 2, "w": 3, "h": 4}} for action in SNAPSHOT["actions"]
    ]
    page, _ = _page(_Tab(snapshots=[SNAPSHOT, SNAPSHOT | {"actions": shifted}, SNAPSHOT | moved]))

    first, shifted_state, changed = [await page.observe() for _ in range(3)]

    assert first.fingerprint == shifted_state.fingerprint
    assert changed.fingerprint != first.fingerprint


async def test_a_document_being_replaced_or_still_parsing_is_read_again() -> None:
    page, _ = _page(_Tab(snapshots=[GONE, None, REFUSED, SNAPSHOT]))

    state = await page.observe()

    assert state.url == SNAPSHOT["url"]


async def test_a_page_that_never_settles_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_mod, "JEV_OBSERVE_ATTEMPTS", 3)
    page, _ = _page(_Tab(snapshots=[GONE]))

    with pytest.raises(StalePage, match=page_mod._NOT_SETTLED):
        await page.observe()


async def test_a_script_that_throws_in_the_page_is_reported_not_read_again() -> None:
    tab = _Tab(snapshots=[THROWS, SNAPSHOT])
    page, _ = _page(tab)

    with pytest.raises(PageScriptError, match="Error: x"):
        await page.observe()

    assert tab.scripts == ["snapshot"]


async def test_a_refused_call_on_a_tab_that_no_longer_answers_is_a_tab_gone_not_a_navigation() -> (
    None
):
    page, _ = _page(_Tab(snapshots=[REFUSED], alive=False))

    with pytest.raises(TabUnavailable, match="navigated or closed"):
        await page.observe()


async def test_a_tab_whose_focus_is_gone_is_unavailable() -> None:
    page, _ = _page(_Tab(hangs="gone"))

    with pytest.raises(TabUnavailable, match="No valid agent focus"):
        await page.observe()


# --- the read after an input -------------------------------------------------------------


async def test_the_read_after_an_input_waits_for_its_requests_and_a_quiet_dom_after_them() -> None:
    tab = _Tab(act={8: {"x": 10, "y": 20}}, settle=[True, True])
    page, _ = _page(tab)
    await page.act(LINK, _state())
    tab.emit("Network.requestWillBeSent", {"requestId": "r1", "loaderId": "L1", "type": "Fetch"})

    reading = asyncio.ensure_future(page.observe())
    await asyncio.sleep(0)
    assert not reading.done()
    tab.emit("Network.loadingFinished", {"requestId": "r1"})
    await reading

    # Quiet, then the request finished, then quiet again on what it rendered.
    assert tab.scripts.count("settle") == 2


async def test_a_new_top_document_ends_the_wait_on_loads_of_the_one_before() -> None:
    tab = _Tab(act={8: {"x": 10, "y": 20}}, settle=[GONE, True])
    page, _ = _page(tab)
    await page.act(LINK, _state())
    tab.emit("Network.requestWillBeSent", {"requestId": "old", "loaderId": "L1", "type": "Fetch"})
    tab.emit(
        "Network.requestWillBeSent",
        {"requestId": "L2", "loaderId": "L2", "type": "Document", "frameId": TAB},
    )
    tab.emit("Network.loadingFinished", {"requestId": "L2"})

    await asyncio.wait_for(page.observe(), timeout=1)


async def test_requests_of_another_tab_or_streams_never_hold_the_read() -> None:
    tab = _Tab(act={8: {"x": 10, "y": 20}})
    page, _ = _page(tab)
    await page.act(LINK, _state())
    tab.emit(
        "Network.requestWillBeSent", {"requestId": "a", "loaderId": "L", "type": "Fetch"}, "other"
    )
    tab.emit(
        "Network.requestWillBeSent", {"requestId": "b", "loaderId": "L", "type": "EventSource"}
    )

    await asyncio.wait_for(page.observe(), timeout=1)


async def test_the_read_after_an_input_stops_waiting_at_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(page_mod, "JEV_SETTLE_MAX_SECONDS", 0.05)
    tab = _Tab(act={8: {"x": 10, "y": 20}})
    page, _ = _page(tab)
    await page.act(LINK, _state())
    tab.emit("Network.requestWillBeSent", {"requestId": "poll", "loaderId": "L", "type": "XHR"})

    state = await asyncio.wait_for(page.observe(), timeout=1)

    assert state.url == SNAPSHOT["url"]


async def test_a_wait_waits_for_the_page_to_change_then_settles_and_sends_no_input() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    await page.act(WAIT, _state())
    await page.observe()

    assert tab.scripts[-3:] == ["wait", "settle", "snapshot"]
    assert (tab.mouse, tab.keys) == ([], [])


# --- inputs ------------------------------------------------------------------------------


async def test_a_decision_on_a_page_that_moved_on_sends_no_input() -> None:
    tab = _Tab(guards={"7": ["a different element"]}, act={7: {"x": 1, "y": 1}})
    page, _ = _page(tab)

    with pytest.raises(StalePage, match=page_mod._MOVED_ON):
        await page.act(FIELD, _state(), text="Ada")

    assert (tab.mouse, tab.keys) == ([], [])


async def test_a_target_no_press_reaches_sends_no_input() -> None:
    tab = _Tab(act={8: None})
    page, _ = _page(tab)

    with pytest.raises(Covered):
        await page.act(LINK, _state())

    assert tab.mouse == []


async def test_a_click_presses_where_the_page_says_a_press_reaches_the_target() -> None:
    tab = _Tab(act={8: {"x": 31.5, "y": 44}})
    page, _ = _page(tab)

    await page.act(LINK, _state())

    assert [(e["type"], e["x"], e["y"], e["button"]) for e in tab.mouse] == [
        ("mousePressed", 31.5, 44, "left"),
        ("mouseReleased", 31.5, 44, "left"),
    ]


async def test_typing_replaces_the_focused_fields_text_with_real_keys_and_reads_it_back() -> None:
    tab = _Tab(act={7: {"x": 1, "y": 1}}, value="Ad")
    page, _ = _page(tab)

    held = await page.act(FIELD, _state(), text="aB1")

    assert held == "Ad"
    downs = [k for k in tab.keys if k["type"] == "keyDown"]
    assert downs[0]["commands"] == ["selectAll"]
    assert [(k["key"], k.get("code"), k.get("windowsVirtualKeyCode")) for k in downs[1:]] == [
        ("a", "KeyA", 65),
        ("B", "KeyB", 66),
        ("1", "Digit1", 49),
    ]


async def test_a_field_that_did_not_take_focus_gets_no_keys() -> None:
    tab = _Tab(act={7: {"x": 1, "y": 1}}, focused=False)
    page, _ = _page(tab)

    with pytest.raises(FieldUnfocused):
        await page.act(FIELD, _state(), text="Ada")

    assert tab.keys == []


async def test_a_date_field_is_set_in_its_own_format_and_read_back_without_keys() -> None:
    tab = _Tab(set="")
    page, _ = _page(tab)

    held = await page.act(DAY, _state(), text="10/01/2026")

    assert (held, tab.mouse, tab.keys) == ("", [], [])


async def test_a_dropdown_is_set_in_the_page_without_a_press() -> None:
    tab = _Tab(act={9: {"set": True}})
    page, _ = _page(tab)

    await page.act(SIZE_L, _state())

    assert (tab.mouse, tab.keys) == ([], [])


async def test_enter_is_pressed_only_in_the_field_that_still_holds_focus() -> None:
    tab = _Tab(act={7: {"focused": True}})
    page, _ = _page(tab)

    await page.act(ENTER, _state())

    assert [k["key"] for k in tab.keys] == ["Enter", "Enter"]
    tab.act = {7: None}
    with pytest.raises(Covered):
        await page.act(ENTER, _state())


async def test_going_back_returns_to_the_history_entry_observed() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    await page.act(BACK, _state())

    assert tab.entries == [41]


async def test_the_page_scrolls_over_its_column_and_an_inner_area_where_the_page_says_it_is() -> (
    None
):
    tab = _Tab(act={11: {"x": 70, "y": 90}})
    page, _ = _page(tab)

    await page.act(SCROLL, _state())
    await page.act(LIST, _state())

    assert [(e["x"], e["y"], e["deltaY"]) for e in tab.mouse] == [
        (page_mod._WHEEL_X, page_mod._WHEEL_Y, 560),
        (70, 90, 240),
    ]


# --- tabs, navigation, bounds ------------------------------------------------------------


async def test_a_tab_the_clicked_tab_opened_is_followed_and_one_another_tab_opened_is_not() -> None:
    tab = _Tab(act={8: {"x": 1, "y": 1}})
    page, browser = _page(tab)
    await page.act(LINK, _state())
    tab.emit(
        "Target.targetCreated",
        {"targetInfo": {"targetId": "elsewhere", "type": "page", "openerId": "tab-9"}},
    )

    assert await page.follow_new_tab() is False

    await page.act(LINK, _state())
    tab.emit(
        "Target.targetCreated",
        {"targetInfo": {"targetId": "popup", "type": "page", "openerId": TAB}},
    )

    assert await page.follow_new_tab() is True
    assert browser.switched == ["popup"]


async def test_opening_an_address_navigates_the_tab_there() -> None:
    page, browser = _page(_Tab())

    await page.navigate("https://site.test/b")

    assert browser.navigated == ["https://site.test/b"]


@pytest.mark.parametrize(
    ("error", "raised"),
    [
        (RuntimeError("Navigation failed: net::ERR_NAME_NOT_RESOLVED"), NavigationFailed),
        (RuntimeError({"code": -32000, "message": "navigation refused"}), TabUnavailable),
    ],
    ids=["the-site-failed", "the-browser-refused"],
)
async def test_a_failed_navigation_says_whether_the_site_or_the_browser_failed(
    error: Exception, raised: type[Exception]
) -> None:
    page, _ = _page(_Tab(), navigate_error=error)

    with pytest.raises(raised):
        await page.navigate("https://site.test/b")


@pytest.mark.parametrize("hangs", ["session", "Runtime.evaluate", "Input.dispatchMouseEvent"])
async def test_a_call_the_tab_never_answers_raises_and_names_the_call(
    monkeypatch: pytest.MonkeyPatch, hangs: str
) -> None:
    monkeypatch.setattr(page_mod, "JEV_CDP_TIMEOUT_SECONDS", 0.01)
    page, _ = _page(_Tab(hangs=hangs, act={8: {"x": 1, "y": 1}}))

    async with captured_wide_event() as event:
        with pytest.raises(PageUnresponsive):
            await page.act(LINK, _state())

    [warning] = event["warnings"]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["call"] == ("the page's CDP session" if hangs == "session" else hangs)


async def test_the_tab_is_told_to_render_as_focused_once_not_on_every_call() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    await page.observe()
    await page.observe()

    assert tab.focus == [True]


async def test_the_page_text_is_read_from_the_whole_body_up_to_the_limit() -> None:
    page, _ = _page(_Tab(body="abcdef"))

    assert await page.body_text(4) == "abcd"


async def test_a_document_replaced_under_a_read_raises_as_replaced() -> None:
    page, _ = _page(_Tab(body=GONE))

    with pytest.raises(DocumentReplaced):
        await page.body_text(4)


async def test_the_card_photo_is_a_jpeg_of_the_tab() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    assert await page.screenshot() == "c2hvdA=="
    assert tab.shots == [{"format": "jpeg", "quality": JEV_SCREENSHOT_QUALITY}]
