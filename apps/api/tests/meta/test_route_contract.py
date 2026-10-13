"""The API contract the generated TypeScript types are built from.

A handful of invariants keep apps/api/openapi.json (and everything generated
from it) trustworthy, and each of them silently rots without a test: a route
that declares no response model documents its body as {}; a body typed Any or
a bare dict generates unknown and every consumer casts; a path-derived
operation id renames a client type whenever a route moves, and a shared id
collapses two routes into one type; a serializer option drops a field the
schema marks required; and a route-level responses= (or a non-JSON response
class) that shadows the router's ERROR_RESPONSES documents an error with no
body at all. This is the ratchet — a new route that breaks any of them fails
here, not in a frontend type-check three PRs later.
"""

from collections import Counter
import types
import typing

from fastapi import APIRouter, FastAPI
from fastapi.datastructures import DefaultPlaceholder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts
from starlette import status
from starlette.responses import Response

from app.core.openapi import api_operation_id
from app.schemas.common import ResponseModel
from tests.meta.response_types import walk_response

_SCHEMA_REF_PREFIX = "#/components/schemas/"
_ENVELOPE_REF = f"{_SCHEMA_REF_PREFIX}ErrorEnvelope"
_DEFAULTS_REQUIRED = "json_schema_serialization_defaults_required"
_OMITTING_OPTIONS = ("response_model_exclude_none", "response_model_exclude_unset")


def _label(ctx: RouteContext) -> str:
    route = ctx.original_route
    assert isinstance(route, APIRoute)
    return f"{','.join(sorted(route.methods))} {ctx.path} ({route.name})"


def _returns_response_subclass(route: APIRoute) -> bool:
    annotation = typing.get_type_hints(route.endpoint).get("return")
    return isinstance(annotation, type) and issubclass(annotation, Response)


def _declares_its_response_class(route: APIRoute) -> bool:
    """Check that a stream/file/redirect/HTML route names its Response class on the decorator, else FastAPI documents an empty JSON body."""
    if isinstance(route.response_class, DefaultPlaceholder):
        return False
    return not issubclass(route.response_class, JSONResponse)


def test_every_route_declares_its_response_body(routes: list[RouteContext]) -> None:
    """A route without a response model documents its body as {}."""
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
    """Any and bare dict generate unknown; every consumer then casts."""
    loose = [
        f"{_label(ctx)} -> {ctx.original_route.response_model}"
        for ctx in routes
        if isinstance(ctx.original_route, APIRoute)
        and ctx.original_route.response_model is not None
        and _label(ctx) in walk_response(ctx.original_route.response_model, _label(ctx)).untyped
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


def test_operation_ids_are_unique(all_routes: list[RouteContext]) -> None:
    """Two routes sharing an id collapse into one generated type, hidden alias included."""
    ids = Counter(ctx.unique_id for ctx in all_routes)
    duplicates = sorted(op_id for op_id, count in ids.items() if count > 1)
    assert duplicates == [], (
        "duplicate operation ids — give the alias route its own operation_id= "
        f"(the id is <tag>_<handler name>, so stacked decorators all share one): {duplicates}"
    )


def test_no_route_overrides_its_router_tag(routes: list[RouteContext]) -> None:
    """A second tag moves the route in the docs while the id keeps the router's first tag."""
    overridden = [
        f"{_label(ctx)} -> {list(ctx.tags)}" for ctx in routes if set(ctx.tags) != {ctx.tags[0]}
    ]
    assert overridden == [], (
        "routes carrying a tag their router did not give them — move the route to a router "
        "mounted with that tag:\n  " + "\n  ".join(overridden)
    )


def _omitting_options(route: APIRoute) -> list[str]:
    return [option for option in _OMITTING_OPTIONS if getattr(route, option, False)]


def test_no_route_omits_fields_its_schema_marks_required(routes: list[RouteContext]) -> None:
    """Omitting a field ResponseModel marks required promises a key the response lacks."""
    lying = []
    for ctx in routes:
        route = ctx.original_route
        assert isinstance(route, APIRoute)
        options = _omitting_options(route)
        if not options or route.response_model is None:
            continue
        forced = sorted(
            model.__name__
            for model in walk_response(route.response_model, _label(ctx)).models
            if model.model_config.get(_DEFAULTS_REQUIRED)
        )
        if forced:
            lying.append(f"{_label(ctx)}: {', '.join(options)} over {', '.join(forced)}")
    assert lying == [], (
        "routes that omit fields their own schema marks required — drop the option, or stop "
        f"deriving the model from ResponseModel ({_DEFAULTS_REQUIRED}):\n  " + "\n  ".join(lying)
    )


async def _probe() -> ResponseModel:
    return ResponseModel()


def test_two_routers_under_one_tag_share_an_id_namespace(all_routes: list[RouteContext]) -> None:
    """The id is <tag>_<handler> with the module left out, so same-named handlers collide."""
    modules = {
        ctx.original_route.endpoint.__module__
        for ctx in all_routes
        if ctx.tags and str(ctx.tags[0]) == "MCP"
    }
    assert len(modules) > 1, f"the MCP routers merged; re-pin this on the survivor: {modules}"

    app = FastAPI(generate_unique_id_function=api_operation_id)
    for _ in modules:
        router = APIRouter()
        router.add_api_route("/probe", _probe, methods=["GET"], name="list_tools")
        app.include_router(router, tags=["MCP"])
    ids = [
        ctx.unique_id
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.original_route, APIRoute)
    ]
    assert ids == ["mcp_list_tools"] * len(modules), (
        f"two MCP routers no longer share an id namespace: {ids}"
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
    """Every non-2xx response is documented as the JSON envelope, or re-typed to HTML by a text/html response class."""
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
