"""Decoding DOMSnapshot's rare-data columns into per-node live form state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.constants.log_tags import LogTag
from app.services.browser.jev import live_values as live_values_mod
from app.services.browser.jev.live_values import LiveValues, parse_snapshot, read_live_values

pytestmark = pytest.mark.unit


def test_parse_maps_values_checked_and_selected_by_backend_node_id() -> None:
    snapshot = {
        "strings": ["Zurich", "", "London"],
        "documents": [
            {
                "nodes": {
                    "backendNodeId": [10, 11, 12, 13, 14, 15],
                    "inputValue": {"index": [1, 2, 3], "value": [0, 1, 2]},
                    "inputChecked": {"index": [4]},
                    "optionSelected": {"index": [5]},
                }
            }
        ],
    }

    live = parse_snapshot(snapshot)

    assert live.values == {11: "Zurich", 12: "", 13: "London"}
    assert live.checked == frozenset({14})
    assert live.selected_options == frozenset({15})


def test_parse_spans_frames_and_tolerates_missing_columns() -> None:
    snapshot = {
        "strings": ["a"],
        "documents": [
            {"nodes": {"backendNodeId": [1], "inputValue": {"index": [0], "value": [0]}}},
            {"nodes": {"backendNodeId": [2], "inputChecked": {"index": [0]}}},
            {"nodes": {}},
        ],
    }

    live = parse_snapshot(snapshot)

    assert live == LiveValues(values={1: "a"}, checked=frozenset({2}))


def test_a_negative_string_index_is_an_empty_value() -> None:
    snapshot = {
        "strings": [],
        "documents": [
            {"nodes": {"backendNodeId": [7], "inputValue": {"index": [0], "value": [-1]}}}
        ],
    }

    assert parse_snapshot(snapshot).values == {7: ""}


async def test_read_takes_one_snapshot_from_the_sessions_cdp_client() -> None:
    seen: list[tuple[dict[str, object], str]] = []

    class _DOMSnapshot:
        async def captureSnapshot(self, params, session_id):
            seen.append((params, session_id))
            return {
                "strings": ["x"],
                "documents": [
                    {"nodes": {"backendNodeId": [3], "inputValue": {"index": [0], "value": [0]}}}
                ],
            }

    session = SimpleNamespace(
        session_id="sess",
        cdp_client=SimpleNamespace(send=SimpleNamespace(DOMSnapshot=_DOMSnapshot())),
    )

    async def get_or_create_cdp_session():
        return session

    browser = SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)

    live = await read_live_values(browser)  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session

    assert live.values == {3: "x"}
    assert seen == [({"computedStyles": [], "includeDOMRects": False}, "sess")]


async def test_a_failed_read_degrades_to_attribute_values_and_is_logged(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr(live_values_mod, "log", logger)

    async def get_or_create_cdp_session():
        raise ConnectionError("gone")

    browser = SimpleNamespace(get_or_create_cdp_session=get_or_create_cdp_session)

    assert await read_live_values(browser) == LiveValues()  # type: ignore[arg-type]  # the test hands a fake session in place of Browser-Use's session
    logger.warning.assert_called_once_with(
        f"{LogTag.BROWSER} Jev live-value snapshot failed", error_type="ConnectionError"
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        pytest.param({"strings": []}, id="no documents"),
        pytest.param({"strings": [], "documents": [{}]}, id="a document without nodes"),
        pytest.param(
            {"strings": [], "documents": [{"nodes": {"backendNodeId": [1], "inputValue": {}}}]},
            id="an empty value column",
        ),
        pytest.param(
            {
                "strings": [],
                "documents": [
                    {"nodes": {"backendNodeId": [1], "inputChecked": {}, "optionSelected": {}}}
                ],
            },
            id="boolean columns without rows",
        ),
    ],
)
def test_a_snapshot_missing_any_column_reads_as_no_live_state(snapshot) -> None:
    assert parse_snapshot(snapshot) == LiveValues()


def test_a_value_column_out_of_step_with_its_rows_is_refused_not_half_read() -> None:
    snapshot = {
        "strings": ["a", "b"],
        "documents": [
            {"nodes": {"backendNodeId": [1, 2], "inputValue": {"index": [0, 1], "value": [0]}}}
        ],
    }

    with pytest.raises(ValueError):
        parse_snapshot(snapshot)
