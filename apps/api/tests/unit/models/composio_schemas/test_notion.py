"""Unit tests for app/models/composio_schemas/notion.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.notion import (
    NotionPageContentUpdatedPayload,
    NotionPageCreatedPayload,
    NotionPagePropertiesUpdatedPayload,
)


class TestNotionPageCreatedPayload:
    # Field set verified against Composio triggers_types API (2026-08).
    def _payload(self) -> dict:
        return {
            "authors": [{"type": "person"}],
            "data": {"parent": {"type": "data_source_id"}},
            "event_id": "evt1",
            "event_type": "page.created",
            "page_id": "page1",
            "timestamp": "2025-01-01T00:00:00Z",
            "workspace_id": "ws1",
            "workspace_name": "Acme",
        }

    def test_valid_full(self):
        m = NotionPageCreatedPayload.model_validate(self._payload())
        assert m.page_id == "page1"
        assert m.workspace_name == "Acme"

    def test_optional_fields_default_none(self):
        m = NotionPageCreatedPayload()
        assert m.authors is None
        assert m.workspace_name is None

    def test_wrong_type_page_id(self):
        with pytest.raises(ValidationError):
            NotionPageCreatedPayload(page_id=123)


class TestNotionPagePropertiesUpdatedPayload:
    def test_valid_full(self):
        m = NotionPagePropertiesUpdatedPayload(
            event_type="page.properties_updated",
            page_id="page1",
            data={"parent": {}, "changed_property_ids": ["title"]},
        )
        assert m.page_id == "page1"
        assert m.data is not None
        assert m.event_type == "page.properties_updated"


class TestNotionPageContentUpdatedPayload:
    def test_valid_full(self):
        m = NotionPageContentUpdatedPayload(
            event_type="page.content_updated",
            page_id="page1",
            data={"parent": {}, "updated_block_ids": ["b1"]},
        )
        assert m.page_id == "page1"
        assert m.data is not None


# ---------------------------------------------------------------------------
# asana trigger payloads
# ---------------------------------------------------------------------------
