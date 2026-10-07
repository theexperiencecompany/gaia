# Where Obscura's CDP and Chromium's disagree, measured 2026-09-19. Each test
# asserts what the live engine does TODAY, so a release that fixes or breaks one
# turns red, and names the Browser-Use 0.11.13 call site it matters to.

# Driven over raw CDP against the host, not through Browser-Use, so a
# Browser-Use upgrade cannot mask an engine change.

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import contextlib
import json
import os
import time
from typing import Any

import httpx
import pytest
import websockets

_HOST = os.environ.get("BROWSER_HOST_URL", "http://localhost:8930")
_WIKI = "https://en.wikipedia.org/wiki/Main_Page"
_FORM = "https://www.selenium.dev/selenium/web/web-form.html"
_TEXT_FIELD = "input[name=my-text]"
_SELECT = "select[name=my-select]"
# A laid-out element on the wiki page: its <h1> is display:none, so its
# geometry is legitimately all zeros and would prove nothing.
_VISIBLE = "#p-search"
# CDP's method-not-implemented code; Obscura answers every unimplemented method with it.
_UNKNOWN_METHOD = -32601
# Our proxy's refusal code (app/browser_host/proxy.py).
_REFUSED = -32000
# A command that returns at once, not one that waited for a page load (a
# navigation measured 2-4 s on these pages).
_PROMPT_SECONDS = 0.5


def _host_answers() -> bool:
    if os.environ.get("USE_REAL_SERVICES") != "1":
        return False
    try:
        body: dict[str, Any] = httpx.get(f"{_HOST}/healthz", timeout=3).json()
    except (httpx.HTTPError, ValueError):
        return False
    return bool(body.get("ok") and body.get("cdp_responsive"))


pytestmark = [
    pytest.mark.service,
    pytest.mark.skipif(
        not _host_answers(), reason="requires USE_REAL_SERVICES=1 and a live browser host"
    ),
]


class Cdp:
    def __init__(self, websocket: websockets.ClientConnection) -> None:
        self._ws = websocket
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.events: list[dict[str, Any]] = []
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                frame: dict[str, Any] = json.loads(raw)
                waiter = self._pending.pop(frame.get("id", -1), None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(frame)
                elif waiter is None:
                    self.events.append(frame)
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float = 60.0,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, float]:
        self._next_id += 1
        message_id = self._next_id
        message: dict[str, Any] = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        waiter: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[message_id] = waiter
        started = time.perf_counter()
        await self._ws.send(json.dumps(message))
        frame = await asyncio.wait_for(waiter, timeout)
        elapsed = time.perf_counter() - started
        return frame.get("result"), frame.get("error"), elapsed

    async def ok(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        result, error, _ = await self.call(method, params, session_id, timeout)
        assert error is None, f"{method} failed: {error}"
        assert result is not None
        return result

    async def close(self) -> None:
        self._reader.cancel()
        await self._ws.close()


Evaluate = Callable[[str], Any]


def _create_session() -> tuple[str, str]:
    body: dict[str, Any] = httpx.post(
        f"{_HOST}/sessions", json={"storage_state": None}, timeout=60
    ).json()
    return body["session_id"], body["cdp_ws"]


def _delete_session(session_id: str) -> None:
    # A leaked session is reaped by the host; failing teardown would hide the real result.
    with contextlib.suppress(httpx.HTTPError):
        httpx.delete(f"{_HOST}/sessions/{session_id}", timeout=30)


# Function-scoped on purpose: one context and one tab per test, so a test that
# leaves the page navigated, scrolled or emulated cannot reach the next one.
@pytest.fixture
async def page() -> AsyncIterator[tuple[Cdp, str]]:
    host_session_id, cdp_ws = _create_session()
    client = Cdp(await websockets.connect(cdp_ws, max_size=None, ping_interval=None))
    created = await client.ok("Target.createTarget", {"url": "about:blank"})
    attached = await client.ok(
        "Target.attachToTarget", {"targetId": created["targetId"], "flatten": True}
    )
    session_id: str = attached["sessionId"]
    await client.ok("Page.enable", {}, session_id)
    await client.ok("DOM.enable", {}, session_id)
    try:
        yield client, session_id
    finally:
        await client.close()
        _delete_session(host_session_id)


@pytest.fixture
async def at_wiki(page: tuple[Cdp, str]) -> tuple[Cdp, str, Evaluate]:
    return await _open(page, _WIKI)


@pytest.fixture
async def at_form(page: tuple[Cdp, str]) -> tuple[Cdp, str, Evaluate]:
    return await _open(page, _FORM)


async def _open(page: tuple[Cdp, str], url: str) -> tuple[Cdp, str, Evaluate]:
    client, session_id = page
    await client.ok("Page.navigate", {"url": url}, session_id)
    await asyncio.sleep(3)

    async def evaluate(expression: str) -> Any:
        result = await client.ok(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id,
        )
        assert "exceptionDetails" not in result, f"page script threw: {result['exceptionDetails']}"
        return (result.get("result") or {}).get("value")

    return client, session_id, evaluate


async def _backend_node_id(client: Cdp, session_id: str, selector: str) -> int:
    document = await client.ok("DOM.getDocument", {"depth": -1}, session_id)
    found = await client.ok(
        "DOM.querySelector",
        {"nodeId": document["root"]["nodeId"], "selector": selector},
        session_id,
    )
    described = await client.ok("DOM.describeNode", {"nodeId": found["nodeId"]}, session_id)
    node_id: int = described["node"]["backendNodeId"]
    return node_id


async def _object_id(client: Cdp, session_id: str, selector: str) -> str:
    resolved = await client.ok(
        "DOM.resolveNode",
        {"backendNodeId": await _backend_node_id(client, session_id, selector)},
        session_id,
    )
    object_id: str = resolved["object"]["objectId"]
    return object_id


async def _press(client: Cdp, session_id: str, x: float, y: float) -> float:
    slowest = 0.0
    for event_type, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
        _, error, elapsed = await client.call(
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
                "buttons": buttons,
            },
            session_id,
        )
        assert error is None
        slowest = max(slowest, elapsed)
    return slowest


