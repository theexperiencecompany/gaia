"""Clicks must land on the element's real rect, through the one dispatch Obscura honours.

Browser-Use dispatches Input mouse events at the point it computes for an
element. On the Obscura host those events are accepted and dropped -- nothing
reaches the page -- so the patch clicks the element handle in JavaScript
instead and reports the centre of the rect the page itself measured.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
import pytest

import app.patches.browser_use_click_patch as patch_module
from tests.helpers import OBSCURA_TEST_CDP_URL

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("obscura_host")]

# What the page measures for the search button, and what the snapshot fabricates
# for it -- a click computed from the snapshot lands a whole page down.
_REAL_RECT = {"x": 670.0, "y": 17.0, "width": 70.0, "height": 32.0}
_REAL_CENTRE = {"click_x": 705.0, "click_y": 33.0}


class _Input:
    """The Input domain is dead on Obscura; touching it at all is the bug."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the patched click must not call Input.{name}")


_SESSION = "sess"


def _session_of(session_id: str) -> None:
    """Refuse a command sent to any session but the node's own, as another frame's target would."""
    if session_id != _SESSION:
        raise RuntimeError(f"no target attached under session {session_id!r}")


class _FakeCdp:
    """Answers the way Chromium's CDP does, and only for the node's own session."""

    def __init__(
        self,
        *,
        rect: dict[str, float] | None = _REAL_RECT,
        object_id: str | None = "obj-11",
        throws: bool = False,
    ) -> None:
        self.rect = rect
        self.scrolled: list[int] = []
        self.resolved: list[int] = []
        self.functions: list[str] = []

        class _DOM:
            @staticmethod
            async def scrollIntoViewIfNeeded(params: dict[str, Any], session_id: str) -> dict:
                _session_of(session_id)
                self.scrolled.append(params["backendNodeId"])
                return {}

            @staticmethod
            async def resolveNode(params: dict[str, Any], session_id: str) -> dict:
                _session_of(session_id)
                self.resolved.append(params["backendNodeId"])
                if object_id is None:
                    # A node detached since the snapshot resolves to no remote object.
                    return {"object": {"type": "object", "subtype": "node"}}
                return {"object": {"objectId": object_id}}

        class _Runtime:
            @staticmethod
            async def callFunctionOn(params: dict[str, Any], session_id: str) -> dict:
                _session_of(session_id)
                self.functions.append(params["functionDeclaration"])
                if params.get("objectId") != object_id:
                    raise RuntimeError("Could not find object with given id")
                if throws:
                    # An Error thrown by the page serialises by value to an empty object.
                    return {
                        "result": {"type": "object", "subtype": "error", "value": {}},
                        "exceptionDetails": {"text": "Uncaught"},
                    }
                if self.rect is None:
                    return {"result": {"value": None}}
                point = {
                    "click_x": self.rect["x"] + self.rect["width"] / 2,
                    "click_y": self.rect["y"] + self.rect["height"] / 2,
                }
                if params.get("returnByValue") is not True:
                    # Without returnByValue the page's object comes back as a handle.
                    return {"result": {"type": "object", "objectId": "obj-point"}}
                return {"result": {"value": point}}

        self.send = SimpleNamespace(DOM=_DOM(), Runtime=_Runtime(), Input=_Input())


def _watchdog(cdp: _FakeCdp, node: object | None = None) -> SimpleNamespace:
    """Build a watchdog whose browser session knows a CDP session for node only (any node when None)."""
    session = SimpleNamespace(session_id=_SESSION, cdp_client=cdp)

    async def cdp_client_for_node(asked: object) -> SimpleNamespace:
        if node is not None and asked is not node:
            raise ValueError("no CDP session for that node")
        return session

    return SimpleNamespace(
        browser_session=SimpleNamespace(
            cdp_url=OBSCURA_TEST_CDP_URL, cdp_client_for_node=cdp_client_for_node
        )
    )


def _node(tag: str = "button", attributes: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tag_name=tag,
        attributes=attributes or {},
        backend_node_id=11,
        # The snapshot's own geometry, fabricated on this engine.
        absolute_position=SimpleNamespace(x=0.0, y=4482.0, width=1280.0, height=18.0),
    )


@pytest.fixture(autouse=True)
def _no_settle_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the wall-clock settle pause; the fake page has nothing to settle."""
    monkeypatch.setattr(patch_module, "_SETTLE_SECONDS", 0)


def _recording_original(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[object, object]]:
    """Stand in for Browser-Use's own click and record who it was asked to click."""
    calls: list[tuple[object, object]] = []

    async def original(watchdog: object, node: object) -> dict[str, str]:
        calls.append((watchdog, node))
        return {"handled_by": "browser-use"}

    monkeypatch.setattr(patch_module, "_original_click_element_node_impl", original)
    return calls


async def test_the_click_point_is_the_centre_of_the_rect_the_page_measured() -> None:
    cdp = _FakeCdp()

    point = await patch_module._click_element_node_impl(_watchdog(cdp), _node())

    assert point == _REAL_CENTRE
    assert cdp.resolved == [11]
    assert "getBoundingClientRect" in cdp.functions[0]


async def test_the_element_is_clicked_in_the_page_and_no_mouse_event_is_dispatched() -> None:
    cdp = _FakeCdp()

    await patch_module._click_element_node_impl(_watchdog(cdp), _node())

    # _Input raises on any attribute, so reaching here proves nothing was dispatched.
    assert ".click()" in cdp.functions[0]


