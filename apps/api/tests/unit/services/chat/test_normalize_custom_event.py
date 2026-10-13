"""normalize_custom_event turns get_stream_writer() card payloads into tool_data.

Regression: the device onboarding/approval cards emit
{"device_onboarding_required": {...}} / {"device_approval_required": {...}}
via get_stream_writer(), but those keys were missing from tool_fields — the
single registry normalize_custom_event iterates. An unrecognized key is returned
as a "non-tool event" (passed through unwrapped), so no tool_data frame ever
reached the frontend and the card silently never rendered. The agent then had a
setup step that produced no visible card.
"""

import pytest

from app.services.chat.chunks import normalize_custom_event

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
    payload = {field_name: {"code": "MBDQ-GXGE", "message": "x"}}

    result = normalize_custom_event(payload)

    tool_data = result.get("tool_data")
    assert isinstance(tool_data, dict), (
        f"{field_name} was not recognized as a tool field — it must be in "
        "tool_fields or the card never renders"
    )
    assert tool_data["tool_name"] == field_name
    assert tool_data["data"] == payload[field_name]
