"""Jev's view of the browser: one atomic snapshot per observation, one guarded input per action.

Runs over the Browser-Use session's CDP connection on the focused tab. Ported
from browser-use/jev-ultrafast (MIT) jev_ultrafast/browser.py: the snapshot
and its guards run in the page, geometry and occlusion are re-read just
before input, and no input is ever retried.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict, TypeVar, cast

from app.constants.browser import (
    JEV_CDP_TIMEOUT_SECONDS,
    JEV_OBSERVE_ATTEMPTS,
    JEV_OBSERVE_RETRY_SECONDS,
    JEV_SCREENSHOT_QUALITY,
    JEV_WAIT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserAutomationError
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession, CDPSession
    from cdp_use.cdp.input.commands import DispatchKeyEventParameters, DispatchMouseEventParameters

_ASSETS = Path(__file__).parent
_SNAPSHOT_JS = (_ASSETS / "snapshot.js").read_text()
_ACT_JS = (_ASSETS / "act.js").read_text().strip()
_SETTLE_JS = (_ASSETS / "settle.js").read_text().strip()
_GUARD_JS = (_ASSETS / "guard.js").read_text().strip()
# The snapshot's full marker, recomputed in place: equal only when nothing it read changed.
_MARKER_JS = f"(() => {{ const state={_SNAPSHOT_JS}; return state?.marker ?? null; }})()"
#: Ctrl on every platform the hosts run (Linux); select-all before text replaces a field.
_CTRL = 2

_T = TypeVar("_T")

ActionKind = Literal["click", "fill", "secret", "select", "scroll", "wait"]


class StalePage(BrowserAutomationError):
    """The decision no longer refers to the observed page; nothing was executed."""


class Covered(StalePage):
    """The target is hidden, disabled, off-screen or covered at its centre."""


class PageUnresponsive(BrowserAutomationError):
    """A CDP call got no answer in time; whether an input it carried took effect is unknown."""


class UncertainSelect(BrowserAutomationError):
    """A dropdown change was interrupted and may already have fired; inspect before retrying."""


class Rect(TypedDict):
    x: float
    y: float
    w: float
    h: float


class PageAction(TypedDict):
    """One executable target from the snapshot; ids are code-owned, never model-written."""

    id: str
    kind: ActionKind
    label: str
    node: NotRequired[int]
    role: NotRequired[str]
    ident: NotRequired[str]
    value: NotRequired[str]
    current_value: NotRequired[str]
    checked: NotRequired[str]
    selected: NotRequired[str]
    expanded: NotRequired[str]
    filled: NotRequired[bool]
    delta: NotRequired[int]
    rect: NotRequired[Rect]


class Frame(TypedDict):
    src: str
    same_origin: bool
    visible: bool


class _Scroll(TypedDict):
    y: float
    height: float


class _Snapshot(TypedDict):
    url: str
    title: str
    text: str
    actions: list[PageAction]
    marker: object
    page_key: object
    guards: dict[str, object]
    omitted_actions: int
    frames: list[Frame]
    scroll: _Scroll


@dataclass(frozen=True)
class PageState:
    """One atomic observation of the focused tab."""

    url: str
    title: str
    text: str
    actions: list[PageAction]
    marker: object
    page_key: object
    guards: dict[str, object]
    frames: list[Frame]
    fingerprint: str

    def action(self, action_id: str) -> PageAction:
        return next(a for a in self.actions if a["id"] == action_id)


def _fingerprint(snapshot: _Snapshot) -> str:
    content = {
        "url": snapshot["url"],
        "text": snapshot["text"],
        "actions": snapshot["actions"],
        "scroll": snapshot["scroll"],
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


async def _bounded(call: Awaitable[_T], what: str) -> _T:
    """Await one CDP call, raising PageUnresponsive when it gets no answer in time."""
    try:
        return await asyncio.wait_for(call, timeout=JEV_CDP_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        log.warning(f"{LogTag.BROWSER} Jev CDP call got no answer", call=what)
        raise PageUnresponsive(f"{what} got no answer in {JEV_CDP_TIMEOUT_SECONDS:.0f}s") from exc


class JevPage:
    """The focused tab of one Browser-Use session, as Jev observes and drives it."""

    def __init__(self, browser: BrowserSession) -> None:
        self._browser = browser
        #: The last input, whose effect the next observation waits a frame or two for.
        self._after_input: PageAction | None = None

    async def _session(self) -> CDPSession:
        return await _bounded(self._browser.get_or_create_cdp_session(), "the page's CDP session")

    async def _evaluate(self, expression: str, *, await_promise: bool = False) -> object:
        session = await self._session()
        response = await _bounded(
            session.cdp_client.send.Runtime.evaluate(
                params={
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": await_promise,
                },
                session_id=session.session_id,
            ),
            "Runtime.evaluate",
        )
        if response.get("exceptionDetails"):
            raise StalePage("The document changed during evaluation.")
        return response.get("result", {}).get("value")

    async def observe(self) -> PageState:
        """Read the page once; retried briefly while a navigation is replacing the document."""
        if self._after_input is not None:
            action, self._after_input = self._after_input, None
            # Read-only and after execution was recorded, so a navigation cutting it short loses nothing.
            try:
                await self._evaluate(f"{_SETTLE_JS}({json.dumps(action)})", await_promise=True)
            except StalePage:
                pass
        for _ in range(JEV_OBSERVE_ATTEMPTS):
            try:
                value = await self._evaluate(_SNAPSHOT_JS)
            except StalePage:
                value = None
            if value is not None:
                snapshot = cast("_Snapshot", value)
                return PageState(
                    url=snapshot["url"],
                    title=snapshot["title"],
                    text=snapshot["text"],
                    actions=snapshot["actions"],
                    marker=snapshot["marker"],
                    page_key=snapshot["page_key"],
                    guards=snapshot["guards"],
                    frames=snapshot["frames"],
                    fingerprint=_fingerprint(snapshot),
                )
            await asyncio.sleep(JEV_OBSERVE_RETRY_SECONDS)
        raise StalePage("The page did not settle.")

    async def fresh(self, page: PageState, action: PageAction | None = None) -> bool:
        """Whether a decision made on page still holds.

        An element decision checks the page key and its own target's guard, so
        unrelated visible change (a ticking countdown) does not invalidate it; a
        page-level one checks the whole snapshot marker.
        """
        if action is not None and "node" in action:
            node = action["node"]
            current = await self._evaluate(f"{_GUARD_JS}({json.dumps(node)})")
            return current == [page.page_key, page.guards.get(str(node))]
        return await self._evaluate(_MARKER_JS) == page.marker

    async def act(self, action: PageAction, page: PageState, text: str | None = None) -> None:
        """Execute one observed action; raises before any input when the page moved on."""
        if not await self.fresh(page, action if action["kind"] != "scroll" else None):
            raise StalePage("The page changed since this decision.")
        kind = action["kind"]
        if kind == "wait":
            await asyncio.sleep(JEV_WAIT_SECONDS)
            return
        session = await self._session()
        if kind == "scroll":
            await self._mouse(
                session,
                {"type": "mouseWheel", "x": 550, "y": 400, "deltaX": 0, "deltaY": action.get("delta", 0)},
            )
            self._after_input = action
            return
        try:
            point = await self._evaluate(f"{_ACT_JS}({json.dumps(action)})")
        except StalePage as exc:
            if kind == "select":
                raise UncertainSelect("The dropdown change was interrupted.") from exc
            raise
        if point is None:
            if kind == "select":
                raise UncertainSelect("The dropdown change was not confirmed.")
            raise Covered("The target changed or is covered.")
        self._after_input = action
        if kind == "select":
            return
        x, y = cast("dict[str, float]", point)["x"], cast("dict[str, float]", point)["y"]
        for event in ("mousePressed", "mouseReleased"):
            await self._mouse(
                session, {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1}
            )
        if kind in ("fill", "secret") and text is not None:
            await self._key(
                session,
                {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": _CTRL, "commands": ["selectAll"]},
            )
            await self._key(session, {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": _CTRL})
            # One key event per character, as a person types: Input.insertText
            # fires no key events, and a date picker or <input type=time> that
            # parses keystrokes then drops the value (measured on Chrome).
            for char in text:
                key = "Enter" if char == "\n" else char
                typed = "\r" if char == "\n" else char
                await self._key(session, {"type": "keyDown", "key": key, "text": typed})
                await self._key(session, {"type": "keyUp", "key": key})

    async def press_enter(self) -> None:
        """Press Enter in whatever holds focus: submits a typed search or form."""
        session = await self._session()
        for event in ("keyDown", "keyUp"):
            await self._key(
                session,
                {"type": event, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
            )

    async def _mouse(self, session: CDPSession, params: DispatchMouseEventParameters) -> None:
        await _bounded(
            session.cdp_client.send.Input.dispatchMouseEvent(params=params, session_id=session.session_id),
            "Input.dispatchMouseEvent",
        )

    async def _key(self, session: CDPSession, params: DispatchKeyEventParameters) -> None:
        await _bounded(
            session.cdp_client.send.Input.dispatchKeyEvent(params=params, session_id=session.session_id),
            "Input.dispatchKeyEvent",
        )

    async def navigate(self, url: str) -> None:
        await self._browser.navigate_to(url)

    async def go_back(self) -> None:
        await self._evaluate("history.back()")

    async def follow_new_tab(self, tabs_before: set[str]) -> bool:
        """Focus a tab the last input opened, as a person would; True when one opened."""
        from browser_use.browser.events import SwitchTabEvent  # noqa: PLC0415 -- heavy optional dep

        tabs = await self._browser.get_tabs()
        opened = [tab.target_id for tab in tabs if tab.target_id not in tabs_before]
        if not opened:
            return False
        event = self._browser.event_bus.dispatch(SwitchTabEvent(target_id=opened[-1]))
        await event
        return True

    async def tab_ids(self) -> set[str]:
        return {tab.target_id for tab in await self._browser.get_tabs()}

    async def screenshot(self) -> str:
        """The focused tab as a base64 JPEG, for the step card."""
        session = await self._session()
        result = await _bounded(
            session.cdp_client.send.Page.captureScreenshot(
                params={"format": "jpeg", "quality": JEV_SCREENSHOT_QUALITY},
                session_id=session.session_id,
            ),
            "Page.captureScreenshot",
        )
        return str(result["data"])
