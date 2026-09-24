"""Reading on-screen truth from the page itself, one CDP evaluate per step."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TypedDict, cast
from unittest.mock import MagicMock

from browser_use.browser.session import BrowserSession
from browser_use.dom.views import EnhancedDOMTreeNode
import pytest

from app.constants.browser import JEV_PAGE_TEXT_MAX_CHARS
from app.constants.log_tags import LogTag
from app.services.browser.jev import viewport as viewport_mod
from app.services.browser.jev.viewport import (
    NodeHandles,
    ViewportBox,
    ViewportRead,
    read_viewport,
)

pytestmark = pytest.mark.unit


def _node(
    xpath: str,
    *,
    parent: EnhancedDOMTreeNode | None = None,
    node_name: str = "A",
    backend_node_id: int | None = None,
) -> EnhancedDOMTreeNode:
    return cast(
        EnhancedDOMTreeNode,
        SimpleNamespace(
            xpath=xpath,
            parent_node=parent,
            node_name=node_name,
            frame_id=None,
            backend_node_id=backend_node_id,
        ),
    )


class _Call(TypedDict):
    params: dict[str, object]
    session_id: str


def _browser(result: object, seen: list[_Call] | None = None) -> BrowserSession:
    class _Runtime:
        async def evaluate(self, params, session_id):
            if seen is not None:
                seen.append(_Call(params=params, session_id=session_id))
            if isinstance(result, Exception):
                raise result
            return result

    session = SimpleNamespace(
        session_id="sess", cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=_Runtime()))
    )

    async def get_or_create_cdp_session():
        return session

    return cast(
        BrowserSession, SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
    )


def _pairs_sent(seen: list[_Call]) -> list[list[object]]:
    expression = str(seen[0]["params"]["expression"])
    payload = expression[expression.rindex("([") + 1 : expression.rindex("])") + 1]
    return json.loads(payload)


async def test_every_index_and_xpath_pair_reaches_the_page_and_comes_back_as_a_box() -> None:
    seen: list[_Call] = []
    browser = _browser(
        {
            "result": {
                "value": {
                    "7": {"on_screen": True, "cx": 0.25, "cy": 0.5},
                    "9": {"on_screen": False, "cx": 1.4, "cy": 0.1},
                }
            }
        },
        seen,
    )
    selector_map = {7: _node("html/body/a"), 9: _node("html/body/div/button")}

    boxes = (await read_viewport(browser, selector_map)).boxes

    assert _pairs_sent(seen) == [[7, "html/body/a"], [9, "html/body/div/button"]]
    assert seen[0]["session_id"] == "sess"
    assert seen[0]["params"]["returnByValue"] is True
    assert boxes == {
        7: ViewportBox(on_screen=True, cx=0.25, cy=0.5),
        9: ViewportBox(on_screen=False, cx=1.4, cy=0.1),
    }


async def test_an_xpath_that_resolved_nothing_is_simply_absent() -> None:
    browser = _browser({"result": {"value": {"7": {"on_screen": True, "cx": 0.1, "cy": 0.2}}}})

    boxes = (await read_viewport(browser, {7: _node("html/body/a"), 9: _node("html/body/b")})).boxes

    assert set(boxes) == {7}


async def test_a_cdp_failure_degrades_to_an_empty_map_and_warns(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)

    screen = await read_viewport(_browser(ConnectionError("gone")), {1: _node("html/body/a")})

    assert screen == ViewportRead()
    logger.warning.assert_any_call(
        f"{LogTag.BROWSER} Jev viewport read failed", error_type="ConnectionError"
    )


async def test_a_javascript_exception_degrades_to_an_empty_map_and_warns(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)

    browser = _browser({"exceptionDetails": {"text": "boom"}, "result": {}})

    assert (await read_viewport(browser, {1: _node("html/body/a")})).boxes == {}
    logger.warning.assert_any_call(
        f"{LogTag.BROWSER} Jev viewport read raised in the page", error_type="JSError"
    )


async def test_nodes_inside_an_iframe_are_never_asked_about_and_are_counted() -> None:
    """Browser-Use's xpath stops at the iframe, so it cannot be resolved from the top document."""
    logger = MagicMock()
    seen: list[_Call] = []
    browser = _browser({"result": {"value": {}}}, seen)
    frame = _node("html/body/iframe", node_name="IFRAME")
    selector_map = {1: _node("html/body/a"), 2: _node("div/button", parent=frame)}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(viewport_mod, "log", logger)
        boxes = (await read_viewport(browser, selector_map)).boxes

    assert boxes == {}
    assert _pairs_sent(seen) == [[1, "html/body/a"]]
    logger.debug.assert_called_once()


