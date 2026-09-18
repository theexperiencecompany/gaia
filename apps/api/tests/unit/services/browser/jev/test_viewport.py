"""Reading on-screen truth from the page itself, one CDP evaluate per step."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.constants.log_tags import LogTag
from app.services.browser.jev import viewport as viewport_mod
from app.services.browser.jev.viewport import ViewportBox, read_viewport

pytestmark = pytest.mark.unit


def _node(xpath: str, *, parent=None):
    return SimpleNamespace(xpath=xpath, parent_node=parent, node_name="A", frame_id=None)


def _browser(result: object, seen: list[dict[str, object]] | None = None):
    class _Runtime:
        async def evaluate(self, params, session_id):
            if seen is not None:
                seen.append({"params": params, "session_id": session_id})
            if isinstance(result, Exception):
                raise result
            return result

    session = SimpleNamespace(
        session_id="sess", cdp_client=SimpleNamespace(send=SimpleNamespace(Runtime=_Runtime()))
    )

    async def get_or_create_cdp_session():
        return session

    return SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)


def _pairs_sent(seen: list[dict[str, object]]) -> list[list[object]]:
    expression = seen[0]["params"]["expression"]
    payload = expression[expression.rindex("([") + 1 : expression.rindex("])") + 1]
    return json.loads(payload)


async def test_every_index_and_xpath_pair_reaches_the_page_and_comes_back_as_a_box() -> None:
    seen: list[dict[str, object]] = []
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

    boxes = await read_viewport(browser, selector_map)  # type: ignore[arg-type]

    assert _pairs_sent(seen) == [[7, "html/body/a"], [9, "html/body/div/button"]]
    assert seen[0]["session_id"] == "sess"
    assert seen[0]["params"]["returnByValue"] is True
    assert boxes == {
        7: ViewportBox(on_screen=True, cx=0.25, cy=0.5),
        9: ViewportBox(on_screen=False, cx=1.4, cy=0.1),
    }


async def test_an_xpath_that_resolved_nothing_is_simply_absent() -> None:
    browser = _browser({"result": {"value": {"7": {"on_screen": True, "cx": 0.1, "cy": 0.2}}}})

    boxes = await read_viewport(browser, {7: _node("html/body/a"), 9: _node("html/body/b")})  # type: ignore[arg-type]

    assert set(boxes) == {7}


async def test_a_cdp_failure_degrades_to_an_empty_map_and_warns(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)

    boxes = await read_viewport(_browser(ConnectionError("gone")), {1: _node("html/body/a")})  # type: ignore[arg-type]

    assert boxes == {}
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev viewport read failed", error_type="ConnectionError"
    )


async def test_a_javascript_exception_degrades_to_an_empty_map_and_warns(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(viewport_mod, "log", logger)

    browser = _browser({"exceptionDetails": {"text": "boom"}, "result": {}})

    assert await read_viewport(browser, {1: _node("html/body/a")}) == {}  # type: ignore[arg-type]
    logger.warning.assert_called_once()


async def test_nodes_inside_an_iframe_are_never_asked_about_and_are_counted() -> None:
    """Browser-Use's xpath stops at the iframe, so it cannot be resolved from the top document."""
    logger = MagicMock()
    seen: list[dict[str, object]] = []
    browser = _browser({"result": {"value": {}}}, seen)
    frame = SimpleNamespace(node_name="IFRAME", parent_node=None, xpath="html/body/iframe")
    selector_map = {1: _node("html/body/a"), 2: _node("div/button", parent=frame)}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(viewport_mod, "log", logger)
        boxes = await read_viewport(browser, selector_map)  # type: ignore[arg-type]

    assert boxes == {}
    assert _pairs_sent(seen) == [[1, "html/body/a"]]
    logger.debug.assert_called_once()


async def test_no_resolvable_node_skips_the_round_trip_entirely() -> None:
    seen: list[dict[str, object]] = []
    browser = _browser({"result": {"value": {}}}, seen)

    assert await read_viewport(browser, {}) == {}  # type: ignore[arg-type]
    assert seen == []


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

    browser = SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)
    selector_map = {
        3: SimpleNamespace(xpath="a", parent_node=None, backend_node_id=11),
        4: SimpleNamespace(xpath="a", parent_node=None, backend_node_id=12),
    }

    boxes = await read_viewport(browser, selector_map)  # type: ignore[arg-type]

    assert sorted(client.resolved) == [11, 12]
    assert client.batched == [["obj-11", "obj-12"]]
    assert boxes == {
        3: ViewportBox(on_screen=True, cx=0.5, cy=0.25),
        4: ViewportBox(on_screen=False, cx=0.5, cy=0.25),
    }
