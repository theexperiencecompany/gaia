"""``api_operation_id``: ``<slug(tag)>_<slug(name)>``, and nothing from the path."""

from enum import Enum

from fastapi.routing import APIRoute

from app.core.openapi import api_operation_id


class _Tag(Enum):
    TODO_ITEMS = "Todo Items"


async def _endpoint() -> None:
    return None


def _route(name: str, tags: list[str | Enum]) -> APIRoute:
    return APIRoute("/api/v1/some/{path}", _endpoint, name=name, tags=tags)


def test_enum_tags_contribute_their_value_not_their_repr() -> None:
    assert api_operation_id(_route("get_todos", [_Tag.TODO_ITEMS])) == "todo_items_get_todos"


def test_runs_of_non_alphanumerics_collapse_to_one_underscore_lowercased() -> None:
    route = _route("-List-Todos (v2)-", ["Todo  Items!"])
    assert api_operation_id(route) == "todo_items_list_todos_v2"


def test_only_the_first_tag_is_the_prefix() -> None:
    assert api_operation_id(_route("get_todos", ["Todos", "Beta"])) == "todos_get_todos"


def test_an_untagged_route_is_its_bare_name() -> None:
    assert api_operation_id(_route("metrics", [])) == "metrics"