async def _type(client: Cdp, session_id: str, key: str, code: str, key_code: int) -> None:
    for event_type in ("keyDown", "keyUp"):
        params: dict[str, Any] = {
            "type": event_type,
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": key_code,
        }
        if event_type == "keyDown" and len(key) == 1:
            params["text"] = key
        _, error, _ = await client.call("Input.dispatchKeyEvent", params, session_id)
        assert error is None


# --- geometry: what Browser-Use's element table is built from ----------------


async def test_dom_snapshot_bounds_are_a_fabricated_ladder(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # dom/service.py:521 builds every node's absolute_position from these bounds.
    client, session_id, evaluate = at_wiki
    snapshot = await client.ok(
        "DOMSnapshot.captureSnapshot",
        {"computedStyles": [], "includeDOMRects": True, "includePaintOrder": True},
        session_id,
    )
    document = snapshot["documents"][0]
    strings, nodes, layout = snapshot["strings"], document["nodes"], document["layout"]
    headings = [
        index
        for index, layout_index in enumerate(layout["nodeIndex"])
        if strings[nodes["nodeName"][layout_index]] == "A"
    ]
    assert headings, "the snapshot carried no anchors to measure"
    boxes = [layout["bounds"][index] for index in headings[:20]]
    viewport_width = await evaluate("innerWidth")

    # Every box is the full page width and a uniform 18px tall, marching down a
    # phantom document -- no real anchor on this page is 1280px wide.
    assert all(box[0] == 0 for box in boxes)
    assert {box[2] for box in boxes} == {float(viewport_width)}
    assert {box[3] for box in boxes} == {18.0}
    assert max(box[1] for box in boxes) > await evaluate("innerHeight")


async def test_dom_get_content_quads_agrees_with_the_page(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # browser/session.py:2607 -- get_element_coordinates, the honest geometry
    # path, and the one this engine's snapshot bounds are not.
    client, session_id, evaluate = at_wiki
    quads = await client.ok(
        "DOM.getContentQuads",
        {"backendNodeId": await _backend_node_id(client, session_id, _VISIBLE)},
        session_id,
    )
    truth = json.loads(
        await evaluate(
            "JSON.stringify((r => [r.left, r.top, r.width, r.height])"
            f"(document.querySelector('{_VISIBLE}').getBoundingClientRect()))"
        )
    )
    quad = quads["quads"][0]

    assert truth[2] > 0 and truth[3] > 0, "the probe element is not laid out"
    assert quad[0] == pytest.approx(truth[0], abs=2)
    assert quad[1] == pytest.approx(truth[1], abs=2)
    assert quad[2] - quad[0] == pytest.approx(truth[2], abs=2)
    assert quad[5] - quad[1] == pytest.approx(truth[3], abs=2)


async def test_a_resolved_node_handle_drives_the_live_element(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # browser/session.py:2647 -- every caller that reaches an element resolves
    # then calls on it. The handle is the node itself (a wrapper before Obscura
    # 8f9c630), and writes through it reach the real element.
    client, session_id, evaluate = at_wiki
    object_id = await _object_id(client, session_id, _VISIBLE)
    identity = await client.ok(
        "Runtime.callFunctionOn",
        {
            "functionDeclaration": (
                f"function(){{return this === document.querySelector('{_VISIBLE}');}}"
            ),
            "objectId": object_id,
            "returnByValue": True,
        },
        session_id,
    )
    await client.ok(
        "Runtime.callFunctionOn",
        {
            "functionDeclaration": "function(){this.setAttribute('data-probe', 'xyz');}",
            "objectId": object_id,
            "returnByValue": True,
        },
        session_id,
    )

    assert identity["result"]["value"] is True
    assert (
        await evaluate(f"document.querySelector('{_VISIBLE}').getAttribute('data-probe')") == "xyz"
    )


async def test_describe_node_reports_no_parent(at_wiki: tuple[Cdp, str, Evaluate]) -> None:
    # dom/service.py:493 builds each node's xpath by walking parent_node; with no
    # parent the xpath collapses to a bare tag name (Jev reads the live document instead).
    client, session_id, _ = at_wiki
    document = await client.ok("DOM.getDocument", {"depth": -1}, session_id)
    found = await client.ok(
        "DOM.querySelector",
        {"nodeId": document["root"]["nodeId"], "selector": _VISIBLE},
        session_id,
    )
    described = await client.ok("DOM.describeNode", {"nodeId": found["nodeId"]}, session_id)

    assert described["node"]["nodeName"] == "DIV"
    assert described["node"].get("parentId") is None


@pytest.mark.parametrize(
    ("method", "params", "call_site"),
    [
        ("DOM.getAttributes", {"nodeId": 1}, "actor/element.py:645"),
        ("DOM.requestChildNodes", {"nodeId": 1, "depth": 1}, "actor/element.py:549 select_option"),
        (
            "DOM.pushNodesByBackendIdsToFrontend",
            {"backendNodeIds": [1]},
            "actor/element.py:79",
        ),
        (
            "DOM.getSearchResults",
            {"searchId": "1", "fromIndex": 0, "toIndex": 1},
            "default_action_watchdog.py:2648",
        ),
        ("DOM.discardSearchResults", {"searchId": "1"}, "default_action_watchdog.py:2664"),
    ],
    ids=["getAttributes", "requestChildNodes", "pushNodes", "getSearchResults", "discardSearch"],
)
async def test_the_dom_method_is_not_implemented(
    at_wiki: tuple[Cdp, str, Evaluate],
    method: str,
    params: dict[str, Any],
    call_site: str,
) -> None:
    client, session_id, _ = at_wiki
    _, error, _ = await client.call(method, params, session_id)

    assert error is not None, f"{method} now works; {call_site} can stop working around it"
    assert error["code"] == _UNKNOWN_METHOD


# --- input --------------------------------------------------------------------


async def test_a_synthesized_scroll_gesture_scrolls_the_page(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:_scroll_with_cdp_gesture -- Browser-Use's page
    # scroll. Engine patch 0037 maps the gesture onto the wheel path.
    client, session_id, evaluate = at_wiki
    await evaluate("window.scrollTo(0, 0)")
    _, error, _ = await client.call(
        "Input.synthesizeScrollGesture", {"x": 400, "y": 400, "yDistance": -400}, session_id
    )

    assert error is None
    assert await evaluate("window.scrollY") == 400


async def test_a_dispatched_click_reaches_the_element_the_page_names(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # actor/element.py:1023 -- Browser-Use's own click; the events are real and
    # trusted, and land where document.elementFromPoint says they do.
    client, session_id, evaluate = at_wiki
    await evaluate(
        "window.__hits = [];"
        "document.addEventListener('mousedown', e => window.__hits.push("
        "  {tag: e.target.tagName, x: e.clientX, y: e.clientY, trusted: e.isTrusted,"
        "   agrees: e.target === document.elementFromPoint(e.clientX, e.clientY)}), true);"
        "document.addEventListener('click', e => e.preventDefault(), true);"
    )
    await _press(client, session_id, 400, 300)
    hits = json.loads(await evaluate("JSON.stringify(window.__hits)"))

    assert len(hits) == 1
    assert hits[0]["x"] == 400
    assert hits[0]["y"] == 300
    assert hits[0]["trusted"] is True
    assert hits[0]["agrees"] is True


async def test_a_press_focuses_the_field_it_lands_on(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:_click_element_node_impl presses at the
    # element's centre and then types; the press must give the field focus.
    client, session_id, evaluate = at_form
    point = json.loads(
        await evaluate(
            "JSON.stringify((r => [r.left + r.width / 2, r.top + r.height / 2])"
            f"(document.querySelector('{_TEXT_FIELD}').getBoundingClientRect()))"
        )
    )
    await _press(client, session_id, point[0], point[1])

    assert await evaluate("document.activeElement.name") == "my-text"


async def test_typing_reaches_the_focused_field_with_trusted_events(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # actor/element.py:427 and default_action_watchdog.py:2371 (send_keys).
    client, session_id, evaluate = at_form
    await evaluate(
        f"const f = document.querySelector('{_TEXT_FIELD}'); f.focus(); f.value = '';"
        "window.__keys = [];"
        "f.addEventListener('keydown', e => window.__keys.push([e.key, e.isTrusted]));"
    )
    await _type(client, session_id, "h", "KeyH", 72)
    await _type(client, session_id, "i", "KeyI", 73)

    assert await evaluate(f"document.querySelector('{_TEXT_FIELD}').value") == "hi"
    assert json.loads(await evaluate("JSON.stringify(window.__keys)")) == [["h", True], ["i", True]]


async def test_the_dom_snapshot_reports_what_a_field_holds_now(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # Engine patch 0019. No GAIA code reads these columns now (Jev reads the live
    # document); this keeps the patch honest for any CDP client that does.
    client, session_id, evaluate = at_form
    await evaluate(f"document.querySelector('{_TEXT_FIELD}').focus()")
    await _type(client, session_id, "h", "KeyH", 72)
    await _type(client, session_id, "i", "KeyI", 73)
    await evaluate("document.querySelector('input[name=my-check]:not([checked])').click()")
    field = await _backend_node_id(client, session_id, _TEXT_FIELD)
    ticked = await _backend_node_id(client, session_id, "#my-check-2")

    snapshot = await client.ok("DOMSnapshot.captureSnapshot", {"computedStyles": []}, session_id)
    nodes, strings = snapshot["documents"][0]["nodes"], snapshot["strings"]
    backend_ids = nodes["backendNodeId"]
    values = {
        backend_ids[row]: strings[string]
        for row, string in zip(
            nodes["inputValue"]["index"], nodes["inputValue"]["value"], strict=True
        )
    }
    checked = {backend_ids[row] for row in nodes["inputChecked"]["index"]}

    assert values[field] == "hi"
    assert ticked in checked


async def test_enter_submits_the_form_the_field_belongs_to(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:2371 -- send_keys('Enter'), Jev's submit.
    client, session_id, evaluate = at_form
    await evaluate(
        "window.__submitted = false;"
        "document.querySelector('form').addEventListener('submit',"
        "  e => { e.preventDefault(); window.__submitted = true; });"
        f"document.querySelector('{_TEXT_FIELD}').focus();"
    )
    await _type(client, session_id, "Enter", "Enter", 13)

    assert await evaluate("window.__submitted") is True


async def test_tab_does_not_move_focus(at_form: tuple[Cdp, str, Evaluate]) -> None:
    # default_action_watchdog.py:2371 -- send_keys('Tab') is inert here, unlike
    # Chromium, where it advances to the next focusable element.
    client, session_id, evaluate = at_form
    await evaluate(f"document.querySelector('{_TEXT_FIELD}').focus()")
    before = await evaluate("document.activeElement.name")
    await _type(client, session_id, "Tab", "Tab", 9)

    assert await evaluate("document.activeElement.name") == before


async def test_ctrl_a_selects_nothing_while_the_select_api_does(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:2371 builds Control+A from dispatchKeyEvent and
    # gets no selection. Clearing (default_action_watchdog.py:1265) assigns value
    # in JavaScript and calls select(), which does work, so clearing is safe.
    client, session_id, evaluate = at_form
    await evaluate(
        f"const f = document.querySelector('{_TEXT_FIELD}'); f.focus(); f.value = 'abcdef';"
    )
    for event_type, key, code, key_code, modifiers in (
        ("keyDown", "Control", "ControlLeft", 17, 0),
        ("keyDown", "a", "KeyA", 65, 2),
        ("keyUp", "a", "KeyA", 65, 2),
        ("keyUp", "Control", "ControlLeft", 17, 0),
    ):
        _, error, _ = await client.call(
            "Input.dispatchKeyEvent",
            {
                "type": event_type,
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": key_code,
                "modifiers": modifiers,
            },
            session_id,
        )
        assert error is None
    after_ctrl_a = json.loads(
        await evaluate(
            f"const g = document.querySelector('{_TEXT_FIELD}');"
            "JSON.stringify([g.selectionStart, g.selectionEnd])"
        )
    )
    after_select = json.loads(
        await evaluate(
            f"const h = document.querySelector('{_TEXT_FIELD}'); h.select();"
            "JSON.stringify([h.selectionStart, h.selectionEnd])"
        )
    )

    assert after_ctrl_a == [None, None]
    assert after_select == [0, 6]


async def test_insert_text_appends_to_the_focused_field(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # skill_cli/python_session.py:174 -- Input.insertText.
    client, session_id, evaluate = at_form
    await evaluate(f"const f = document.querySelector('{_TEXT_FIELD}'); f.focus(); f.value = '';")
    _, error, _ = await client.call("Input.insertText", {"text": "hello"}, session_id)

    assert error is None
    assert await evaluate(f"document.querySelector('{_TEXT_FIELD}').value") == "hello"


# --- <select>: Jev's SELECT operation -----------------------------------------


async def test_setting_option_selected_selects_it(at_form: tuple[Cdp, str, Evaluate]) -> None:
    # default_action_watchdog.py:3221 writes value, option.selected and
    # selectedIndex in turn; each must move the one selection (engine patch 0034).
    _, _, evaluate = at_form
    state = json.loads(
        await evaluate(
            f"const s = document.querySelector('{_SELECT}'); s.selectedIndex = 0;"
            "s.options[2].selected = true;"
            "JSON.stringify({value: s.value, index: s.selectedIndex,"
            " flags: Array.from(s.options).map(o => o.selected)})"
        )
    )

    assert state == {"value": "2", "index": 2, "flags": [False, False, True, False]}


async def test_assigning_value_selects_the_option(at_form: tuple[Cdp, str, Evaluate]) -> None:
    # The first of the three writes Browser-Use's select handler makes.
    _, _, evaluate = at_form
    state = json.loads(
        await evaluate(
            f"const s = document.querySelector('{_SELECT}'); s.selectedIndex = 0; s.value = '2';"
            "JSON.stringify({value: s.value, index: s.selectedIndex,"
            " text: s.options[s.selectedIndex].text.trim(),"
            " sent: new FormData(document.querySelector('form')).get('my-select')})"
        )
    )

    assert state == {"value": "2", "index": 2, "text": "Two", "sent": "2"}


async def test_browser_uses_select_sequence_keeps_the_option(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:3221-3240, as Browser-Use runs it: focus, then
    # value, option.selected and selectedIndex = option.index, input and change,
    # then a read-back of value that reports a reverted pick when it differs.
    _, _, evaluate = at_form
    state = json.loads(
        await evaluate(
            f"const s = document.querySelector('{_SELECT}'); s.selectedIndex = 0;"
            "const o = Array.from(s.options).find(o => o.text.trim() === 'Three');"
            "s.focus(); s.value = o.value; o.selected = true; s.selectedIndex = o.index;"
            "s.dispatchEvent(new Event('input', {bubbles: true}));"
            "s.dispatchEvent(new Event('change', {bubbles: true}));"
            "JSON.stringify({value: s.value, kept: s.value === o.value,"
            " sent: new FormData(document.querySelector('form')).get('my-select')})"
        )
    )

    assert state == {"value": "3", "kept": True, "sent": "3"}


# --- tabs ----------------------------------------------------------------------


async def test_window_open_without_user_activation_opens_nothing(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # Chrome's popup blocker: a page cannot open a window on its own.
    client, _, evaluate = at_wiki
    before = len((await client.ok("Target.getTargets"))["targetInfos"])
    seen = len(client.events)
    opened = await evaluate("!!window.open('https://en.wikipedia.org/wiki/Dog', '_blank')")
    await asyncio.sleep(1)

    assert opened is False
    assert len((await client.ok("Target.getTargets"))["targetInfos"]) == before
    assert [
        event
        for event in client.events[seen:]
        if str(event.get("method", "")).startswith("Target.targetCreated")
    ] == []


async def test_window_open_from_a_click_opens_a_target(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # popups_watchdog.py:46 and session_manager.py:105 wait for the new target
    # a page opens (engine patch 0036).
    client, session_id, evaluate = at_wiki
    point = json.loads(
        await evaluate(
            "const b = document.createElement('button'); b.textContent = 'open';"
            "b.style.cssText = 'position:fixed;left:10px;top:200px;z-index:2147483647;padding:8px';"
            "b.onclick = () => window.open('https://en.wikipedia.org/wiki/Dog', '_blank');"
            "document.body.appendChild(b);"
            "JSON.stringify((r => [r.left + r.width / 2, r.top + r.height / 2])"
            "(b.getBoundingClientRect()))"
        )
    )
    seen = len(client.events)
    await _press(client, session_id, point[0], point[1])
    await asyncio.sleep(4)
    created = [
        event["params"]["targetInfo"]
        for event in client.events[seen:]
        if event.get("method") == "Target.targetCreated"
    ]

    assert len(created) == 1
    assert created[0]["openerId"]
    try:
        assert await evaluate("location.href") == _WIKI
        targets = (await client.ok("Target.getTargets"))["targetInfos"]
        assert "https://en.wikipedia.org/wiki/Dog" in [target["url"] for target in targets]
    finally:
        await client.call("Target.closeTarget", {"targetId": created[0]["targetId"]})


async def test_an_init_script_runs_immediately_and_on_the_next_document(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # browser/session.py:3294 and the stealth patch both pass runImmediately.
    client, session_id, evaluate = at_wiki
    marker = "window.__init_marker = (window.__init_marker || 0) + 1;"
    await client.ok(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": marker, "runImmediately": True},
        session_id,
    )
    on_the_open_page = await evaluate("window.__init_marker")
    await client.ok("Page.navigate", {"url": _WIKI}, session_id)
    await asyncio.sleep(3)

    assert on_the_open_page == 1
    assert await evaluate("window.__init_marker") == 1


async def test_a_blank_link_opens_a_new_target(at_wiki: tuple[Cdp, str, Evaluate]) -> None:
    # A press on a target=_blank link opens the page in a new tab, as in Chrome.
    client, session_id, evaluate = at_wiki
    before = len((await client.ok("Target.getTargets"))["targetInfos"])
    point = json.loads(
        await evaluate(
            "const a = document.createElement('a');"
            "a.href = 'https://en.wikipedia.org/wiki/Bird'; a.target = '_blank';"
            "a.textContent = 'probe'; a.style.cssText = 'position:fixed;left:10px;top:200px;"
            "z-index:2147483647;background:#fff;padding:8px;font-size:20px';"
            "document.body.appendChild(a);"
            "JSON.stringify((r => [r.left + r.width / 2, r.top + r.height / 2])"
            "(a.getBoundingClientRect()))"
        )
    )
    seen = len(client.events)
    await _press(client, session_id, point[0], point[1])
    await asyncio.sleep(4)
    created = [
        event["params"]["targetInfo"]["targetId"]
        for event in client.events[seen:]
        if event.get("method") == "Target.targetCreated"
    ]

    try:
        assert len((await client.ok("Target.getTargets"))["targetInfos"]) == before + 1
        assert await evaluate("location.href") == _WIKI
    finally:
        for target_id in created:
            await client.call("Target.closeTarget", {"targetId": target_id})


async def test_opening_and_switching_tabs_over_target_works(page: tuple[Cdp, str]) -> None:
    # browser/session.py:1232 (new tab) and 1070 (switch_tab) -- both intact.
    client, _ = page
    before = len((await client.ok("Target.getTargets"))["targetInfos"])
    created = await client.ok("Target.createTarget", {"url": "https://en.wikipedia.org/wiki/Dog"})
    await asyncio.sleep(3)
    attached = await client.ok(
        "Target.attachToTarget", {"targetId": created["targetId"], "flatten": True}
    )
    href = await client.ok(
        "Runtime.evaluate",
        {"expression": "location.href", "returnByValue": True},
        attached["sessionId"],
    )
    _, activate_error, _ = await client.call(
        "Target.activateTarget", {"targetId": created["targetId"]}
    )
    try:
        assert len((await client.ok("Target.getTargets"))["targetInfos"]) == before + 1
        assert href["result"]["value"] == "https://en.wikipedia.org/wiki/Dog"
        assert activate_error is None
    finally:
        await client.call("Target.closeTarget", {"targetId": created["targetId"]})


# --- navigation ----------------------------------------------------------------


async def test_page_navigate_answers_at_commit_and_reports_load_later(
    page: tuple[Cdp, str],
) -> None:
    # session.py:_navigate_and_wait -- Browser-Use bounds Page.navigate at 20s
    # and then waits for a lifecycle event carrying the loaderId it returned.
    # Chrome answers at commit; so does Obscura since engine patch 0030.
    client, session_id = page
    result, error, answered_after = await client.call("Page.navigate", {"url": _WIKI}, session_id)
    assert error is None and result is not None
    loader_id = result["loaderId"]
    lifecycle = [
        event["params"]
        for event in client.events
        if event.get("method") == "Page.lifecycleEvent"
        and event["params"].get("loaderId") == loader_id
    ]
    assert "commit" in [step["name"] for step in lifecycle]

    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        names = [
            event["params"]["name"]
            for event in client.events
            if event.get("method") == "Page.lifecycleEvent"
            and event["params"].get("loaderId") == loader_id
        ]
        if "load" in names:
            break
        await asyncio.sleep(0.1)
    assert "load" in names, f"no load for the navigation's loader after {answered_after:.1f}s"


async def test_going_back_through_the_history_entry_works(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:2284 -- on_GoBackEvent, Jev's go_back.
    client, session_id, evaluate = at_wiki
    await client.ok("Page.navigate", {"url": "https://en.wikipedia.org/wiki/Cat"}, session_id)
    await asyncio.sleep(3)
    history = await client.ok("Page.getNavigationHistory", {}, session_id)
    assert history["currentIndex"] > 0, "Obscura kept no previous entry to go back to"
    previous = history["entries"][history["currentIndex"] - 1]
    await client.ok("Page.navigateToHistoryEntry", {"entryId": previous["id"]}, session_id)
    await asyncio.sleep(3)

    assert await evaluate("location.href") == previous["url"]


# --- methods Browser-Use calls that Obscura does not implement ------------------


@pytest.mark.parametrize(
    ("method", "params", "call_site"),
    [
        ("DOM.performSearch", {"query": "//h1"}, "default_action_watchdog.py:2642 scroll_to_text"),
        ("DOM.getNodeForLocation", {"x": 10, "y": 10}, "browser/session.py:2350"),
        ("DOM.getFrameOwner", {"frameId": "page-1"}, "browser/session.py:3661"),
        ("Page.handleJavaScriptDialog", {"accept": True}, "popups_watchdog.py:91"),
        ("DOMStorage.enable", {}, "browser/session.py:3344 storage state"),
    ],
    ids=["performSearch", "getNodeForLocation", "getFrameOwner", "handleDialog", "domStorage"],
)
async def test_the_method_is_not_implemented(
    at_wiki: tuple[Cdp, str, Evaluate],
    method: str,
    params: dict[str, Any],
    call_site: str,
) -> None:
    client, session_id, _ = at_wiki
    _, error, _ = await client.call(method, params, session_id)

    assert error is not None, f"{method} now works; {call_site} can stop working around it"
    assert error["code"] == _UNKNOWN_METHOD


async def test_setting_a_file_input_is_refused_by_the_engine(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # default_action_watchdog.py:2602 -- on_UploadFileEvent. Not fixable from
    # here: the engine wants `obscura serve --allow-file-access`.
    client, session_id, _ = at_form
    _, error, _ = await client.call(
        "DOM.setFileInputFiles",
        {
            "files": ["/etc/hostname"],
            "backendNodeId": await _backend_node_id(client, session_id, "body"),
        },
        session_id,
    )

    assert error is not None
    assert "allow-file-access" in error["message"]


async def test_an_alert_neither_blocks_the_page_nor_raises_a_dialog_event(
    at_form: tuple[Cdp, str, Evaluate],
) -> None:
    # popups_watchdog.py:126 registers Page.javascriptDialogOpening; nothing
    # fires it, and confirm() answers itself, so no page ever hangs on one.
    client, session_id, evaluate = at_form
    seen = len(client.events)

    assert await evaluate("window.alert('probe'); 'past-the-alert'") == "past-the-alert"
    assert await evaluate("String(window.confirm('ok?'))") == "true"
    assert [
        event for event in client.events[seen:] if event.get("method", "").startswith("Page.java")
    ] == []


# --- what works exactly as Chromium does ---------------------------------------


async def test_the_page_scrolls_in_javascript(at_wiki: tuple[Cdp, str, Evaluate]) -> None:
    # Browser-Use's JavaScript scroll fallback.
    _, _, evaluate = at_wiki
    await evaluate("window.scrollTo(0, 0)")
    await evaluate("window.scrollBy(0, 600)")

    assert await evaluate("window.scrollY") > 0


async def test_an_element_click_in_javascript_follows_the_link(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # Browser-Use's JavaScript click, used when the element is occluded.
    _, _, evaluate = at_wiki
    await evaluate(
        "const a = document.createElement('a');"
        "a.href = 'https://en.wikipedia.org/wiki/Dog'; a.id = 'probe';"
        "document.body.appendChild(a); a.click(); 'clicked'"
    )
    await asyncio.sleep(3)

    assert await evaluate("location.href") == "https://en.wikipedia.org/wiki/Dog"


_PROBE_LINK = (
    "const a = document.createElement('a');"
    "a.href = 'https://en.wikipedia.org/wiki/Dog'; a.id = 'probe';"
    "document.body.appendChild(a);"
)


async def test_a_click_that_navigates_returns_before_the_page_loads(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # Browser-Use gives a click 15s; the command answers at once, as in Chrome,
    # and the navigation follows with its own events.
    client, session_id, evaluate = at_wiki
    _, error, elapsed = await client.call(
        "Runtime.evaluate", {"expression": _PROBE_LINK + "a.click(); 'clicked'"}, session_id
    )
    await asyncio.sleep(3)

    assert error is None
    assert elapsed < _PROMPT_SECONDS
    assert await evaluate("location.href") == "https://en.wikipedia.org/wiki/Dog"


async def test_runtime_evaluate_waits_for_a_promise(at_wiki: tuple[Cdp, str, Evaluate]) -> None:
    # browser/session.py:2574 -- every JS read Browser-Use makes.
    _, _, evaluate = at_wiki

    assert await evaluate("new Promise(r => setTimeout(() => r('resolved'), 300))") == "resolved"


async def test_the_accessibility_tree_is_served(at_wiki: tuple[Cdp, str, Evaluate]) -> None:
    # dom/service.py:361 -- the AX names Browser-Use labels elements with.
    client, session_id, _ = at_wiki
    tree = await client.ok("Accessibility.getFullAXTree", {}, session_id)

    assert len(tree["nodes"]) > 100


async def test_device_metrics_override_resizes_the_viewport(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # browser/session.py:3332 -- the viewport Jev's screenshots are framed in.
    client, session_id, evaluate = at_wiki
    await client.ok(
        "Emulation.setDeviceMetricsOverride",
        {"width": 800, "height": 600, "deviceScaleFactor": 1, "mobile": False},
        session_id,
    )
    await asyncio.sleep(0.5)
    try:
        assert await evaluate("innerWidth") == 800
        assert await evaluate("innerHeight") == 600
    finally:
        await client.call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 720, "deviceScaleFactor": 1, "mobile": False},
            session_id,
        )


# --- our own host ---------------------------------------------------------------


async def test_the_host_refuses_to_re_enable_downloads(page: tuple[Cdp, str]) -> None:
    # downloads_watchdog.py:416 would undo the per-context download deny; our
    # proxy's refusal table (app/browser_host/proxy.py) stops it.
    client, _ = page
    _, error, _ = await client.call(
        "Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": "/tmp"}
    )

    assert error is not None
    assert error["code"] == _REFUSED
    assert "downloads are denied" in error["message"]


async def test_the_host_costs_about_a_millisecond_a_command(
    at_wiki: tuple[Cdp, str, Evaluate],
) -> None:
    # The proxy forwards on one shared connection with no per-command timeout and
    # no pacing, so a command waits only on the engine. Guards against a future
    # change that makes every forwarded command wait behind something.
    client, session_id, _ = at_wiki
    samples: list[float] = []
    for _ in range(11):
        _, error, elapsed = await client.call(
            "Runtime.evaluate", {"expression": "1", "returnByValue": True}, session_id
        )
        assert error is None
        samples.append(elapsed)

    assert sorted(samples)[5] < 0.05
