"""Write the API's OpenAPI document to ``apps/api/openapi.json``.

The generated TypeScript types (``libs/shared/ts/src/api/generated``) are built
from this file, and CI fails when it drifts from the routes. Run through
``mise api:types``, which regenerates both.

Usage (from ``apps/api``)::

    uv run python scripts/export_openapi.py
"""

import json
import os
from pathlib import Path
import re
import sys

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))
# create_app() mounts app/static relative to the working directory.
os.chdir(API_ROOT)

import tests.offline_env  # noqa: F401 -- must run before any app import

from app.core.app_factory import create_app

OUTPUT = API_ROOT / "openapi.json"

# FastAPI names a colliding model by its module path (``app__models__x__Name``)
# instead of failing. Every consumer would then carry that path in a type name,
# so the export refuses the collision: rename one of the two models.
_MANGLED_NAME = re.compile(r"^app__")
_REF_PREFIX = "#/components/schemas/"


def _identifier(name: str) -> str:
    """The component name as a TypeScript/Python identifier.

    Pydantic suffixes a model used both as a request and a response with
    ``-Input``/``-Output``; the dash is the only non-identifier character a
    component name carries, and dropping it keeps the name readable.
    """
    return name.replace("-", "")


def _with_identifier_component_names(schema: dict) -> dict:
    """Rename every component schema (and every ``$ref`` to it) to an identifier."""
    schemas = schema["components"]["schemas"]
    mangled = sorted(name for name in schemas if _MANGLED_NAME.match(name))
    if mangled:
        raise SystemExit(
            "two API models share a class name, so FastAPI mangled them by module path;"
            " rename one of each pair so the generated type carries the class name:\n  "
            + "\n  ".join(mangled)
        )
    renames = {name: _identifier(name) for name in schemas if _identifier(name) != name}
    clashes = sorted(new for new in renames.values() if new in schemas)
    if clashes:
        raise SystemExit(f"identifier rename collides with an existing schema: {clashes}")
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


def main() -> None:
    schema = _with_identifier_component_names(create_app().openapi())
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    operations = sum(len(methods) for methods in schema["paths"].values())
    print(f"wrote {OUTPUT.relative_to(API_ROOT.parent.parent)}: {operations} operations")


if __name__ == "__main__":
    main()
