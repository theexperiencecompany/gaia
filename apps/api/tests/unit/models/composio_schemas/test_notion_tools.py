"""Unit tests for app/models/composio_schemas/notion_tools.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.notion_tools import NotionFetchDataData, NotionItem


class TestNotionFetchDataData:
    def test_get_items_returns_typed_models(self):
        m = NotionFetchDataData(values=[{"id": "p1", "title": "A"}, {"id": "p2", "title": "B"}])
        items = m.get_items()
        assert isinstance(items[0], NotionItem)
        assert [i.id for i in items] == ["p1", "p2"]

    def test_get_items_skips_non_dicts(self):
        # `values` is list[dict], so non-dicts can only exist via model_construct
        # (bypasses validation); get_items must still filter them out.
        m = NotionFetchDataData.model_construct(values=[{"id": "p1"}, "junk", None, 7])
        items = m.get_items()
        assert [i.id for i in items] == ["p1"]

    def test_get_items_skips_missing_id(self):
        m = NotionFetchDataData(values=[{"title": "no-id"}])
        with pytest.raises(ValidationError):
            m.get_items()
