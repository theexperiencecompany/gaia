"""Unit tests for ``app.models.composio_schemas.notion`` trigger payloads."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.notion import (
    NotionAllPageEventsPayload,
    NotionPageAddedPayload,
    NotionPageUpdatedPayload,
)


def test_page_added_requires_event_type() -> None:
    with pytest.raises(ValidationError):
        NotionPageAddedPayload.model_validate({"block": {"id": "b1"}})


def test_page_added_parses_block_as_object_dict() -> None:
    payload = NotionPageAddedPayload.model_validate(
        {"block": {"id": "b1", "type": "page", "depth": 0}, "event_type": "page_added"}
    )
    assert payload.block == {"id": "b1", "type": "page", "depth": 0}
    assert payload.event_type == "page_added"


def test_page_updated_parses() -> None:
    payload = NotionPageUpdatedPayload.model_validate(
        {"block": {"id": "b2"}, "event_type": "page_updated"}
    )
    assert payload.block == {"id": "b2"}


def test_all_page_events_parses() -> None:
    payload = NotionAllPageEventsPayload.model_validate({"event_type": "page_deleted"})
    assert payload.event_type == "page_deleted"
    assert payload.block is None


def test_unknown_fields_are_ignored_not_rejected() -> None:
    """Trigger payloads must tolerate extra Composio fields."""
    payload = NotionPageAddedPayload.model_validate(
        {"event_type": "page_added", "unexpected_new_field": {"deep": True}}
    )
    assert payload.event_type == "page_added"
    assert not hasattr(payload, "unexpected_new_field")
