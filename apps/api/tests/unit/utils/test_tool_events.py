"""normalize_custom_event turns get_stream_writer() card payloads into tool_data.

Regression: the device onboarding/approval cards emit
{"device_onboarding_required": {...}} / {"device_approval_required": {...}}
via get_stream_writer(), but those keys were missing from tool_fields — the
single registry normalize_custom_event iterates. An unrecognized key is returned
as a "non-tool event" (passed through unwrapped), so no tool_data frame ever
reached the frontend and the card silently never rendered. The agent then had a
setup step that produced no visible card.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine

from app.utils.tool_events import normalize_custom_event

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "field_name",
    [
        "device_onboarding_required",
        "device_approval_required",
        # control: the integration card this pattern was modeled on
        "integration_connection_required",
    ],
)
def test_card_payload_is_wrapped_as_tool_data(field_name: str) -> None:
    payload: dict[str, object] = {field_name: {"code": "MBDQ-GXGE", "message": "x"}}

    result = normalize_custom_event(payload)

    tool_data = result.get("tool_data")
    assert isinstance(tool_data, dict), (
        f"{field_name} was not recognized as a tool field — it must be in "
        "tool_fields or the card never renders"
    )
    assert tool_data["tool_name"] == field_name
    assert tool_data["data"] == payload[field_name]


@time_machine.travel(datetime(2026, 11, 15, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata")), tick=False)
def test_each_card_is_stamped_in_utc_and_the_other_keys_ride_beside_it() -> None:
    payload: dict[str, object] = {
        "email_fetch_data": [{"id": "m1"}],
        "integration_connection_required": {"integration": "gmail"},
        "nextPageToken": "page-2",
    }

    result = normalize_custom_event(payload)

    stamp = "2026-11-15T04:00:00+00:00"
    assert result == {
        "nextPageToken": "page-2",
        "tool_data": [
            {"tool_name": "email_fetch_data", "data": [{"id": "m1"}], "timestamp": stamp},
            {
                "tool_name": "integration_connection_required",
                "data": {"integration": "gmail"},
                "timestamp": stamp,
            },
        ],
    }


def test_an_already_normalized_payload_passes_through_untouched() -> None:
    payload: dict[str, object] = {
        "tool_data": {"tool_name": "x", "data": 1},
        "email_fetch_data": [{"id": "m1"}],
    }

    assert normalize_custom_event(payload) is payload
