"""Stable OpenAPI operation ids: <router_tag>_<function_name>.

FastAPI's default id embeds the path (get_todos_api_v1_todos_get), so
moving a route renames every generated client type that hangs off it. The
tag and the handler name are what a reader already knows the operation by.
"""

from enum import Enum
import re
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema


def _slug(text: str | Enum) -> str:
    raw = text.value if isinstance(text, Enum) else text
    return "_".join(re.findall(r"[a-z0-9]+", str(raw).lower()))


def api_operation_id(route: APIRoute) -> str:
    """Operation id for route; the first tag is the router's, per include_router.

    An untagged route (only the hidden /metrics mount today) gets its bare
    name; tests/meta/test_route_contract.py requires a tag on every
    documented route so the id never degrades to that.
    """
    if not route.tags:
        return _slug(route.name)
    return f"{_slug(route.tags[0])}_{_slug(route.name)}"


class StreamFrameFastAPI(FastAPI):
    """FastAPI whose document also carries the SSE frame models no route returns.

    Clients then get generated types for stream frames like every other wire shape.
    A frame name that collides with a route component of another shape raises.
    """

    stream_frame_models: tuple[type[BaseModel], ...] = ()

    def openapi(self) -> dict[str, Any]:
        """Build the route document once, then add the frame models' schemas to it."""
        if self.openapi_schema:
            return self.openapi_schema
        schema = super().openapi()
        _, frames = models_json_schema(
            [(model, "serialization") for model in self.stream_frame_models],
            ref_template="#/components/schemas/{model}",
        )
        components: dict[str, Any] = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, body in frames.get("$defs", {}).items():
            if name in components and components[name] != body:
                raise ValueError(f"stream frame schema {name} collides with a route component")
            components[name] = body
        return schema
