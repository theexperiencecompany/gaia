"""What the page itself says is on screen: which elements, and which text.

Browser-Use's snapshot carries absolute_position and is_visible, but on some
engines that geometry is fabricated: boxes march down a phantom document far
past the real page height while every node claims to be visible. Filtering on
it empties the element table, and its page text is the whole document from the
top, so scrolling never changes a word of what Jev reads. The page is the only
truth, so each observation measures the nodes in the live document and walks
the text nodes the viewport actually shows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
import json
import re
from typing import TYPE_CHECKING, TypedDict

from pydantic import TypeAdapter, ValidationError

from app.constants.browser import JEV_PAGE_TEXT_MAX_CHARS
from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession, CDPSession
    from browser_use.dom.views import EnhancedDOMTreeNode
    from cdp_use.cdp.dom.commands import ResolveNodeReturns
    from cdp_use.cdp.runtime.commands import CallFunctionOnReturns, EvaluateReturns
    from cdp_use.cdp.runtime.types import RemoteObject

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


# The text a person reads off the screen: every text node whose parent is shown
# and whose own range rect overlaps the viewport, in document order. The live
# url and title ride along, because the state summary's pair can disagree.
_SCREEN_JS = r"""(limit) => {
  const w = window.innerWidth, h = window.innerHeight;
  const onScreen = (r) => r.bottom > 0 && r.top < h && r.right > 0 && r.left < w;
  // Walk elements and prune whole subtrees that lie off screen: a text node's
  // own rect is asked for only under an element that is (partly) on screen, so
  // a long article costs hundreds of layout reads, not one per text node.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      if (node.nodeType === Node.TEXT_NODE) return NodeFilter.FILTER_ACCEPT;
      if (typeof node.checkVisibility === 'function'
          && !node.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return NodeFilter.FILTER_REJECT;
      const r = node.getBoundingClientRect();
      // A box with no size (inline wrappers, display: contents) says nothing
      // about where its children are; descend without judging it.
      if ((r.width || r.height) && !onScreen(r)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_SKIP;
    },
  });
  const lines = [];
  let total = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
    const parent = node.parentElement;
    if (!text || !parent) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rect = range.getBoundingClientRect();
    if (!rect.width || !rect.height || !onScreen(rect)) continue;
    // A label the page cut short ("The Road to Little...") carries its full text in title.
    const stem = text.replace(/(\.\.\.|\u2026)$/, '').trim();
    const holder = stem !== text ? parent.closest('[title]') : null;
    const full = holder ? (holder.getAttribute('title') || '').trim() : '';
    const shown = full.startsWith(stem) ? full : text;
    lines.push(shown);
    total += shown.length + 1;
    if (total >= limit) break;
  }
  const doc = document.documentElement;
  const atBottom = window.scrollY + h >= Math.max(doc.scrollHeight, document.body.scrollHeight) - 2;
  return {text: lines.join('\n'), url: location.href, title: document.title, at_bottom: atBottom};
}"""


# Zero-width characters survive a JS \s+ collapse and reach the user's answer
# as stray gaps ("January  <ZWSP>1,  <ZWSP>1992"); NBSP becomes a plain space.
_INVISIBLE = str.maketrans(
    {"\u200b": None, "\u200c": None, "\u200d": None, "\ufeff": None, "\u00a0": " "}
)
_SPACE_RUN = re.compile(r"[ \t]+")


def normalize_page_text(text: str) -> str:
    """Return page text a person can read: no zero-width characters, one space per run, lines kept."""
    return _SPACE_RUN.sub(" ", text.translate(_INVISIBLE))


class _ScreenValue(TypedDict, total=False):
    """The viewport's own text, url, title and bottom flag, as _SCREEN_JS reports them."""

    text: str
    url: str
    title: str
    at_bottom: bool


class _ViewportRow(TypedDict):
    """One element's measured box, as _MEASURE_JS and _MEASURE_HANDLES_JS report it."""

    on_screen: bool
    cx: float
    cy: float


_SCREEN_VALUE: TypeAdapter[_ScreenValue] = TypeAdapter(_ScreenValue)
_VIEWPORT_ROW: TypeAdapter[_ViewportRow] = TypeAdapter(_ViewportRow)


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


@dataclass(frozen=True)
class ViewportRead:
    """One step's screen: the elements it shows, the text it shows, and where it is.

    An index absent from boxes is one the page could not resolve; text, url and
    title are None when the page could not be read at all, and the caller falls back.
    """

    boxes: dict[int, ViewportBox] = field(default_factory=dict)
    text: str | None = None
    url: str | None = None
    title: str | None = None
    #: True when the end of the page is on screen; None when the page could not say.
    at_bottom: bool | None = None


