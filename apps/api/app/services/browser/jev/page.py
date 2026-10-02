"""Jev's view of the browser: one atomic snapshot per observation, one guarded input per action.

Runs over the Browser-Use session's CDP connection on the focused tab. Ported
from browser-use/jev-ultrafast (MIT) jev_ultrafast/browser.py: the snapshot
and its guards run in the page, reachability is hit-tested again just before
input, no input is ever retried, and the read after an input waits on the
page's own facts (DOM and network quiet), not on a timer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import contextlib
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, TypeVar, cast, final

from browser_use.browser.events import SwitchTabEvent
from browser_use.browser.session import BrowserSession, CDPSession
from cdp_use.cdp.input.commands import DispatchKeyEventParameters, DispatchMouseEventParameters
from cdp_use.cdp.network.events import (
    LoadingFailedEvent,
    LoadingFinishedEvent,
    RequestWillBeSentEvent,
)
from cdp_use.cdp.page.commands import CaptureScreenshotReturns, GetNavigationHistoryReturns
from cdp_use.cdp.page.events import DomContentEventFiredEvent
from cdp_use.cdp.page.types import NavigationEntry
from cdp_use.cdp.runtime.commands import EvaluateReturns
from cdp_use.cdp.runtime.types import ExceptionDetails, RemoteObject
from cdp_use.cdp.target.events import TargetCreatedEvent
from cdp_use.cdp.target.types import TargetInfo
from cdp_use.client import CDPClient

from app.constants.browser import (
    BROWSER_STEP_PHOTO_QUALITY,
    JEV_CDP_TIMEOUT_SECONDS,
    JEV_OBSERVE_ATTEMPTS,
    JEV_PARSE_WAIT_SECONDS,
    JEV_SETTLE_MAX_SECONDS,
    JEV_WAIT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.patches.obscura_sessions import on_obscura
from app.services.browser.exceptions import BrowserAutomationError
from shared.py.wide_events import log

_ASSETS = Path(__file__).parent
_SNAPSHOT_JS = (_ASSETS / "snapshot.js").read_text()


@dataclass(frozen=True)
class _PageFunction:
    """One of Jev's scripts: a named function declaration, called inside an IIFE so the page keeps no global."""

    source: str
    name: str

    def call(self, argument: object) -> str:
        return f"(() => {{\n{self.source}\nreturn {self.name}({json.dumps(argument)});\n}})()"


