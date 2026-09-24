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
from typing import TYPE_CHECKING

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from cdp_use.cdp.domsnapshot.commands import CaptureSnapshotReturns
    from cdp_use.cdp.domsnapshot.types import (
        DocumentSnapshot,
        NodeTreeSnapshot,
        RareBooleanData,
        RareStringData,
    )


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
        snapshot: CaptureSnapshotReturns = (
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


def parse_snapshot(snapshot: CaptureSnapshotReturns) -> LiveValues:
    """Decode DOMSnapshot.captureSnapshot's rare-data columns into per-node facts."""
    # Indexed only for a value row, which a missing table fails on under any default.
    strings = snapshot.get("strings", [])  # pragma: no mutate
    values: dict[int, str] = {}
    checked: set[int] = set()
    selected: set[int] = set()
    documents: list[DocumentSnapshot] = snapshot.get("documents", [])
    for document in documents:
        nodes: NodeTreeSnapshot = document.get("nodes", {})
        # As strings: read only through a row, which a missing column fails on either way.
        backend_ids = nodes.get("backendNodeId", [])  # pragma: no mutate
        input_value: RareStringData | None = nodes.get("inputValue")
        if input_value is not None:
            for row, string_index in zip(
                input_value.get("index", []), input_value.get("value", []), strict=True
            ):
                values[backend_ids[row]] = strings[string_index] if string_index >= 0 else ""
        checked.update(backend_ids[row] for row in _rows(nodes.get("inputChecked")))
        selected.update(backend_ids[row] for row in _rows(nodes.get("optionSelected")))
    return LiveValues(
        values=values, checked=frozenset(checked), selected_options=frozenset(selected)
    )


def _rows(column: RareBooleanData | None) -> list[int]:
    """Return the rows a rare boolean column marks true; none when the engine left it out."""
    return column.get("index", []) if column is not None else []
