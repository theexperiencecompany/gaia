"""Wrap a custom stream event's per-tool fields into the unified tool_data shape."""

from datetime import UTC, datetime

from app.models.chat_models import tool_fields
from shared.py.conversation_wire import ToolDataEntry


def normalize_custom_event(payload: dict[str, object]) -> dict[str, object]:
    """Normalize a raw tool payload dict into the unified tool_data format.

    The single conversion point reused by the executor streaming path, the
    comms loop, and the background collector. Already-normalized or non-tool
    payloads pass through unchanged; recognized fields wrap into tool_data
    (a list when several match).
    """
    if "tool_data" in payload:
        return payload

    timestamp = datetime.now(UTC).isoformat()
    entries: list[ToolDataEntry] = []
    for field_name in tool_fields:
        if payload.get(field_name) is not None:
            entries.append(
                {
                    "tool_name": field_name,
                    "data": payload[field_name],
                    "timestamp": timestamp,
                }
            )

    if not entries:
        return payload  # Non-tool event — pass through

    # Preserve non-tool keys (e.g. nextPageToken alongside email_fetch_data)
    other_keys = {k: v for k, v in payload.items() if k not in tool_fields}
    # A lone entry rides the envelope unwrapped; several ride as a list. The
    # frontend parser accepts both, and normalizing to a list here would change
    # the wire shape for every single-tool chunk.
    tool_data_value: ToolDataEntry | list[ToolDataEntry] = (
        entries[0] if len(entries) == 1 else entries
    )
    return {**other_keys, "tool_data": tool_data_value}