_ACT_JS = (_ASSETS / "act.js").read_text()
_SETTLE_JS = (_ASSETS / "settle.js").read_text()
_ACT = _PageFunction(_ACT_JS, "gaiaJevAct")
_FOCUSED = _PageFunction(_ACT_JS, "gaiaJevFocused")
_VALUE = _PageFunction(_ACT_JS, "gaiaJevValue")
_SET = _PageFunction(_ACT_JS, "gaiaJevSet")
_SETTLE = _PageFunction(_SETTLE_JS, "gaiaJevSettle")
_WAIT = _PageFunction(_SETTLE_JS, "gaiaJevWait")
_GUARD = _PageFunction((_ASSETS / "guard.js").read_text(), "gaiaJevGuard")
#: Ctrl on every platform the hosts run (Linux); select-all before text replaces a field.
_CTRL = 2
_SHIFT = 8
_SELECT_ALL: tuple[DispatchKeyEventParameters, ...] = (
    {
        "type": "keyDown",
        "key": "a",
        "code": "KeyA",
        "windowsVirtualKeyCode": 65,
        "modifiers": _CTRL,
        "commands": ["selectAll"],
    },
    {"type": "keyUp", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "modifiers": _CTRL},
)
_ENTER: tuple[DispatchKeyEventParameters, ...] = (
    {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
    {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
)
#: Where the wheel turns to scroll the page itself: over its main column, inside the viewport.
_WHEEL_X, _WHEEL_Y = 550, 400
#: Inputs whose value is a format the browser parses, not keystrokes: set in the page, then read back.
_SET_IN_PAGE = frozenset({"date", "time", "datetime-local", "month", "week", "range"})
#: Request types that stay open by design; a page waiting on one is still quiet.
_STREAMS = frozenset({"EventSource"})

_NOT_SETTLED = "The page did not settle."
_MOVED_ON = "The page changed since this decision."
_NOT_FOCUSED = "The field did not take focus when clicked; nothing was typed."
_SESSION_CALL = "the page's CDP session"

_T = TypeVar("_T")

ActionKind = Literal["click", "fill", "secret", "select", "scroll", "wait", "enter", "back"]


class StalePage(BrowserAutomationError):
    """The decision no longer refers to the observed page; nothing was executed."""


class DocumentReplaced(StalePage):
    """The document went away under a call (a navigation committed): nothing ran in the next one."""


class Covered(StalePage):
    """No press at any of the target's boxes reaches it: hidden, disabled, off-screen or covered."""


class FieldUnfocused(BrowserAutomationError):
    """A field was clicked but did not take focus, so nothing was typed into it."""


class PageLoading(BrowserAutomationError):
    """The document was still parsing (a script it loads had not arrived) when the wait for it ended."""


class PageUnresponsive(BrowserAutomationError):
    """A CDP call got no answer in time; whether an input it carried took effect is unknown."""


class TabUnavailable(BrowserAutomationError):
    """The browser refused a call on the tab or no longer has it (closed, crashed, focus lost)."""


class PageScriptError(BrowserAutomationError):
    """One of Jev's own scripts threw in a document that stayed: a real script error, not a navigation."""


class EngineScriptError(PageScriptError):
    """One of Jev's own scripts called a feature this browser engine does not have."""


#: What our scripts throw where the engine lacks a DOM feature they call (a missing
#: method is a TypeError, a missing global a ReferenceError), whatever the page is.
_ENGINE_GAP_ERRORS = frozenset({"TypeError", "ReferenceError"})


class NavigationFailed(BrowserAutomationError):
    """The page could not be opened: the site failed, or never answered and its load was stopped."""


class Rect(TypedDict):
    x: float
    y: float
    w: float
    h: float


class SelectOption(TypedDict):
    """A choice a dropdown offers that it does not already hold."""

    value: str
    label: str


class PageAction(TypedDict):
    """One executable target from the snapshot; ids are code-owned, never model-written."""

    id: str
    kind: ActionKind
    label: str
    node: NotRequired[int]
    role: NotRequired[str]
    ident: NotRequired[str]
    #: An <input>'s type attribute, which says what format its value takes.
    input_type: NotRequired[str]
    #: A field's placeholder and pattern attributes: the format the page asks a typed value in.
    placeholder: NotRequired[str]
    pattern: NotRequired[str]
    value: NotRequired[str]
    current_value: NotRequired[str]
    checked: NotRequired[str]
    selected: NotRequired[str]
    expanded: NotRequired[str]
    filled: NotRequired[bool]
    href: NotRequired[str]
    delta: NotRequired[int]
    rect: NotRequired[Rect]
    #: A dropdown's choices; the action that picks one carries its value instead.
    options: NotRequired[list[SelectOption]]
    #: The tab's history entry GO_BACK returns to.
    entry: NotRequired[int]


class Frame(TypedDict):
    src: str
    same_origin: bool
    visible: bool


class _Point(TypedDict):
    x: float
    y: float


@final
class _Parsing(TypedDict):
    """A document still parsing: it has no body to read yet."""

    loading: Literal[True]
    url: str


@final
class _Snapshot(TypedDict):
    url: str
    title: str
    text: str
    text_cut: bool
    actions: list[PageAction]
    page_key: object
    guards: dict[str, object]
    omitted_actions: int
    frames: list[Frame]


@dataclass(frozen=True)
class PageState:
    """One atomic observation of the focused tab."""

    url: str
    title: str
    text: str
    #: Whether text was cut at the snapshot's budget, possibly inside a word.
    text_cut: bool
    actions: list[PageAction]
    page_key: object
    guards: dict[str, object]
    frames: list[Frame]
    fingerprint: str
    #: Controls the snapshot found beyond its budget and left out.
    omitted_actions: int = 0


def controls(actions: list[PageAction]) -> list[PageAction]:
    """Return actions as they mean, without where they sit: what changes when the page does."""
    return [cast("PageAction", {k: v for k, v in a.items() if k != "rect"}) for a in actions]


def _fingerprint(snapshot: _Snapshot) -> str:
    """Hash what a person sees change: the document, scroll and fields, the controls and the text.

    A control's position is left out: an animation or a layout shift moves it without changing it.
    """
    content = [snapshot["page_key"], controls(snapshot["actions"]), snapshot["text"]]
    return hashlib.sha256(json.dumps(content).encode()).hexdigest()


def _key_events(char: str) -> tuple[DispatchKeyEventParameters, DispatchKeyEventParameters]:
    """Return the key down and up a US keyboard sends for one typed character."""
    down: DispatchKeyEventParameters = {"type": "keyDown", "key": char, "text": char}
    up: DispatchKeyEventParameters = {"type": "keyUp", "key": char}
    if char.isascii() and (char.isalpha() or char.isdigit() or char == " "):
        code = (
            "Space" if char == " " else f"Key{char.upper()}" if char.isalpha() else f"Digit{char}"
        )
        for params in (down, up):
            params["code"] = code
            params["windowsVirtualKeyCode"] = ord(char.upper())
            if char.isupper():
                params["modifiers"] = _SHIFT
    return down, up


def _refused(exc: RuntimeError) -> bool:
    """Whether exc is the browser's own answer refusing a call: cdp_use raises it with the error object."""
    return bool(exc.args) and isinstance(exc.args[0], dict)


async def _bounded(call: Awaitable[_T], what: str) -> _T:
    """Await one CDP call: PageUnresponsive when it gets no answer in time, TabUnavailable when refused."""
    try:
        return await asyncio.wait_for(call, timeout=JEV_CDP_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        log.warning(f"{LogTag.BROWSER} Jev CDP call got no answer", call=what)
        raise PageUnresponsive(f"{what} got no answer in {JEV_CDP_TIMEOUT_SECONDS:.0f}s") from exc
    except RuntimeError as exc:
        if not _refused(exc):
            raise
        raise TabUnavailable(f"{what} was refused: {exc.args[0]}") from exc


class _Requests:
    """The requests one tab started since an input and has not finished, as CDP reports them."""

    def __init__(self, session_id: str, frame_id: str) -> None:
        self._session = session_id
        #: The tab's main frame, whose new document ends every load of the one before.
        self._frame = frame_id
        self._open: set[str] = set()
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def pending(self) -> bool:
        return bool(self._open)

    def started(self, event: RequestWillBeSentEvent, session_id: str | None) -> None:
        if session_id != self._session or event.get("type") in _STREAMS:
            return
        if event.get("type") == "Document" and event.get("frameId") == self._frame:
            # A new top document: the old one's loads end with it, reported or not, and its
            # own start only after its response.
            self._open = set()
        self._open.add(event["requestId"])
        self._idle.clear()

    def ended(
        self, event: LoadingFinishedEvent | LoadingFailedEvent, session_id: str | None
    ) -> None:
        if session_id == self._session:
            self._open.discard(event["requestId"])
            if not self._open:
                self._idle.set()

    async def idle(self) -> None:
        await self._idle.wait()


class JevPage:
    """The focused tab of one Browser-Use session, as Jev observes and drives it."""

    def __init__(self, browser: BrowserSession) -> None:
        self._browser = browser
        #: The last input, whose effect the next observation waits for.
        self._after_input: PageAction | None = None
        #: Page sessions already told to render as if focused and to report their page's events.
        self._focused: set[str] = set()
        #: Page session -> the read waiting for its document to finish parsing.
        self._parsing: dict[str, asyncio.Event] = {}
        #: (opener, target) for every tab the browser opened while listening.
        self._opened: list[tuple[str, str]] = []
        #: The tab the last click was on, and how many tabs had opened before it.
        self._click_mark: tuple[str, int] | None = None

    async def _session(self) -> CDPSession:
        try:
            session = await _bounded(self._browser.get_or_create_cdp_session(), _SESSION_CALL)
        except ValueError as exc:
            # Browser-Use's own word that the tab it focused is gone (a popup that closed).
            raise TabUnavailable(str(exc)) from exc
        # Again on every call: a reconnect brings a new client, and registering replaces a handler.
        self._listen(session.cdp_client)
        if session.session_id not in self._focused:
            # A tab behind another (a page that opened a window, a tab the run left)
            # stops producing frames, so requestAnimationFrame never fires and reads
            # that wait for a frame hang. jev-ultrafast keeps its tab focused the same way.
            await _bounded(
                session.cdp_client.send.Emulation.setFocusEmulationEnabled(
                    params={"enabled": True}, session_id=session.session_id
                ),
                "Emulation.setFocusEmulationEnabled",
            )
            # The page's events (DOMContentLoaded) reach this connection only once enabled.
            await _bounded(
                session.cdp_client.send.Page.enable(session_id=session.session_id), "Page.enable"
            )
            self._focused.add(session.session_id)
        return session

    def _listen(self, client: CDPClient) -> None:
        """Hear which tab opened which, and each tab's document finishing its parse, on this connection."""
        client.register.Target.targetCreated(self._on_target_created)
        client.register.Page.domContentEventFired(self._on_parsed)

    def _on_parsed(self, event: DomContentEventFiredEvent, session_id: str | None) -> None:
        del event
        waiting = self._parsing.get(session_id) if session_id is not None else None
        if waiting is not None:
            waiting.set()

    def _on_target_created(self, event: TargetCreatedEvent, session_id: str | None) -> None:
        del session_id
        info: TargetInfo = event["targetInfo"]
        opener = info.get("openerId")
        if info["type"] == "page" and opener:
            self._opened.append((opener, info["targetId"]))

    async def _evaluate(self, expression: str) -> object:
        """Return what expression evaluates to in the page, a promise awaited.

        Every script of Jev's returns a value, so an undefined result, or a call the
        browser cut off while the tab still answers, is the document going away under
        it (DocumentReplaced); PageScriptError is a script that threw in the document,
        EngineScriptError one that threw because the engine lacks what it called.
        """
        session = await self._session()
        try:
            response: EvaluateReturns = await self._run(session, expression)
        except TabUnavailable:
            # Refused by a navigation that committed mid-call, or by a tab that is gone:
            # only a tab that answers the next call is still there.
            await self._run(session, "0")
            raise DocumentReplaced from None
        details: ExceptionDetails | None = response.get("exceptionDetails")
        if details is not None:
            exception: RemoteObject | None = details.get("exception")
            thrown = (exception.get("description") if exception else None) or details["text"]
            if exception is not None and exception.get("className") in _ENGINE_GAP_ERRORS:
                raise EngineScriptError(f"Jev's page script failed: {thrown}")
            raise PageScriptError(f"Jev's page script failed: {thrown}")
        result: RemoteObject = response["result"]
        if result["type"] == "undefined":
            raise DocumentReplaced
        return result.get("value")

    async def _run(self, session: CDPSession, expression: str) -> EvaluateReturns:
        return await _bounded(
            session.cdp_client.send.Runtime.evaluate(
                params={"expression": expression, "returnByValue": True, "awaitPromise": True},
                session_id=session.session_id,
            ),
            "Runtime.evaluate",
        )

    def _watch(self, session: CDPSession) -> None:
        """Count the requests the tab starts from this input on: the new count replaces the last one's."""
        # Chrome gives a tab's main frame its target's id.
        self._requests = _Requests(session.session_id, session.target_id)
        # Obscura reports a page's requests only once its navigation is done, never as they
        # finish, so there the read after an input waits on the DOM alone.
        if not on_obscura():
            client = session.cdp_client
            client.register.Network.requestWillBeSent(self._requests.started)
            client.register.Network.loadingFinished(self._requests.ended)
            client.register.Network.loadingFailed(self._requests.ended)

    async def _settle(self, action: PageAction) -> None:
        """Wait for what the last input set off: its requests done and the DOM quiet for a frame after.

        A document the input replaced is settled in turn, as Chrome holds the call
        until it commits. Capped, since a page that animates or polls is never quiet.
        """
        try:
            async with asyncio.timeout(JEV_SETTLE_MAX_SECONDS):
                await self._until_quiet(action)
        except TimeoutError:
            # The cap: the page animates or polls, and is read as it stands.
            return

    async def _until_quiet(self, action: PageAction) -> None:
        if action["kind"] == "wait":
            # A navigation ends the wait as any other change would.
            with contextlib.suppress(DocumentReplaced):
                await self._evaluate(_WAIT.call(JEV_WAIT_SECONDS))
        while True:
            try:
                # True: a quiet frame; False: the page's own cap came first.
                quiet = await self._evaluate(_SETTLE.call(JEV_SETTLE_MAX_SECONDS))
            except DocumentReplaced:
                # A navigation committed: settle the document it brought in turn.
                continue
            if not quiet or not self._requests.pending:
                return
            await self._requests.idle()

    async def observe(self) -> PageState:
        """Read the page once the last input has settled; read again while a navigation replaces it.

        A document still parsing is read again once the tab reports DOMContentLoaded;
        PageLoading when it has not within JEV_PARSE_WAIT_SECONDS.
        """
        if self._after_input is not None:
            action, self._after_input = self._after_input, None
            await self._settle(action)
        parse_deadline = asyncio.get_running_loop().time() + JEV_PARSE_WAIT_SECONDS
        for _ in range(JEV_OBSERVE_ATTEMPTS):
            session = await self._session()
            # Set before the read: DOMContentLoaded fired after the read saw "loading" lands here.
            parsed = self._parsing[session.session_id] = asyncio.Event()
            try:
                snapshot: _Snapshot | _Parsing = cast(
                    "_Snapshot | _Parsing", await self._evaluate(_SNAPSHOT_JS)
                )
            except DocumentReplaced:
                # The next read waits for the new document: Chrome holds it until that commits.
                continue
            if "loading" not in snapshot:
                return await self._state(snapshot)
            try:
                async with asyncio.timeout_at(parse_deadline):
                    await parsed.wait()
            except TimeoutError:
                raise PageLoading(f"The page is still loading: {snapshot['url']}") from None
        raise StalePage(_NOT_SETTLED)

    async def _state(self, snapshot: _Snapshot) -> PageState:
        actions = snapshot["actions"]
        back = await self._previous_entry()
        if back is not None:
            actions = [*actions, back]
        return PageState(
            url=snapshot["url"],
            title=snapshot["title"],
            text=snapshot["text"],
            text_cut=snapshot["text_cut"],
            actions=actions,
            page_key=snapshot["page_key"],
            guards=snapshot["guards"],
            frames=snapshot["frames"],
            fingerprint=_fingerprint(snapshot),
            omitted_actions=snapshot["omitted_actions"],
        )

    async def _previous_entry(self) -> PageAction | None:
        """Return going back as an action when the tab's history has a page before this one."""
        session = await self._session()
        history: GetNavigationHistoryReturns = await _bounded(
            session.cdp_client.send.Page.getNavigationHistory(session_id=session.session_id),
            "Page.getNavigationHistory",
        )
        index = history["currentIndex"]
        if index <= 0:
            return None
        previous: NavigationEntry = history["entries"][index - 1]
        title = previous["title"] or previous["url"]
        return PageAction(
            id="go_back", kind="back", label=f"Go back to {title}", entry=previous["id"]
        )

    async def fresh(self, page: PageState, action: PageAction | None = None) -> bool:
        """Whether a decision made on page still holds.

        Every decision checks the page key (document, address, scroll, viewport,
        form state) and an element decision its own target's guard too; visible
        text elsewhere (a clock, a countdown) invalidates neither. Nothing holds
        on a document replaced while it was checked.
        """
        node = action.get("node") if action is not None else None
        try:
            current = await self._evaluate(_GUARD.call(node))
        except DocumentReplaced:
            return False
        return current == [page.page_key, None if node is None else page.guards.get(str(node))]

    async def act(self, action: PageAction, page: PageState, text: str | None = None) -> str | None:
        """Execute one observed action; raises before any input when the page moved on.

        Returns what a field holds once text was put into it, None for every other action.
        """
        if not await self.fresh(page, action):
            raise StalePage(_MOVED_ON)
        session = await self._session()
        self._watch(session)
        if action["kind"] in ("wait", "back") or (
            action["kind"] == "scroll" and "node" not in action
        ):
            await self._on_page(session, action)
            return None
        if text is not None and action.get("input_type") in _SET_IN_PAGE:
            return await self._set(action, text)
        target = await self._evaluate(_ACT.call(action))
        if target is None:
            raise Covered
        self._after_input = action
        return await self._on_target(session, action, target, text)

    async def _on_page(self, session: CDPSession, action: PageAction) -> None:
        """Act on the page as a whole: wait for it, go back in its history, or scroll it."""
        self._after_input = action
        if action["kind"] == "back":
            await _bounded(
                session.cdp_client.send.Page.navigateToHistoryEntry(
                    params={"entryId": action["entry"]}, session_id=session.session_id
                ),
                "Page.navigateToHistoryEntry",
            )
        elif action["kind"] == "scroll":
            await self._mouse(session, self._wheel(action, None))

    async def _set(self, action: PageAction, text: str) -> str:
        """Set a field whose value is a format in the page; return what it holds after."""
        held = await self._evaluate(_SET.call({"node": action["node"], "text": text}))
        if held is None:
            raise Covered
        self._after_input = action
        return str(held)

    async def _on_target(
        self, session: CDPSession, action: PageAction, target: object, text: str | None
    ) -> str | None:
        """Send the input a reachable target takes: none for a set dropdown, Enter, the wheel, or a press."""
        kind = action["kind"]
        if kind == "select":
            return None
        if kind == "enter":
            await self._keys(session, _ENTER)
            return None
        point: _Point = cast("_Point", target)
        if kind == "scroll":
            await self._mouse(session, self._wheel(action, point))
            return None
        await self._press(session, point)
        return None if text is None else await self._fill(session, action, text)

    async def _press(self, session: CDPSession, point: _Point) -> None:
        self._click_mark = (session.target_id, len(self._opened))
        for event in ("mousePressed", "mouseReleased"):
            await self._mouse(
                session,
                {
                    "type": event,
                    "x": point["x"],
                    "y": point["y"],
                    "button": "left",
                    "clickCount": 1,
                },
            )

    async def _fill(self, session: CDPSession, action: PageAction, text: str) -> str | None:
        """Type text into the field the press focused; return what it holds after, None once the page went on."""
        try:
            focused = await self._evaluate(_FOCUSED.call(action["node"]))
        except DocumentReplaced:
            focused = False
        if not focused:
            raise FieldUnfocused(_NOT_FOCUSED)
        await self._type(session, text)
        try:
            return str(await self._evaluate(_VALUE.call(action["node"])))
        except DocumentReplaced:
            # What was typed submitted the page (a line break pressed Enter): nothing left to read.
            return None

    def _wheel(self, action: PageAction, point: _Point | None) -> DispatchMouseEventParameters:
        """Turn the wheel inside the container a scroll names, or over the page for the page itself."""
        x, y = (point["x"], point["y"]) if point is not None else (_WHEEL_X, _WHEEL_Y)
        return {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": action["delta"]}

    async def _type(self, session: CDPSession, text: str) -> None:
        """Replace the focused field's text, one key event per character as a person types.

        Input.insertText fires no key events, and a field that listens for keys
        (an autocomplete, a masked input) then misses the value.
        """
        await self._keys(session, _SELECT_ALL)
        for char in text:
            await self._keys(session, _ENTER if char == "\n" else _key_events(char))

    async def _keys(
        self, session: CDPSession, events: tuple[DispatchKeyEventParameters, ...]
    ) -> None:
        for params in events:
            await _bounded(
                session.cdp_client.send.Input.dispatchKeyEvent(
                    params=params, session_id=session.session_id
                ),
                "Input.dispatchKeyEvent",
            )

    async def _mouse(self, session: CDPSession, params: DispatchMouseEventParameters) -> None:
        await _bounded(
            session.cdp_client.send.Input.dispatchMouseEvent(
                params=params, session_id=session.session_id
            ),
            "Input.dispatchMouseEvent",
        )

    async def body_text(self, limit: int) -> str:
        """Return the start of the whole page's rendered text, not only what the viewport shows."""
        return str(
            await self._evaluate(
                f"(document.body ? document.body.innerText : '').slice(0, {limit})"
            )
        )

    async def navigate(self, url: str) -> None:
        """Open url in the tab; NavigationFailed when the browser could not load it."""
        try:
            await self._browser.navigate_to(url)
        except RuntimeError as exc:
            if _refused(exc):
                raise TabUnavailable(f"Opening {url} was refused: {exc.args[0]}") from exc
            # Browser-Use's own report of a navigation the page failed: its error text, or no answer.
            raise NavigationFailed(str(exc)) from exc

    async def follow_new_tab(self) -> bool:
        """Focus the tab the last click opened, as a person would; True when it opened one."""
        if self._click_mark is None:
            return False
        acting, seen = self._click_mark
        self._click_mark = None
        opened = [target for opener, target in self._opened[seen:] if opener == acting]
        if not opened:
            return False
        event = self._browser.event_bus.dispatch(SwitchTabEvent(target_id=opened[-1]))
        await event
        return True

    async def screenshot(self) -> str:
        """Return the focused tab as a base64 JPEG, for the step card."""
        session = await self._session()
        result: CaptureScreenshotReturns = await _bounded(
            session.cdp_client.send.Page.captureScreenshot(
                params={"format": "jpeg", "quality": BROWSER_STEP_PHOTO_QUALITY},
                session_id=session.session_id,
            ),
            "Page.captureScreenshot",
        )
        return result["data"]
