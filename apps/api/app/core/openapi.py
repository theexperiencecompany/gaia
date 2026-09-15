"""Stable OpenAPI operation ids: ``<router_tag>_<function_name>``.

FastAPI's default id embeds the path (``get_todos_api_v1_todos_get``), so
moving a route renames every generated client type that hangs off it. The
tag and the handler name are what a reader already knows the operation by.
"""

from enum import Enum
import re

from fastapi.routing import APIRoute


def _slug(text: str | Enum) -> str:
    raw = text.value if isinstance(text, Enum) else text
    return "_".join(re.findall(r"[a-z0-9]+", str(raw).lower()))


def api_operation_id(route: APIRoute) -> str:
    """Operation id for ``route``; the first tag is the router's, per ``include_router``.

    An untagged route (only the hidden ``/metrics`` mount today) gets its bare
    name; ``tests/meta/test_route_contract.py`` requires a tag on every
    documented route so the id never degrades to that.
    """
    if not route.tags:
        return _slug(route.name)
    return f"{_slug(route.tags[0])}_{_slug(route.name)}"