class NodeHandles:
    """Remote-object handles for backend node ids, kept for as long as one page lives.

    Resolving a node is one CDP round trip, serialised by the engine: 200 nodes
    cost about 2s on every step of a long page. A handle stays valid while its
    document does, so the same page pays that once.
    """

    def __init__(self) -> None:
        self._url: str | None = None  # pragma: no mutate — no handle is kept before a page
        self._handles: dict[int, str] = {}

    def on_page(self, url: str | None) -> None:
        """Forget every handle when the document changed; the old ones point into it."""
        if url != self._url:
            self._url = url
            self._handles = {}

    def get(self, backend_node_id: int) -> str | None:
        return self._handles.get(backend_node_id)

    def put(self, backend_node_id: int, object_id: str) -> None:
        self._handles[backend_node_id] = object_id

    def forget(self, backend_node_ids: Iterable[int]) -> None:
        for backend_node_id in backend_node_ids:
            self._handles.pop(backend_node_id, None)


async def read_viewport(
    browser: BrowserSession,
    selector_map: dict[int, EnhancedDOMTreeNode],
    handles: NodeHandles | None = None,
) -> ViewportRead:
    """Read the screen: measure every element on it, and collect the text it shows."""
    targets, framed = _targets(selector_map)
    if framed:
        log.debug(
            f"{LogTag.BROWSER} Jev viewport cannot measure iframe content",
            browser={"nodes": framed},
        )
    try:
        session = await browser.get_or_create_cdp_session()
        boxes, screen = await asyncio.gather(
            _measure(session, targets, handles or NodeHandles()), _screen(session)
        )
    except Exception as exc:  # a failed read degrades to "everything unknown", not a dead step
        log.warning(f"{LogTag.BROWSER} Jev viewport read failed", error_type=type(exc).__name__)
        return ViewportRead()
    return replace(screen, boxes=boxes)


async def _measure(
    session: CDPSession, targets: list[_Target], handles: NodeHandles
) -> dict[int, ViewportBox]:
    """One Runtime.evaluate over every xpath, falling back to per-node resolution.

    Some engines serialise no parent chain, so Browser-Use's xpath collapses to
    a bare tag name that matches nothing and only backend node ids work.
    """
    if not targets:
        return {}
    boxes = await _by_xpath(session, targets)
    return boxes or await _by_backend_node(session, targets, handles)


async def _screen(session: CDPSession) -> ViewportRead:
    """Return the viewport's own text, url and title; every field None when the page could not answer."""
    try:
        response: EvaluateReturns = await session.cdp_client.send.Runtime.evaluate(
            params={
                "expression": f"({_SCREEN_JS})({JEV_PAGE_TEXT_MAX_CHARS})",
                "returnByValue": True,
            },
            session_id=session.session_id,
        )
    except Exception as exc:  # the element table still stands; only the text is lost
        log.warning(
            f"{LogTag.BROWSER} Jev viewport text read failed", error_type=type(exc).__name__
        )
        return ViewportRead()
    if response.get("exceptionDetails"):
        log.warning(
            f"{LogTag.BROWSER} Jev viewport text read raised in the page", error_type="JSError"
        )
        return ViewportRead()
    try:
        value: _ScreenValue = _SCREEN_VALUE.validate_python(_returned_value(response.get("result")))
    except ValidationError:
        log.warning(
            f"{LogTag.BROWSER} Jev viewport text read returned an unexpected shape",
            error_type="ValidationError",
        )
        return ViewportRead()
    text = value.get("text")
    return ViewportRead(
        text=normalize_page_text(text)[:JEV_PAGE_TEXT_MAX_CHARS] if text is not None else None,
        url=value.get("url") or None,
        title=value.get("title") or None,
        at_bottom=value.get("at_bottom"),
    )


def _returned_value(result: RemoteObject | None) -> object:
    """Return the JSON value a returnByValue call produced; None when the page returned nothing."""
    return result.get("value") if result is not None else None


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
        backend_node_id = node.backend_node_id
        if xpath or backend_node_id is not None:
            targets.append(_Target(index, xpath, backend_node_id))
    return targets, framed


async def _by_xpath(session: CDPSession, targets: list[_Target]) -> dict[int, ViewportBox]:
    """Resolve every xpath in one evaluate; empty when this engine has no usable xpaths."""
    pairs = [[t.index, t.xpath] for t in targets if t.xpath]
    if not pairs:
        return {}
    response: EvaluateReturns = await session.cdp_client.send.Runtime.evaluate(
        params={
            "expression": f"({_MEASURE_JS})({json.dumps(pairs)})",
            "returnByValue": True,
        },
        session_id=session.session_id,
    )
    return _parse(response)


