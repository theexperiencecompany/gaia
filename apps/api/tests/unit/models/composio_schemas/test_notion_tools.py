"""Unit tests for ``app.models.composio_schemas.notion_tools`` — NOTION_FETCH_DATA output."""

from app.models.composio_schemas.notion_tools import (
    NotionFetchDataData,
    NotionFetchDataInput,
    NotionItem,
)


def test_fetch_data_input_parses_query_and_page_size() -> None:
    inp = NotionFetchDataInput.model_validate(
        {"fetch_type": "pages", "query": "quarterly", "page_size": 25}
    )
    assert inp.fetch_type == "pages"
    assert inp.query == "quarterly"
    assert inp.page_size == 25


def test_fetch_data_input_defaults() -> None:
    inp = NotionFetchDataInput.model_validate({"fetch_type": "all"})
    assert inp.query is None
    assert inp.page_size == 100


def test_item_parses_and_ignores_extra_fields() -> None:
    item = NotionItem.model_validate({"id": "p1", "title": "Plan", "type": "page", "extra": 1})
    assert item.id == "p1"
    assert item.title == "Plan"
    assert item.type == "page"
    assert item.url is None


def test_get_items_parses_each_value_dict() -> None:
    data = NotionFetchDataData.model_validate(
        {"values": [{"id": "p1", "title": "A"}, {"id": "p2", "type": "database"}]}
    )
    items = data.get_items()
    assert [item.id for item in items] == ["p1", "p2"]
    assert items[1].title is None
    assert items[1].type == "database"


def test_get_items_defaults_to_empty_list() -> None:
    assert NotionFetchDataData.model_validate({}).get_items() == []


def test_get_items_skips_non_dict_values() -> None:
    """``values`` is mutable post-construction (validate_assignment is off),
    so the isinstance guard in get_items is a real defensive filter."""
    data = NotionFetchDataData.model_validate({"values": [{"id": "p1"}]})
    data.values.insert(0, "not-a-dict")
    items = data.get_items()
    assert [item.id for item in items] == ["p1"]
