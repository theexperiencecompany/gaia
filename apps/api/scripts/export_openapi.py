"""Write the API's OpenAPI document to apps/api/openapi.json.

The generated TypeScript types (libs/shared/ts/src/api/generated) are built
from this file, and CI fails when it drifts from the routes. Run through
mise api:types, which regenerates both.

Usage (from apps/api)::

    uv run python scripts/export_openapi.py
"""

from collections import Counter
from collections.abc import Iterator
import json
import os
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))
# create_app() mounts app/static relative to the working directory.
os.chdir(API_ROOT)

import tests.offline_env  # noqa: F401 -- must run before any app import

from app.core.app_factory import create_app

OUTPUT = API_ROOT / "openapi.json"

# A generated name carries ``__`` only when pydantic built it from something
# other than the class name: a module path for two models sharing one name
# (``app__models__x__Name``), or the type arguments of a parameterised generic
# (``NotificationResponse_dict_str__Any__``). Both rename the TypeScript type
# when an unrelated model moves or a type argument changes, so the export
# refuses them: give the shape its own named model.
_MANGLED_MARKER = "__"
_REF_PREFIX = "#/components/schemas/"


def _identifier(name: str) -> str:
    """Return the component name as a TypeScript/Python identifier.

    Pydantic suffixes a model used both as a request and a response with
    -Input/-Output; the dash is the only non-identifier character a
    component name carries, and dropping it keeps the name readable.
    """
    return name.replace("-", "")


def _with_identifier_component_names(schema: dict) -> dict:
    """Rename every component schema (and every $ref to it) to an identifier."""
    schemas = schema["components"]["schemas"]
    mangled = sorted(name for name in schemas if _MANGLED_MARKER in name)
    if mangled:
        raise SystemExit(
            "component names pydantic built from a module path (two models sharing a class"
            " name) or from a generic's type arguments; both drift when unrelated code moves."
            " Give each one its own named model:\n  " + "\n  ".join(mangled)
        )
    renames = {name: _identifier(name) for name in schemas if _identifier(name) != name}
    # Two renames can also land on one name (``A-Input`` and ``A-` + `Input``),
    # which would silently drop one component, so the count matters too.
    taken = Counter(renames.values())
    clashes = sorted({new for new in renames.values() if new in schemas or taken[new] > 1})
    if clashes:
        raise SystemExit(
            "the Input/Output rename collides with another component; rename one of the"
            f" models so both keep a name of their own: {clashes}"
        )
    if not renames:
        return schema

    def rename_refs(node: object) -> object:
        if isinstance(node, dict):
            if (ref := node.get("$ref")) and ref.startswith(_REF_PREFIX):
                node["$ref"] = _REF_PREFIX + renames.get(
                    ref[len(_REF_PREFIX) :], ref[len(_REF_PREFIX) :]
                )
            return {key: rename_refs(value) for key, value in node.items()}
        if isinstance(node, list):
            return [rename_refs(item) for item in node]
        return node

    renamed = rename_refs(schema)
    assert isinstance(renamed, dict)
    renamed["components"]["schemas"] = {
        renames.get(name, name): body for name, body in renamed["components"]["schemas"].items()
    }
    return renamed


def _iter_refs(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref
        for value in node.values():
            yield from _iter_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


def assert_refs_resolve(schema: dict) -> None:
    """Every ``$ref`` in the document names a component that exists.

    A hand-written ref (``ERROR_RESPONSES``' envelope) keeps pointing at a name
    pydantic is free to rename — a model that becomes both a request and a
    response body exports as ``NameInput``/``NameOutput`` — and the generated
    TypeScript then silently types that body as ``unknown``.
    """
    schemas = schema.get("components", {}).get("schemas", {})
    dangling = sorted(
        {
            ref
            for ref in _iter_refs(schema)
            if not ref.startswith(_REF_PREFIX) or ref[len(_REF_PREFIX) :] not in schemas
        }
    )
    if dangling:
        raise SystemExit(
            "the document references components that do not exist; a hand-written $ref"
            " outlived the model it names:\n  " + "\n  ".join(dangling)
        )


def main() -> None:
    schema = _with_identifier_component_names(create_app().openapi())
    assert_refs_resolve(schema)
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    operations = sum(len(methods) for methods in schema["paths"].values())
    print(f"wrote {OUTPUT.relative_to(API_ROOT.parent.parent)}: {operations} operations")


if __name__ == "__main__":
    main()