async def test_no_resolvable_node_skips_the_element_measure_entirely() -> None:
    """Nothing to measure still reads the screen's text, which needs no element."""
    seen: list[_Call] = []
    browser = _browser({"result": {"value": ""}}, seen)

    assert (await read_viewport(browser, {})).boxes == {}
    assert [call["params"]["expression"] for call in seen] == [
        f"({viewport_mod._SCREEN_JS})({JEV_PAGE_TEXT_MAX_CHARS})"
    ]


class _FallbackClient:
    """A CDP engine whose xpaths resolve nothing, so only backend node ids work."""

    def __init__(self) -> None:
        self.resolved: list[int] = []
        self.batched: list[list[str]] = []

        class _Runtime:
            @staticmethod
            async def evaluate(params, session_id):
                return {"result": {"value": {}}}

            @staticmethod
            async def callFunctionOn(params, session_id):
                ids = [argument["objectId"] for argument in params["arguments"]]
                self.batched.append(ids)
                return {
                    "result": {
                        "value": [
                            {"on_screen": object_id == "obj-11", "cx": 0.5, "cy": 0.25}
                            for object_id in ids
                        ]
                    }
                }

        class _DOM:
            @staticmethod
            async def resolveNode(params, session_id):
                self.resolved.append(params["backendNodeId"])
                return {"object": {"objectId": f"obj-{params['backendNodeId']}"}}

        self.send = SimpleNamespace(Runtime=_Runtime(), DOM=_DOM())


async def test_an_engine_without_usable_xpaths_is_measured_node_by_node() -> None:
    """Some engines serialise no parent chain, so every xpath collapses to a bare tag name."""
    client = _FallbackClient()
    session = SimpleNamespace(session_id="sess", cdp_client=client)

    async def get_or_create_cdp_session():
        return session

    browser = cast(
        BrowserSession, SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
    )
    selector_map = {
        3: _node("a", backend_node_id=11),
        4: _node("a", backend_node_id=12),
    }

    boxes = (await read_viewport(browser, selector_map)).boxes

    assert sorted(client.resolved) == [11, 12]
    assert client.batched == [["obj-11", "obj-12"]]
    assert boxes == {
        3: ViewportBox(on_screen=True, cx=0.5, cy=0.25),
        4: ViewportBox(on_screen=False, cx=0.5, cy=0.25),
    }


class _ScreenClient:
    """A CDP engine that answers the element measure and the viewport-screen read."""

    def __init__(
        self,
        text: object = "Visible line\nSecond line",
        url: str = "https://de.wikipedia.org/wiki/Berlin",
        title: str = "Berlin - Wikipedia",
        at_bottom: bool | None = None,
    ) -> None:
        self.text = text
        self.url = url
        self.title = title
        self.at_bottom = at_bottom
        self.expressions: list[str] = []

        class _Runtime:
            @staticmethod
            async def evaluate(params, session_id):
                self.expressions.append(params["expression"])
                if "createTreeWalker" in params["expression"]:
                    if isinstance(self.text, Exception):
                        raise self.text
                    value = {"text": self.text, "url": self.url, "title": self.title}
                    if self.at_bottom is not None:
                        value["at_bottom"] = self.at_bottom
                    return {"result": {"value": value}}
                return {"result": {"value": {"7": {"on_screen": True, "cx": 0.5, "cy": 0.5}}}}

        self.send = SimpleNamespace(Runtime=_Runtime())


def _screen_browser(client: _ScreenClient) -> BrowserSession:
    session = SimpleNamespace(session_id="sess", cdp_client=client)

    async def get_or_create_cdp_session():
        return session

    return cast(
        BrowserSession, SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
    )


async def test_the_screens_own_text_comes_back_with_the_boxes() -> None:
    client = _ScreenClient()

    screen = await read_viewport(_screen_browser(client), {7: _node("html/body/a")})

    assert screen.text == "Visible line\nSecond line"
    assert screen.boxes == {7: ViewportBox(on_screen=True, cx=0.5, cy=0.5)}


async def test_the_live_url_and_title_come_back_with_the_text() -> None:
    """The state summary's url can be pre-navigation; the page's own answer never is."""
    screen = await read_viewport(_screen_browser(_ScreenClient()), {7: _node("html/body/a")})

    assert screen.url == "https://de.wikipedia.org/wiki/Berlin"
    assert screen.title == "Berlin - Wikipedia"


async def test_the_viewport_text_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(viewport_mod, "JEV_PAGE_TEXT_MAX_CHARS", 7)

    screen = await read_viewport(_screen_browser(_ScreenClient()), {7: _node("html/body/a")})

    assert screen.text == "Visible"