async def test_browser_uses_own_scroll_into_view_still_runs_first() -> None:
    cdp = _FakeCdp()

    await patch_module._click_element_node_impl(_watchdog(cdp), _node())

    assert cdp.scrolled == [11]


async def test_a_select_element_keeps_browser_uses_own_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    async def original(watchdog: object, node: object) -> dict[str, str]:
        seen.append(node)
        return {"validation_error": "Cannot click on <select> elements."}

    monkeypatch.setattr(patch_module, "_original_click_element_node_impl", original)
    cdp = _FakeCdp()

    result = await patch_module._click_element_node_impl(_watchdog(cdp), _node("select"))

    assert result == {"validation_error": "Cannot click on <select> elements."}
    assert len(seen) == 1
    assert cdp.resolved == []


async def test_a_file_input_keeps_browser_uses_own_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def original(watchdog: object, node: object) -> dict[str, str]:
        return {"validation_error": "File uploads must be handled using upload_file_to_element."}

    monkeypatch.setattr(patch_module, "_original_click_element_node_impl", original)
    cdp = _FakeCdp()

    result = await patch_module._click_element_node_impl(
        _watchdog(cdp), _node("input", {"type": "file"})
    )

    assert result == {
        "validation_error": "File uploads must be handled using upload_file_to_element."
    }
    assert cdp.resolved == []


async def test_an_element_the_page_cannot_measure_falls_back_to_browser_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero-sized or detached node has no rect to click; Browser-Use's own path reports it."""
    called: list[object] = []

    async def original(watchdog: object, node: object) -> None:
        called.append(node)

    monkeypatch.setattr(patch_module, "_original_click_element_node_impl", original)

    result = await patch_module._click_element_node_impl(_watchdog(_FakeCdp(rect=None)), _node())

    assert result is None
    assert len(called) == 1


async def test_apply_routes_the_watchdogs_click_through_the_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After apply, Browser-Use's own class clicks in the page instead of dispatching Input events."""
    monkeypatch.setattr(
        DefaultActionWatchdog,
        "_click_element_node_impl",
        patch_module._original_click_element_node_impl,
    )
    cdp = _FakeCdp()
    node = _node()

    patch_module.apply()
    point = await DefaultActionWatchdog._click_element_node_impl(_watchdog(cdp, node), node)

    assert point == _REAL_CENTRE


async def test_every_cdp_command_goes_to_the_nodes_own_session() -> None:
    """The node may live in an iframe's target; its session is the only one that knows it."""
    cdp = _FakeCdp()
    node = _node()

    point = await patch_module._click_element_node_impl(_watchdog(cdp, node), node)

    assert point == _REAL_CENTRE
    assert cdp.scrolled == [11]


@pytest.mark.parametrize(
    ("tag", "attributes"),
    [
        ("select", {}),
        ("input", {"type": "file"}),
        # Attribute values keep the page's own case.
        ("input", {"type": "FILE"}),
    ],
)
async def test_selects_and_file_inputs_are_handed_to_browser_use_with_the_same_node(
    monkeypatch: pytest.MonkeyPatch, tag: str, attributes: dict[str, str]
) -> None:
    calls = _recording_original(monkeypatch)
    cdp = _FakeCdp()
    watchdog = _watchdog(cdp)
    node = _node(tag, attributes)

    result = await patch_module._click_element_node_impl(watchdog, node)

    assert result == {"handled_by": "browser-use"}
    assert calls == [(watchdog, node)]
    assert cdp.resolved == []


@pytest.mark.parametrize(
    ("tag", "attributes"),
    [
        # A text box has no type attribute at all.
        ("input", {}),
        ("input", {"type": "text"}),
        # Only an <input> is a file picker, whatever a type attribute elsewhere says.
        ("button", {"type": "file"}),
    ],
)
async def test_other_elements_are_clicked_in_the_page(
    monkeypatch: pytest.MonkeyPatch, tag: str, attributes: dict[str, str]
) -> None:
    calls = _recording_original(monkeypatch)
    cdp = _FakeCdp()

    point = await patch_module._click_element_node_impl(_watchdog(cdp), _node(tag, attributes))

    assert point == _REAL_CENTRE
    assert calls == []


async def test_a_node_that_resolves_to_no_object_is_handed_to_browser_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recording_original(monkeypatch)
    cdp = _FakeCdp(object_id=None)
    watchdog = _watchdog(cdp)
    node = _node()

    result = await patch_module._click_element_node_impl(watchdog, node)

    assert result == {"handled_by": "browser-use"}
    assert calls == [(watchdog, node)]
    assert cdp.functions == []


async def test_an_unmeasurable_element_is_handed_to_browser_use_with_the_same_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recording_original(monkeypatch)
    watchdog = _watchdog(_FakeCdp(rect=None))
    node = _node()

    result = await patch_module._click_element_node_impl(watchdog, node)

    assert result == {"handled_by": "browser-use"}
    assert calls == [(watchdog, node)]


async def test_a_click_that_throws_in_the_page_is_handed_to_browser_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thrown Error serialises to an empty object, which is no click point."""
    calls = _recording_original(monkeypatch)
    watchdog = _watchdog(_FakeCdp(throws=True))
    node = _node()

    result = await patch_module._click_element_node_impl(watchdog, node)

    assert result == {"handled_by": "browser-use"}
    assert calls == [(watchdog, node)]