async def _by_backend_node(
    session: CDPSession, targets: list[_Target], handles: NodeHandles
) -> dict[int, ViewportBox]:
    """Measure each node through its backend id: a resolveNode per new node, then batched measures."""
    boxes, resolved_any = await _resolve_and_measure(session, targets, handles)
    if boxes or not resolved_any:
        return boxes
    # A kept handle can outlive its document without the url changing; drop them
    # all and measure this screen the slow way once, keeping what that resolves
    # so the next step is fast.
    handles.forget(t.backend_node_id for t in targets if t.backend_node_id is not None)
    boxes, _ = await _resolve_and_measure(session, targets, handles)
    return boxes


async def _resolve_and_measure(
    session: CDPSession, targets: list[_Target], handles: NodeHandles
) -> tuple[dict[int, ViewportBox], bool]:
    """Return the boxes measured through backend ids, and whether any node resolved at all."""
    semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

    async def resolve(target: _Target) -> tuple[int, str] | None:
        if target.backend_node_id is None:
            return None
        known = handles.get(target.backend_node_id)
        if known is not None:
            return (target.index, known)
        async with semaphore:
            try:
                resolved: ResolveNodeReturns = await session.cdp_client.send.DOM.resolveNode(
                    params={"backendNodeId": target.backend_node_id},
                    session_id=session.session_id,
                )
            except Exception as exc:
                log.debug(
                    f"{LogTag.BROWSER} Jev viewport could not resolve a node",
                    error_type=type(exc).__name__,
                )
                return None
        resolved_object: RemoteObject | None = resolved.get("object")
        object_id = resolved_object.get("objectId") if resolved_object is not None else None
        if not object_id:
            return None
        handles.put(target.backend_node_id, str(object_id))
        return (target.index, str(object_id))

    resolved = [
        handle
        for handle in await asyncio.gather(
            *(resolve(t) for t in targets if t.backend_node_id is not None)
        )
        if handle is not None
    ]
    batches = [resolved[i : i + _MEASURE_BATCH] for i in range(0, len(resolved), _MEASURE_BATCH)]
    measured = await asyncio.gather(*(_measure_batch(session, batch) for batch in batches))
    return {index: box for batch in measured for index, box in batch.items()}, bool(resolved)


async def _measure_batch(
    session: CDPSession, batch: list[tuple[int, str]]
) -> dict[int, ViewportBox]:
    response: CallFunctionOnReturns = await session.cdp_client.send.Runtime.callFunctionOn(
        params={
            "functionDeclaration": _MEASURE_HANDLES_JS,
            "objectId": batch[0][1],
            "arguments": [{"objectId": object_id} for _, object_id in batch],
            "returnByValue": True,
        },
        session_id=session.session_id,
    )
    # A throw in the page comes back as the error object, never a list of rows.
    raw_values = _returned_value(response.get("result"))
    if not isinstance(raw_values, list):
        return {}
    rows = zip(batch, raw_values, strict=False)  # pragma: no mutate — one row per element sent
    return _boxes_from_rows({str(index): value for (index, _), value in rows if value})


def _inside_iframe(node: EnhancedDOMTreeNode) -> bool:
    current = getattr(node, "parent_node", None)
    for _ in range(_MAX_ANCESTORS):
        if current is None:
            return False
        # Any stand-in for a missing name is equally not an iframe.
        name = getattr(current, "node_name", "") or ""  # pragma: no mutate
        if name.lower() == "iframe":
            return True
        current = getattr(current, "parent_node", None)
    return False


def _parse(response: EvaluateReturns) -> dict[int, ViewportBox]:
    if response.get("exceptionDetails"):
        log.warning(f"{LogTag.BROWSER} Jev viewport read raised in the page", error_type="JSError")
        return {}
    value = _returned_value(response.get("result"))
    return _boxes_from_rows(value) if isinstance(value, dict) else {}


def _boxes_from_rows(rows: Mapping[str, object]) -> dict[int, ViewportBox]:
    boxes: dict[int, ViewportBox] = {}
    for index, raw_box in rows.items():
        try:
            box: _ViewportRow = _VIEWPORT_ROW.validate_python(raw_box)
            boxes[int(index)] = ViewportBox(on_screen=box["on_screen"], cx=box["cx"], cy=box["cy"])
        except (ValidationError, ValueError):
            continue
    return boxes