async def test_a_text_read_that_fails_leaves_the_text_unknown(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)
    client = _ScreenClient(text=ConnectionError("gone"))

    screen = await read_viewport(_screen_browser(client), {7: _node("html/body/a")})

    assert (screen.text, screen.url, screen.title) == (None, None, None)
    # The element table survives a text failure; only the text is lost.
    assert screen.boxes == {7: ViewportBox(on_screen=True, cx=0.5, cy=0.5)}
    logger.warning.assert_called_once()


async def test_the_screens_text_is_stripped_of_zero_width_and_doubled_spaces() -> None:
    """Regression: a delivered sentence read "January  <ZWSP>1,  <ZWSP>1992"."""
    client = _ScreenClient(text="January  \u200b1,  \u200b1992\nNext\u00a0line  here")

    screen = await read_viewport(_screen_browser(client), {7: _node("html/body/a")})

    assert screen.text == "January 1, 1992\nNext line here"


async def test_the_page_end_being_on_screen_comes_back_with_the_text() -> None:
    client = _ScreenClient(at_bottom=True)

    screen = await read_viewport(_screen_browser(client), {7: _node("html/body/a")})

    assert screen.at_bottom is True


async def test_a_node_resolved_once_is_not_resolved_again_on_the_same_page() -> None:
    """Two hundred resolveNode round trips cost about 2 s on every step of a long page."""
    client = _FallbackClient()
    session = SimpleNamespace(session_id="sess", cdp_client=client)

    async def get_or_create_cdp_session():
        return session

    browser = cast(
        BrowserSession, SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
    )
    selector_map = {3: _node("a", backend_node_id=11), 4: _node("a", backend_node_id=12)}
    handles = NodeHandles()
    handles.on_page("https://example.com/list")

    first = (await read_viewport(browser, selector_map, handles)).boxes
    second = (await read_viewport(browser, selector_map, handles)).boxes
    handles.on_page("https://example.com/other")
    await read_viewport(browser, selector_map, handles)

    assert first == second
    assert client.resolved == [11, 12, 11, 12]
    assert len(client.batched) == 3


class _Engine:
    """A CDP page that keeps CDP's own rules: its session only, values only when asked by value.

    Each document generation hands out its own object ids; after the document is
    replaced in place, the old ids measure as nothing, as a detached handle does.
    """

    def __init__(
        self,
        *,
        xpaths: dict[str, ViewportBox] | None = None,
        screen: object = None,
        measurable: bool = True,
        unresolvable: frozenset[int] = frozenset(),
    ) -> None:
        self.xpaths = xpaths or {}
        self.screen = (
            screen if screen is not None else {"text": "On screen", "url": "https://x.test/"}
        )
        self.measurable = measurable
        self.unresolvable = unresolvable
        self.generation = 0
        self.resolved: list[int] = []
        self.xpath_evaluates = 0
        engine = self

        def _own_session(session_id: str) -> None:
            if session_id != "sess":
                raise RuntimeError("No session with given id")

        def _by_value(params: dict[str, object], value: object) -> dict[str, object]:
            if params.get("returnByValue") is not True:
                return {"result": {"type": "object", "objectId": "remote-1"}}
            return {"result": {"type": "object", "value": value}}

        class _Runtime:
            @staticmethod
            async def evaluate(params, session_id):
                _own_session(session_id)
                expression = params["expression"]
                if "createTreeWalker" in expression:
                    if isinstance(engine.screen, Exception):
                        raise engine.screen
                    return _by_value(params, engine.screen)
                engine.xpath_evaluates += 1
                pairs = json.loads(
                    expression[expression.rindex("([") + 1 : expression.rindex("])") + 1]
                )
                rows = {
                    str(index): {"on_screen": box.on_screen, "cx": box.cx, "cy": box.cy}
                    for index, xpath in pairs
                    if (box := engine.xpaths.get(xpath)) is not None
                }
                return _by_value(params, rows)

            @staticmethod
            async def callFunctionOn(params, session_id):
                _own_session(session_id)
                if "functionDeclaration" not in params or not isinstance(
                    params.get("objectId"), str
                ):
                    raise RuntimeError("Either objectId or executionContextId must be specified")
                rows = [
                    {"on_screen": True, "cx": 0.5, "cy": 0.5}
                    if engine.measurable and engine._live(argument["objectId"])
                    else None
                    for argument in params["arguments"]
                ]
                return _by_value(params, rows)

        class _DOM:
            @staticmethod
            async def resolveNode(params, session_id):
                _own_session(session_id)
                engine.resolved.append(params["backendNodeId"])
                if params["backendNodeId"] in engine.unresolvable:
                    raise RuntimeError("No node with given id found")
                return {"object": {"objectId": f"doc{engine.generation}-{params['backendNodeId']}"}}

        self.send = SimpleNamespace(Runtime=_Runtime(), DOM=_DOM())

    def _live(self, object_id: object) -> bool:
        return isinstance(object_id, str) and object_id.startswith(f"doc{self.generation}-")

    def replace_document(self) -> None:
        """Swap the document without the url changing, as a client-side render does."""
        self.generation += 1

    def browser(self) -> BrowserSession:
        session = SimpleNamespace(session_id="sess", cdp_client=self)

        async def get_or_create_cdp_session():
            return session

        return cast(
            BrowserSession, SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
        )


