"""Live form state: what a field holds now, not what its HTML said at load.

Browser-Use's DOM model keeps the value attribute and the accessible name,
so text the agent typed a step ago is invisible to the next observation and a
policy would type it again. jev-ultrafast reads current values in its atomic
snapshot; the one-call equivalent here is DOMSnapshot.captureSnapshot, which
reports every input's value, checked state and selected options keyed by
backend node id, the same ids Browser-Use's selector map carries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession


@dataclass(frozen=True)
class LiveValues:
    """Per backend node id: current input text, checked flags, selected <option>s."""

    values: dict[int, str] = field(default_factory=dict)
    checked: frozenset[int] = frozenset()
    selected_options: frozenset[int] = frozenset()


async def read_live_values(browser: BrowserSession) -> LiveValues:
    """One CDP round-trip; empty (attributes only) when the snapshot is unavailable."""
    try:
        session = await browser.get_or_create_cdp_session()
        snapshot: dict[str, Any] = dict(
            await session.cdp_client.send.DOMSnapshot.captureSnapshot(
                params={"computedStyles": [], "includeDOMRects": False},
                session_id=session.session_id,
            )
        )
    except Exception as exc:  # a failed read degrades to attribute values, not a dead step
        log.warning(
            f"{LogTag.BROWSER} Jev live-value snapshot failed", error_type=type(exc).__name__
        )
        return LiveValues()
    return parse_snapshot(snapshot)


def parse_snapshot(snapshot: dict[str, Any]) -> LiveValues:
    """Decode DOMSnapshot.captureSnapshot's rare-data columns into per-node facts."""
    strings: list[str] = snapshot.get("strings", [])
    values: dict[int, str] = {}
    checked: set[int] = set()
    selected: set[int] = set()
    for document in snapshot.get("documents", []):
        nodes = document.get("nodes", {})
        backend_ids: list[int] = nodes.get("backendNodeId", [])
        input_value = nodes.get("inputValue", {})
        for row, string_index in zip(
            input_value.get("index", []), input_value.get("value", []), strict=True
        ):
            values[backend_ids[row]] = strings[string_index] if string_index >= 0 else ""
        checked.update(backend_ids[row] for row in nodes.get("inputChecked", {}).get("index", []))
        selected.update(
            backend_ids[row] for row in nodes.get("optionSelected", {}).get("index", [])
        )
    return LiveValues(
        values=values, checked=frozenset(checked), selected_options=frozenset(selected)
    )
