"""Unit tests for app/models/composio_schemas/notion_tools.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.notion_tools import (
    NotionFetchDataData,
    NotionFetchDataInput,
    NotionItem,
)


class TestNotionFetchDataInput:
    def test_defaults(self):
        m = NotionFetchDataInput(fetch_type="pages")
        assert m.fetch_type == "pages"
        assert m.page_size == 100
        assert m.query is None

    def test_valid_full(self):
        m = NotionFetchDataInput(fetch_type="all", page_size=50, query="roadmap")
        assert m.fetch_type == "all"
        assert m.page_size == 50
        assert m.query == "roadmap"

    @pytest.mark.parametrize("fetch_type", ["pages", "databases", "all"])
    def test_valid_fetch_types(self, fetch_type):
        m = NotionFetchDataInput(fetch_type=fetch_type)
        assert m.fetch_type == fetch_type

    @pytest.mark.parametrize("fetch_type", ["blocks", "PAGES", ""])
    def test_invalid_fetch_type(self, fetch_type):
        with pytest.raises(ValidationError):
            NotionFetchDataInput(fetch_type=fetch_type)

    def test_missing_fetch_type(self):
        with pytest.raises(ValidationError):
            NotionFetchDataInput()

    def test_wrong_type_page_size(self):
        with pytest.raises(ValidationError):
            NotionFetchDataInput(fetch_type="pages", page_size="hundred")


class TestNotionItem:
    def test_valid_minimal(self):
        m = NotionItem(id="page1")
        assert m.id == "page1"
        assert m.title is None
        assert m.type is None
        assert m.url is None

    def test_valid_full(self):
        m = NotionItem(id="page1", title="Roadmap", type="page", url="https://notion.so/page1")
        assert m.title == "Roadmap"
        assert m.type == "page"

    def test_extra_fields_ignored(self):
        m = NotionItem(id="page1", parent_id="ignored")
        assert not hasattr(m, "parent_id")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            NotionItem()

    def test_wrong_type_id(self):
        with pytest.raises(ValidationError):
            NotionItem(id=123)


class TestNotionFetchDataData:
    def test_defaults(self):
        m = NotionFetchDataData()
        assert m.values == []
        assert m.get_items() == []

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

    def test_extra_fields_ignored(self):
        m = NotionFetchDataData(values=[], extra="dropped")
        assert not hasattr(m, "extra")


# ---------------------------------------------------------------------------
# sheets_tools
# ---------------------------------------------------------------------------