async def test_an_xpath_engine_answers_boxes_and_screen_text_through_the_pages_own_session() -> (
    None
):
    engine = _Engine(
        xpaths={"html/body/a": ViewportBox(on_screen=True, cx=0.2, cy=0.4)},
        screen={
            "text": "Top story",
            "url": "https://news.test/",
            "title": "News",
            "at_bottom": False,
        },
    )

    screen = await read_viewport(engine.browser(), {5: _node("html/body/a")})

    assert screen == ViewportRead(
        boxes={5: ViewportBox(on_screen=True, cx=0.2, cy=0.4)},
        text="Top story",
        url="https://news.test/",
        title="News",
        at_bottom=False,
    )


async def test_a_single_node_is_measured_through_its_own_handle() -> None:
    engine = _Engine()

    boxes = (await read_viewport(engine.browser(), {3: _node("", backend_node_id=11)})).boxes

    assert boxes == {3: ViewportBox(on_screen=True, cx=0.5, cy=0.5)}


async def test_a_node_without_an_xpath_skips_the_xpath_evaluate_and_is_measured_by_its_id() -> None:
    engine = _Engine()
    selector_map = {3: _node("", backend_node_id=11), 4: _node(None, backend_node_id=12)}  # type: ignore[arg-type]  # Browser-Use leaves xpath unset on some nodes

    boxes = (await read_viewport(engine.browser(), selector_map)).boxes

    assert set(boxes) == {3, 4}
    assert engine.xpath_evaluates == 0


async def test_revisiting_the_same_url_keeps_the_handles_already_resolved() -> None:
    engine = _Engine()
    selector_map = {3: _node("a", backend_node_id=11)}
    handles = NodeHandles()

    for _ in range(2):
        handles.on_page("https://news.test/")
        await read_viewport(engine.browser(), selector_map, handles)

    assert engine.resolved == [11]


async def test_handles_that_outlived_their_document_are_resolved_again_once() -> None:
    engine = _Engine()
    selector_map = {3: _node("a", backend_node_id=11), 4: _node("a", backend_node_id=12)}
    handles = NodeHandles()
    handles.on_page("https://app.test/")
    await read_viewport(engine.browser(), selector_map, handles)
    engine.replace_document()

    boxes = (await read_viewport(engine.browser(), selector_map, handles)).boxes
    third = (await read_viewport(engine.browser(), selector_map, handles)).boxes

    assert (
        boxes
        == third
        == {
            3: ViewportBox(on_screen=True, cx=0.5, cy=0.5),
            4: ViewportBox(on_screen=True, cx=0.5, cy=0.5),
        }
    )
    assert sorted(engine.resolved) == [11, 11, 12, 12]


async def test_a_page_whose_nodes_never_measure_is_given_up_after_one_fresh_resolve() -> None:
    engine = _Engine(measurable=False)

    boxes = (await read_viewport(engine.browser(), {3: _node("a", backend_node_id=11)})).boxes

    assert boxes == {}
    assert engine.resolved == [11, 11]


async def test_iframe_nodes_anywhere_in_the_map_are_counted_and_the_rest_still_measured(
    monkeypatch,
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)
    engine = _Engine(xpaths={"html/body/a": ViewportBox(on_screen=True, cx=0.1, cy=0.1)})
    frame = _node("html/body/iframe", node_name="iframe")
    wrapper = _node("div", parent=frame, node_name="DIV")
    selector_map = {
        1: _node("div/button", parent=frame),
        2: _node("span/button", parent=wrapper),
        3: _node("html/body/a"),
    }

    boxes = (await read_viewport(engine.browser(), selector_map)).boxes

    assert set(boxes) == {3}
    logger.debug.assert_called_once_with(
        f"{LogTag.BROWSER} Jev viewport cannot measure iframe content", browser={"nodes": 2}
    )


