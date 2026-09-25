"""Jev's hands on the tab: every CDP call bounded, no input on a stale or covered target, typing as a person types."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import re
from types import SimpleNamespace
from typing import Any

import pytest

from app.constants.browser import (
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
    JEV_SCREENSHOT_QUALITY,
)
from app.constants.log_tags import LogTag
from app.services.browser.jev import page as page_mod
from app.services.browser.jev.page import (
    Covered,
    JevPage,
    NavigationFailed,
    PageAction,
    PageState,
    PageUnresponsive,
    StalePage,
    UncertainSelect,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

SESSION = "page-1"
FIELD = PageAction(id="e1", node=7, kind="fill", label="Name", role="textbox", value="")
LINK = PageAction(id="e2", node=8, kind="click", label="Docs", role="link", value="")
SIZE_L = PageAction(id="e3", node=9, kind="select", label="Size → Large", value="l")
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down", delta=560)
WAIT = PageAction(id="wait", kind="wait", label="Wait for the page to update")
PAGE_KEY = ["key"]
MARKER = ["marker"]
GUARDS = {"7": ["guard-of-7"], "8": ["guard-of-8"], "9": ["guard-of-9"]}
#: What Runtime.evaluate reports when the script threw (the document was replaced under it).
THROWS = object()

SNAPSHOT: dict[str, Any] = {
    "url": "https://site.test/",
    "title": "Site",
    "w": BROWSER_VIEWPORT_WIDTH,
    "h": BROWSER_VIEWPORT_HEIGHT,
    "text": "Welcome",
    "scroll": {"y": 0, "height": 2400},
    "actions": [FIELD, LINK, SIZE_L, SCROLL, WAIT],
    "marker": MARKER,
    "page_key": PAGE_KEY,
    "guards": GUARDS,
    "omitted_actions": 0,
    "frames": [{"src": "https://pay.test/frame", "same_origin": False, "visible": True}],
}


def _state(**changes: Any) -> PageState:
    """Return the page as observed when SNAPSHOT was read."""
    fields: dict[str, Any] = {
        "url": SNAPSHOT["url"],
        "title": SNAPSHOT["title"],
        "text": SNAPSHOT["text"],
        "actions": SNAPSHOT["actions"],
        "marker": MARKER,
        "page_key": PAGE_KEY,
        "guards": GUARDS,
        "frames": SNAPSHOT["frames"],
        "fingerprint": "f",
    }
    return PageState(**(fields | changes))


def _call_argument(expression: str, script: str) -> Any:
    return json.loads(expression[len(script) + 1 : -1])


class _Tab:
    """One page's CDP session as Chrome answers it: only commands addressed to the page's session."""

    def __init__(
        self,
        *,
        snapshots: list[object] | None = None,
        marker: object = MARKER,
        page_key: object = PAGE_KEY,
        guards: dict[str, object] | None = None,
        points: dict[int, object] | None = None,
        settle: object = None,
        body: str = "",
        hangs: str | None = None,
    ) -> None:
        self.snapshots = list(snapshots or [SNAPSHOT])
        self.marker = marker
        self.page_key = page_key
        self.guards = GUARDS if guards is None else guards
        self.points = points or {}
        self.settle = settle
        self.body = body
        self.hangs = hangs
        self.focus: list[bool] = []
        self.settled: list[dict[str, Any]] = []
        self.acted: list[dict[str, Any]] = []
        self.went_back = 0
        self.mouse: list[dict[str, Any]] = []
        self.keys: list[dict[str, Any]] = []
        self.shots: list[dict[str, Any]] = []
        self.send = SimpleNamespace(
            Emulation=SimpleNamespace(setFocusEmulationEnabled=self._focus),
            Runtime=SimpleNamespace(evaluate=self._evaluate),
            Input=SimpleNamespace(dispatchMouseEvent=self._mouse, dispatchKeyEvent=self._key),
            Page=SimpleNamespace(captureScreenshot=self._screenshot),
        )

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
        value = self._run(params["expression"], awaited=params["awaitPromise"])
        if value is THROWS:
            return {"result": {"type": "object"}, "exceptionDetails": {"text": "Uncaught"}}
        if isinstance(value, dict | list) and not params["returnByValue"]:
            return {"result": {"type": "object", "objectId": "remote-1"}}
        return {"result": {"type": "undefined"} if value is None else {"value": value}}

    def _run(self, expression: str, *, awaited: bool) -> object:
        if expression == page_mod._SNAPSHOT_JS:
            return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if expression == page_mod._MARKER_JS:
            return self.marker
        if expression.startswith(page_mod._GUARD_JS):
            node = _call_argument(expression, page_mod._GUARD_JS)
            if self.page_key is THROWS:
                return THROWS
            return [self.page_key, self.guards.get(str(node))]
        if expression.startswith(page_mod._ACT_JS):
            action = _call_argument(expression, page_mod._ACT_JS)
            self.acted.append(action)
            return self.points.get(action.get("node"))
        if expression.startswith(page_mod._SETTLE_JS):
            if awaited:
                self.settled.append(_call_argument(expression, page_mod._SETTLE_JS))
            return self.settle
        if expression == "history.back()":
            self.went_back += 1
            return None
        body = re.fullmatch(
            r"\(document\.body \? document\.body\.innerText : ''\)\.slice\(0, (\d+)\)", expression
        )
        assert body is not None, f"the tab was sent a script it does not know: {expression[:80]}"
        return self.body[: int(body.group(1))]

    async def _mouse(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Input.dispatchMouseEvent", session_id)
        self.mouse.append(params)
        return {}

    async def _key(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Input.dispatchKeyEvent", session_id)
        self.keys.append(params)
        return {}

    async def _screenshot(self, params: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        await self._command("Page.captureScreenshot", session_id)
        self.shots.append(params)
        return {"data": "c2hvdA=="}


class _Browser:
    """The Browser-Use session JevPage drives: its page session, navigation and tabs."""

    def __init__(
        self,
        tab: _Tab,
        *,
        navigate_error: Exception | None = None,
        tabs: list[str] | None = None,
    ) -> None:
        self._tab = tab
        self._navigate_error = navigate_error
        self.tabs = tabs or ["tab-1"]
        self.navigated: list[str | None] = []
        self.switched: list[str] = []
        self.event_bus = SimpleNamespace(dispatch=self._dispatch)

    async def get_or_create_cdp_session(self) -> Any:
        if self._tab.hangs == "session":
            await asyncio.Event().wait()
        return SimpleNamespace(session_id=SESSION, cdp_client=self._tab)

    async def navigate_to(self, url: str | None) -> None:
        self.navigated.append(url)
        if self._navigate_error is not None:
            raise self._navigate_error

    async def get_tabs(self) -> list[Any]:
        return [SimpleNamespace(target_id=target) for target in self.tabs]

    def _dispatch(self, event: Any) -> Awaitable[None]:
        self.switched.append(event.target_id)
        return asyncio.sleep(0)


def _page(tab: _Tab, **browser: Any) -> tuple[JevPage, _Browser]:
    session = _Browser(tab, **browser)
    return JevPage(session), session  # type: ignore[arg-type]  # the calls JevPage makes of a session


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_mod, "JEV_OBSERVE_RETRY_SECONDS", 0)
    monkeypatch.setattr(page_mod, "JEV_WAIT_SECONDS", 0)


async def test_a_snapshot_is_read_into_the_page_state() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    state = await page.observe()

    assert state == _state(fingerprint=state.fingerprint)
    assert state.action("e2") == LINK
    # No input preceded this read, so there was nothing to wait for.
    assert tab.settled == []


def _moved(field: str) -> dict[str, Any]:
    changed = {
        "url": "https://site.test/next",
        "text": "Welcome back",
        "actions": [FIELD],
        "scroll": {"y": 560, "height": 2400},
    }
    return SNAPSHOT | {field: changed[field]}


@pytest.mark.parametrize("field", ["url", "text", "actions", "scroll"])
async def test_the_fingerprint_changes_with_what_a_person_sees(field: str) -> None:
    page, _ = _page(_Tab(snapshots=[SNAPSHOT, SNAPSHOT, _moved(field)]))

    first, again, moved = [await page.observe() for _ in range(3)]

    assert first.fingerprint == again.fingerprint
    assert moved.fingerprint != first.fingerprint


async def test_the_fingerprint_ignores_a_marker_that_ticks() -> None:
    page, _ = _page(_Tab(snapshots=[SNAPSHOT, SNAPSHOT | {"marker": ["ticked"]}]))

    first, ticked = await page.observe(), await page.observe()

    assert ticked.fingerprint == first.fingerprint


async def test_a_page_being_replaced_is_read_again_until_it_settles() -> None:
    page, _ = _page(_Tab(snapshots=[None, THROWS, SNAPSHOT]))

    state = await page.observe()

    assert state.url == SNAPSHOT["url"]


async def test_a_page_that_never_settles_is_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_mod, "JEV_OBSERVE_ATTEMPTS", 3)
    page, _ = _page(_Tab(snapshots=[None]))

    with pytest.raises(StalePage, match=page_mod._NOT_SETTLED):
        await page.observe()


async def test_the_read_after_an_input_waits_for_that_input_to_settle_once() -> None:
    tab = _Tab(points={8: {"x": 10, "y": 20}})
    page, _ = _page(tab)

    await page.act(LINK, _state())
    await page.observe()
    await page.observe()

    assert tab.settled == [LINK]


async def test_a_navigation_that_cuts_the_settle_wait_short_still_reads_the_new_page() -> None:
    tab = _Tab(points={8: {"x": 10, "y": 20}}, settle=THROWS)
    page, _ = _page(tab)

    await page.act(LINK, _state())
    state = await page.observe()

    assert state.url == SNAPSHOT["url"]


async def test_an_element_decision_holds_while_its_page_and_target_do_though_other_parts_tick() -> (
    None
):
    page, _ = _page(_Tab(marker=["ticked"]))

    assert await page.fresh(_state(), FIELD) is True


@pytest.mark.parametrize(
    "tab",
    [
        _Tab(page_key=["another page"]),
        _Tab(guards={"7": ["the element moved"]}),
    ],
)
async def test_an_element_decision_is_stale_once_its_page_or_target_changed(tab: _Tab) -> None:
    page, _ = _page(tab)

    assert await page.fresh(_state(), FIELD) is False


@pytest.mark.parametrize(("marker", "fresh"), [(MARKER, True), (["scrolled"], False)])
async def test_a_page_level_decision_holds_only_while_the_whole_page_does(
    marker: object, fresh: bool
) -> None:
    page, _ = _page(_Tab(marker=marker))

    assert await page.fresh(_state()) is fresh
    assert await page.fresh(_state(), SCROLL) is fresh


async def test_a_decision_on_a_page_that_moved_on_sends_no_input() -> None:
    tab = _Tab(guards={"7": ["a different element"]}, points={7: {"x": 1, "y": 1}})
    page, _ = _page(tab)

    with pytest.raises(StalePage, match=page_mod._MOVED_ON):
        await page.act(FIELD, _state(), text="Ada")

    assert (tab.acted, tab.mouse, tab.keys) == ([], [], [])


async def test_a_covered_target_sends_no_input() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    with pytest.raises(Covered, match=page_mod._COVERED):
        await page.act(FIELD, _state(), text="Ada")

    assert (tab.mouse, tab.keys) == ([], [])


async def test_a_click_presses_and_releases_the_left_button_once_at_the_targets_centre() -> None:
    tab = _Tab(points={8: {"x": 40, "y": 60}})
    page, _ = _page(tab)

    await page.act(LINK, _state())

    assert tab.acted == [LINK]
    assert tab.mouse == [
        {"type": "mousePressed", "x": 40, "y": 60, "button": "left", "clickCount": 1},
        {"type": "mouseReleased", "x": 40, "y": 60, "button": "left", "clickCount": 1},
    ]
    assert tab.keys == []


async def test_typing_clicks_the_field_selects_its_text_and_sends_one_key_per_character() -> None:
    tab = _Tab(points={7: {"x": 40, "y": 60}})
    page, _ = _page(tab)

    await page.act(FIELD, _state(), text="Ab")

    assert [event["type"] for event in tab.mouse] == ["mousePressed", "mouseReleased"]
    select_all, typed = tab.keys[:2], tab.keys[2:]
    # Ctrl+A with the selectAll command: what is typed replaces the field's text.
    assert [(event["type"], event["key"]) for event in select_all] == [
        ("keyDown", "a"),
        ("keyUp", "a"),
    ]
    assert select_all[0]["commands"] == ["selectAll"]
    # A date or time field that parses keystrokes drops a value inserted any other way.
    assert typed == [
        {"type": "keyDown", "key": "A", "text": "A"},
        {"type": "keyUp", "key": "A"},
        {"type": "keyDown", "key": "b", "text": "b"},
        {"type": "keyUp", "key": "b"},
    ]


async def test_a_typed_line_break_presses_enter_as_press_enter_does() -> None:
    typing, pressing = _Tab(points={7: {"x": 1, "y": 1}}), _Tab()
    typed, _ = _page(typing)
    pressed, _ = _page(pressing)

    await typed.act(FIELD, _state(), text="a\nb")
    await pressed.press_enter()

    assert typing.keys[4:6] == pressing.keys
    assert [event["key"] for event in typing.keys[6:]] == ["b", "b"]
    assert [(event["type"], event["key"], event["text"]) for event in pressing.keys] == [
        ("keyDown", "Enter", "\r"),
        ("keyUp", "Enter", "\r"),
    ]


async def test_a_wait_sends_no_input() -> None:
    tab = _Tab(points={7: {"x": 1, "y": 1}})
    page, _ = _page(tab)

    await page.act(WAIT, _state())

    assert (tab.acted, tab.mouse, tab.keys) == ([], [], [])


async def test_a_scroll_turns_the_wheel_inside_the_viewport_and_settles_before_the_next_read() -> (
    None
):
    tab = _Tab()
    page, _ = _page(tab)

    await page.act(SCROLL, _state())
    await page.observe()

    [wheel] = tab.mouse
    assert (wheel["type"], wheel["deltaX"], wheel["deltaY"]) == ("mouseWheel", 0, 560)
    assert 0 < wheel["x"] < BROWSER_VIEWPORT_WIDTH
    assert 0 < wheel["y"] < BROWSER_VIEWPORT_HEIGHT
    assert tab.settled == [SCROLL]


async def test_a_scroll_on_a_page_that_moved_turns_nothing() -> None:
    tab = _Tab(marker=["scrolled"])
    page, _ = _page(tab)

    with pytest.raises(StalePage):
        await page.act(SCROLL, _state())

    assert tab.mouse == []


async def test_a_dropdown_is_set_in_the_page_without_a_click_and_settles_before_the_next_read() -> (
    None
):
    tab = _Tab(points={9: {"x": 5, "y": 5}})
    page, _ = _page(tab)

    await page.act(SIZE_L, _state())
    await page.observe()

    assert tab.acted == [SIZE_L]
    assert tab.mouse == []
    assert tab.settled == [SIZE_L]


@pytest.mark.parametrize(
    ("answer", "why"),
    [(THROWS, page_mod._SELECT_INTERRUPTED), (None, page_mod._SELECT_UNCONFIRMED)],
)
async def test_a_dropdown_change_that_may_have_fired_is_uncertain_not_stale(
    answer: object, why: str
) -> None:
    page, _ = _page(_Tab(points={9: answer}))

    with pytest.raises(UncertainSelect, match=why):
        await page.act(SIZE_L, _state())


async def test_a_click_interrupted_by_a_navigation_is_stale_and_sends_no_input() -> None:
    tab = _Tab(points={8: THROWS})
    page, _ = _page(tab)

    with pytest.raises(StalePage, match=page_mod._CHANGED_DURING_EVALUATION) as raised:
        await page.act(LINK, _state())

    assert type(raised.value) is StalePage
    assert tab.mouse == []


def _hanging_calls() -> list[tuple[str, str, Callable[[JevPage], Awaitable[object]]]]:
    return [
        ("session", page_mod._SESSION_CALL, lambda page: page.body_text(10)),
        (
            "Emulation.setFocusEmulationEnabled",
            "Emulation.setFocusEmulationEnabled",
            lambda page: page.body_text(10),
        ),
        ("Runtime.evaluate", "Runtime.evaluate", lambda page: page.body_text(10)),
        (
            "Input.dispatchMouseEvent",
            "Input.dispatchMouseEvent",
            lambda page: page.act(LINK, _state()),
        ),
        ("Input.dispatchKeyEvent", "Input.dispatchKeyEvent", lambda page: page.press_enter()),
        ("Page.captureScreenshot", "Page.captureScreenshot", lambda page: page.screenshot()),
    ]


@pytest.mark.parametrize(("hangs", "named", "call"), _hanging_calls())
async def test_a_call_the_tab_never_answers_raises_and_names_the_call(
    monkeypatch: pytest.MonkeyPatch,
    hangs: str,
    named: str,
    call: Callable[[JevPage], Awaitable[object]],
) -> None:
    monkeypatch.setattr(page_mod, "JEV_CDP_TIMEOUT_SECONDS", 0.05)
    page, _ = _page(_Tab(hangs=hangs, points={8: {"x": 1, "y": 1}}))

    async with captured_wide_event() as event:
        with pytest.raises(PageUnresponsive, match=named):
            await call(page)

    [warning] = event["warnings"]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["call"] == named


async def test_the_tab_is_told_to_render_as_focused_once_not_on_every_call() -> None:
    tab = _Tab(body="text")
    page, _ = _page(tab)

    await page.body_text(10)
    await page.body_text(10)

    assert tab.focus == [True]


async def test_the_page_text_is_read_from_the_whole_body_up_to_the_limit() -> None:
    page, _ = _page(_Tab(body="Headline and the article below it"))

    assert await page.body_text(8) == "Headline"


async def test_opening_an_address_navigates_the_tab_there() -> None:
    page, browser = _page(_Tab())

    await page.navigate("https://docs.test/")

    assert browser.navigated == ["https://docs.test/"]


async def test_an_address_that_cannot_be_opened_is_a_navigation_failure() -> None:
    page, _ = _page(
        _Tab(), navigate_error=RuntimeError("Navigation failed: net::ERR_NAME_NOT_RESOLVED")
    )

    with pytest.raises(NavigationFailed, match="ERR_NAME_NOT_RESOLVED"):
        await page.navigate("https://gone.test/")


async def test_going_back_goes_back_in_the_tabs_history() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    await page.go_back()

    assert tab.went_back == 1


async def test_a_tab_the_last_input_opened_is_followed_and_the_newest_one_wins() -> None:
    page, browser = _page(_Tab(), tabs=["tab-1", "tab-2", "tab-3", "tab-4"])

    followed = await page.follow_new_tab({"tab-1"})

    assert followed is True
    assert browser.switched == ["tab-4"]


async def test_no_tab_is_followed_when_the_input_opened_none() -> None:
    page, browser = _page(_Tab(), tabs=["tab-1", "tab-2"])

    assert await page.tab_ids() == {"tab-1", "tab-2"}
    assert await page.follow_new_tab({"tab-1", "tab-2"}) is False
    assert browser.switched == []


async def test_the_card_photo_is_a_jpeg_of_the_tab() -> None:
    tab = _Tab()
    page, _ = _page(tab)

    shot = await page.screenshot()

    assert shot == "c2hvdA=="
    assert tab.shots == [{"format": "jpeg", "quality": JEV_SCREENSHOT_QUALITY}]


@pytest.mark.parametrize("action", [FIELD, None])
async def test_a_decision_on_a_document_being_replaced_no_longer_holds(
    action: PageAction | None,
) -> None:
    page, _ = _page(_Tab(marker=THROWS, page_key=THROWS))

    assert await page.fresh(_state(), action) is False
