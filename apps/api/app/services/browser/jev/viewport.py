"""What the page itself says is on screen, one CDP evaluate per step.

Browser-Use's snapshot carries absolute_position and is_visible, but on some
engines that geometry is fabricated: boxes march down a phantom document far
past the real page height while every node claims to be visible. Filtering on
it empties the element table. The page is the only truth, so each observation
resolves the nodes' xpaths in the live document and reads getBoundingClientRect
and checkVisibility there.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import TYPE_CHECKING, Any

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession, CDPSession
    from browser_use.dom.views import EnhancedDOMTreeNode

# An element inside an iframe would need its own frame to walk parents in.
_MAX_ANCESTORS = 200
# Concurrent CDP calls on the per-node fallback; enough to hide the round-trip
# without flooding a host that serialises its protocol.
_RESOLVE_CONCURRENCY = 32
_MEASURE_BATCH = 100

_MEASURE_JS = """(pairs) => {
  const out = {};
  const w = window.innerWidth, h = window.innerHeight;
  for (const pair of pairs) {
    const index = pair[0], xpath = pair[1];
    let node = null;
    try {
      node = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null)
        .singleNodeValue;
    } catch (err) { node = null; }
    const el = node && node.nodeType === 1 ? node : null;
    if (!el) continue;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    const shown = typeof el.checkVisibility === 'function'
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : true;
    out[index] = {
      on_screen: !!(shown && rect.width > 0 && rect.height > 0
        && cx >= 0 && cx < w && cy >= 0 && cy < h),
      cx: w ? cx / w : 0,
      cy: h ? cy / h : 0,
    };
  }
  return out;
}"""

_MEASURE_HANDLES_JS = """function(...elements) {
  const w = window.innerWidth, h = window.innerHeight;
  return elements.map((el) => {
    if (!el || el.nodeType !== 1) return null;
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    const shown = typeof el.checkVisibility === 'function'
      ? el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      : true;
    return {
      on_screen: !!(shown && rect.width > 0 && rect.height > 0
        && cx >= 0 && cx < w && cy >= 0 && cy < h),
      cx: w ? cx / w : 0,
      cy: h ? cy / h : 0,
    };
  });
}"""


@dataclass(frozen=True)
class _Target:
    index: int
    xpath: str
    backend_node_id: int | None


@dataclass(frozen=True)
class ViewportBox:
    """One element as the page sees it: on screen, and its centre as a 0..1 fraction."""

    on_screen: bool
    cx: float
    cy: float


async def read_viewport(
    browser: BrowserSession, selector_map: dict[int, EnhancedDOMTreeNode]
) -> dict[int, ViewportBox]:
    """Measure the page; an index is absent when the page could not resolve it.

    One Runtime.evaluate over every xpath, falling back to per-node resolution
    on engines whose snapshot carries no parent chain to build an xpath from.
    """
    targets, framed = _targets(selector_map)
    if framed:
        log.debug(
            f"{LogTag.BROWSER} Jev viewport cannot measure iframe content",
            browser={"nodes": framed},
        )
    if not targets:
        return {}
    try:
        session = await browser.get_or_create_cdp_session()
        boxes = await _by_xpath(session, targets)
        if not boxes:
            boxes = await _by_backend_node(session, targets)
    except Exception as exc:  # a failed read degrades to "everything unknown", not a dead step
        log.warning(f"{LogTag.BROWSER} Jev viewport read failed", error_type=type(exc).__name__)
        return {}
    return boxes


def _targets(selector_map: dict[int, EnhancedDOMTreeNode]) -> tuple[list[_Target], int]:
    """Return the nodes the top document can measure, and how many iframe ones it cannot."""
    targets: list[_Target] = []
    framed = 0
    for index in sorted(selector_map):
        node = selector_map[index]
        if _inside_iframe(node):
            framed += 1
            continue
        xpath = str(getattr(node, "xpath", None) or "")
        backend_node_id = getattr(node, "backend_node_id", None)
        if xpath or backend_node_id is not None:
            targets.append(_Target(index, xpath, backend_node_id))
    return targets, framed


async def _by_xpath(session: CDPSession, targets: list[_Target]) -> dict[int, ViewportBox]:
    """Resolve every xpath in one evaluate; empty when this engine has no usable xpaths."""
    pairs = [[t.index, t.xpath] for t in targets if t.xpath]
    if not pairs:
        return {}
    response: dict[str, Any] = dict(
        await session.cdp_client.send.Runtime.evaluate(
            params={
                "expression": f"({_MEASURE_JS})({json.dumps(pairs)})",
                "returnByValue": True,
                "awaitPromise": False,
            },
            session_id=session.session_id,
        )
    )
    return _parse(response)


async def _by_backend_node(session: CDPSession, targets: list[_Target]) -> dict[int, ViewportBox]:
    """Measure each node through its backend id: N resolveNode calls, then batched measures.

    The engine Jev runs against serialises no parent chain, so Browser-Use's
    xpath collapses to a bare tag name that matches nothing.
    """
    semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

    async def resolve(target: _Target) -> tuple[int, str] | None:
        async with semaphore:
            try:
                resolved = await session.cdp_client.send.DOM.resolveNode(
                    params={"backendNodeId": target.backend_node_id},
                    session_id=session.session_id,
                )
            except Exception as exc:
                log.debug(
                    f"{LogTag.BROWSER} Jev viewport could not resolve a node",
                    error_type=type(exc).__name__,
                )
                return None
        payload: dict[str, Any] = dict(resolved)
        object_id = (payload.get("object") or {}).get("objectId")
        return (target.index, str(object_id)) if object_id else None

    handles = [
        handle
        for handle in await asyncio.gather(
            *(resolve(t) for t in targets if t.backend_node_id is not None)
        )
        if handle is not None
    ]
    batches = [handles[i : i + _MEASURE_BATCH] for i in range(0, len(handles), _MEASURE_BATCH)]
    measured = await asyncio.gather(*(_measure_batch(session, batch) for batch in batches))
    return {index: box for batch in measured for index, box in batch.items()}


async def _measure_batch(
    session: CDPSession, batch: list[tuple[int, str]]
) -> dict[int, ViewportBox]:
    response: dict[str, Any] = dict(
        await session.cdp_client.send.Runtime.callFunctionOn(
            params={
                "functionDeclaration": _MEASURE_HANDLES_JS,
                "objectId": batch[0][1],
                "arguments": [{"objectId": object_id} for _, object_id in batch],
                "returnByValue": True,
            },
            session_id=session.session_id,
        )
    )
    if response.get("exceptionDetails"):
        return {}
    values = (response.get("result") or {}).get("value") or []
    return _boxes_from_rows(
        {str(index): value for (index, _), value in zip(batch, values, strict=False) if value}
    )


def _inside_iframe(node: EnhancedDOMTreeNode) -> bool:
    current = getattr(node, "parent_node", None)
    for _ in range(_MAX_ANCESTORS):
        if current is None:
            return False
        if (getattr(current, "node_name", "") or "").lower() == "iframe":
            return True
        current = getattr(current, "parent_node", None)
    return False


def _parse(response: dict[str, Any]) -> dict[int, ViewportBox]:
    if response.get("exceptionDetails"):
        log.warning(f"{LogTag.BROWSER} Jev viewport read raised in the page", error_type="JSError")
        return {}
    value = (response.get("result") or {}).get("value")
    return _boxes_from_rows(value) if isinstance(value, dict) else {}


def _boxes_from_rows(rows: dict[str, Any]) -> dict[int, ViewportBox]:
    boxes: dict[int, ViewportBox] = {}
    for index, box in rows.items():
        try:
            boxes[int(index)] = ViewportBox(
                on_screen=bool(box["on_screen"]), cx=float(box["cx"]), cy=float(box["cy"])
            )
        except (KeyError, TypeError, ValueError):
            continue
    return boxes