async def test_a_page_without_iframes_logs_no_iframe_note(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)
    engine = _Engine(xpaths={"html/body/a": ViewportBox(on_screen=True, cx=0.1, cy=0.1)})

    await read_viewport(engine.browser(), {1: _node("html/body/a")})

    logger.debug.assert_not_called()


@pytest.mark.parametrize(
    ("screen", "message", "error_type"),
    [
        pytest.param(
            ConnectionError("gone"),
            "Jev viewport text read failed",
            "ConnectionError",
            id="the call fails",
        ),
        pytest.param(
            {"text": 42},
            "Jev viewport text read returned an unexpected shape",
            "ValidationError",
            id="the page answers a wrong shape",
        ),
    ],
)
async def test_a_screen_text_read_that_cannot_be_used_is_unknown_and_says_why(
    monkeypatch, screen, message, error_type
) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)
    engine = _Engine(
        xpaths={"html/body/a": ViewportBox(on_screen=True, cx=0.1, cy=0.1)}, screen=screen
    )

    read = await read_viewport(engine.browser(), {1: _node("html/body/a")})

    assert (read.text, read.url, read.title, read.at_bottom) == (None, None, None, None)
    assert set(read.boxes) == {1}
    logger.warning.assert_called_once_with(f"{LogTag.BROWSER} {message}", error_type=error_type)


async def test_a_screen_text_read_that_throws_in_the_page_is_unknown_and_says_so(
    monkeypatch,
) -> None:
    """CDP hands the thrown error back as the result, whose value is an empty object."""
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)

    class _Throwing(_Engine):
        def __init__(self) -> None:
            super().__init__()
            evaluate = self.send.Runtime.evaluate

            async def throwing(params, session_id):
                if "createTreeWalker" in params["expression"]:
                    return {"exceptionDetails": {"text": "Uncaught"}, "result": {"value": {}}}
                return await evaluate(params, session_id)

            self.send = SimpleNamespace(
                Runtime=SimpleNamespace(evaluate=throwing), DOM=self.send.DOM
            )

    read = await read_viewport(_Throwing().browser(), {})

    assert (read.text, read.url, read.title) == (None, None, None)
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev viewport text read raised in the page", error_type="JSError"
    )


async def test_a_stale_handle_is_measured_afresh_beside_a_node_that_never_resolves() -> None:
    engine = _Engine(unresolvable=frozenset({13}))
    selector_map = {3: _node("a", backend_node_id=11), 4: _node("a", backend_node_id=13)}
    handles = NodeHandles()
    handles.on_page("https://app.test/")
    await read_viewport(engine.browser(), selector_map, handles)
    engine.replace_document()

    boxes = (await read_viewport(engine.browser(), selector_map, handles)).boxes

    assert boxes == {3: ViewportBox(on_screen=True, cx=0.5, cy=0.5)}


async def test_a_node_nested_deeper_than_the_ancestor_walk_is_not_taken_for_iframe_content() -> (
    None
):
    engine = _Engine(xpaths={"html/body/deep": ViewportBox(on_screen=True, cx=0.3, cy=0.3)})
    parent = None
    for _ in range(viewport_mod._MAX_ANCESTORS + 50):
        parent = _node("div", parent=parent, node_name="DIV")

    boxes = (
        await read_viewport(engine.browser(), {1: _node("html/body/deep", parent=parent)})
    ).boxes

    assert set(boxes) == {1}


async def test_an_ancestor_without_a_parent_link_ends_the_walk_as_top_document() -> None:
    """Some node shapes carry no parent_node at the top of their chain."""
    engine = _Engine(xpaths={"html/body/a": ViewportBox(on_screen=True, cx=0.3, cy=0.3)})
    top = cast(EnhancedDOMTreeNode, SimpleNamespace(node_name="BODY"))

    boxes = (await read_viewport(engine.browser(), {1: _node("html/body/a", parent=top)})).boxes

    assert set(boxes) == {1}


async def test_a_malformed_row_loses_only_its_own_element() -> None:
    browser = _browser(
        {
            "result": {
                "value": {
                    "1": {"on_screen": True},
                    "not-an-index": {"on_screen": True, "cx": 0.1, "cy": 0.1},
                    "2": {"on_screen": False, "cx": 0.4, "cy": 0.6},
                }
            }
        }
    )

    boxes = (await read_viewport(browser, {1: _node("html/body/a"), 2: _node("html/body/b")})).boxes

    assert boxes == {2: ViewportBox(on_screen=False, cx=0.4, cy=0.6)}
