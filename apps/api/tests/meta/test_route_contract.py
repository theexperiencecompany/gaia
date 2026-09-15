"""The API contract the generated TypeScript types are built from.

Three invariants keep ``apps/api/openapi.json`` (and everything generated from
it) trustworthy, and each of them silently rots without a test: a route that
declares no response model documents its body as ``{}``; a body typed ``Any``
or a bare ``dict`` generates ``unknown`` and every consumer casts; a
path-derived operation id renames a client type whenever a route moves; and a
route-level ``responses=`` (or a non-JSON response class) that shadows the
router's ``ERROR_RESPONSES`` documents an error with no body at all. This is
the ratchet — a new route that breaks any of them fails here, not in a
frontend type-check three PRs later.
"""

from collections import Counter
import dataclasses
import types
import typing
from typing import Any

from fastapi import FastAPI
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from pydantic import BaseModel
import pytest
from starlette import status
from starlette.responses import Response

from app.core.app_factory import create_app
from app.core.openapi import api_operation_id

_SCHEMA_REF_PREFIX = "#/components/schemas/"
_ENVELOPE_REF = f"{_SCHEMA_REF_PREFIX}ErrorEnvelope"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="module")
def routes(app: FastAPI) -> list[RouteContext]:
    return [
        ctx
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute) and ctx.original_route.include_in_schema
    ]


def _label(ctx: RouteContext) -> str:
    route = ctx.original_route
    assert isinstance(route, APIRoute)
    return f"{','.join(sorted(route.methods))} {ctx.path} ({route.name})"


def _returns_response_subclass(route: APIRoute) -> bool:
    annotation = typing.get_type_hints(route.endpoint).get("return")
    return isinstance(annotation, type) and issubclass(annotation, Response)


def _is_typed_body(model: Any) -> bool:
    origin = typing.get_origin(model)
    if origin in (list, set, tuple, frozenset):
        return all(_is_typed_body(arg) for arg in typing.get_args(model))
    if origin is dict:
        key, value = typing.get_args(model)
        return key is str and _is_typed_body(value)
    if origin in (types.UnionType, typing.Union):
        return all(arg is type(None) or _is_typed_body(arg) for arg in typing.get_args(model))
    if model is Any or model is object or model in (dict, list):
        return False
    if isinstance(model, type):
        return (
            issubclass(model, BaseModel)
            or dataclasses.is_dataclass(model)
            or model in (str, int, float, bool)
        )
    return False


def _declares_its_response_class(route: APIRoute) -> bool:
    """A stream/file/redirect/HTML route names its Response class on the decorator.

    Without ``response_class=`` FastAPI documents the body as an empty JSON
    object; a JSON response class is not an answer either — that body needs a
    model.
    """
    if isinstance(route.response_class, DefaultPlaceholder):
        return False
    return not issubclass(route.response_class, JSONResponse)


def test_every_route_declares_its_response_body(routes: list[RouteContext]) -> None:
    """A route without a response model documents its body as ``{}``."""
    undeclared = [
        _label(ctx)
        for ctx in routes
        if (route := ctx.original_route)
        and isinstance(route, APIRoute)
        and route.response_model is None
        and not (_returns_response_subclass(route) and _declares_its_response_class(route))
        and route.status_code != status.HTTP_204_NO_CONTENT
    ]
    assert undeclared == [], (
        "routes with no response model — annotate the return type with a Pydantic model; "
        "a stream/file/redirect/HTML route returns that Response subclass AND sets "
        "response_class= to it on the decorator:\n  " + "\n  ".join(undeclared)
    )


def test_no_route_body_is_any_or_a_bare_dict(routes: list[RouteContext]) -> None:
    """``Any`` and bare ``dict`` generate ``unknown``; every consumer then casts."""
    loose = [
        f"{_label(ctx)} -> {ctx.original_route.response_model}"
        for ctx in routes
        if isinstance(ctx.original_route, APIRoute)
        and ctx.original_route.response_model is not None
        and not _is_typed_body(ctx.original_route.response_model)
    ]
    assert loose == [], "routes whose body is untyped:\n  " + "\n  ".join(loose)


def test_every_documented_route_is_tagged(routes: list[RouteContext]) -> None:
    """The tag is the first half of the operation id; without it ids degrade to bare names."""
    untagged = [_label(ctx) for ctx in routes if not ctx.tags]
    assert untagged == [], "mount these routers with tags=[...]:\n  " + "\n  ".join(untagged)


def test_operation_ids_are_tag_and_name_not_path(routes: list[RouteContext]) -> None:
    """A path-derived id renames the generated client type whenever a route moves."""
    drifted = [
        f"{_label(ctx)}: {ctx.unique_id!r} != {api_operation_id(ctx)!r}"
        for ctx in routes
        if ctx.unique_id != api_operation_id(ctx)
    ]
    assert drifted == [], "operation ids not of the form <tag>_<name>:\n  " + "\n  ".join(drifted)


def test_operation_ids_are_unique(routes: list[RouteContext]) -> None:
    """Two routes sharing an id collapse into one generated type."""
    ids = Counter(ctx.unique_id for ctx in routes)
    duplicates = sorted(op_id for op_id, count in ids.items() if count > 1)
    assert duplicates == [], (
        f"duplicate operation ids (rename the handler or hide the alias path): {duplicates}"
    )


def _is_html_route(route: APIRoute) -> bool:
    return not isinstance(route.response_class, DefaultPlaceholder) and issubclass(
        route.response_class, HTMLResponse
    )


def _declared_body_refs(route: APIRoute) -> set[str]:
    """Component refs of the models the handler itself returns (a union covers a non-200 body)."""
    model = route.response_model
    members = (
        typing.get_args(model)
        if typing.get_origin(model) in (types.UnionType, typing.Union)
        else (model,)
    )
    return {
        f"{_SCHEMA_REF_PREFIX}{member.__name__}" for member in members if isinstance(member, type)
    }


def test_every_error_response_is_the_json_envelope(
    app: FastAPI, routes: list[RouteContext]
) -> None:
    """A route-level ``responses=`` entry documents its status with no body unless it
    names the envelope, and a ``text/html`` response class re-types the envelope as HTML."""
    schema = app.openapi()
    assert _ENVELOPE_REF[len(_SCHEMA_REF_PREFIX) :] in schema["components"]["schemas"]
    shadowed = []
    for ctx in routes:
        route = ctx.original_route
        assert isinstance(route, APIRoute)
        # health's 503 is DegradedHealthResponse: the handler's own return type,
        # set on the injected Response — a documented body, not a shadowed one.
        allowed_refs = _declared_body_refs(route) | {_ENVELOPE_REF}
        for method in route.methods:
            responses = schema["paths"][ctx.path_format][method.lower()]["responses"]
            for code, response in responses.items():
                # 3xx is a redirect route's own success status, not an error.
                if not code.startswith(("4", "5")):
                    continue
                content = response.get("content", {})
                ref = content.get("application/json", {}).get("schema", {}).get("$ref")
                if set(content) == {"application/json"} and ref in allowed_refs:
                    continue
                # An HTML page answers its own bad link with a page (or nothing),
                # not with an API error; every other status is the JSON envelope.
                if code == "400" and _is_html_route(route) and set(content) <= {"text/html"}:
                    continue
                shadowed.append(f"{method} {ctx.path} {code}: {content or 'no body'}")
    assert shadowed == [], (
        "4xx/5xx responses whose body is not the ErrorEnvelope — pass route-level "
        "descriptions through error_responses(), and give a text/html route "
        "HTML_ROUTE_ERROR_RESPONSES:\n  " + "\n  ".join(shadowed)
    )
