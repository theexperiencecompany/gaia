"""Write the API's OpenAPI document to apps/api/openapi.json.

The generated TypeScript types (libs/shared/ts/src/api/generated) are built
from this file, and CI fails when it drifts from the routes. Run through
mise api:types, which regenerates both.

Usage (from apps/api)::

    uv run python scripts/export_openapi.py
"""

import json
import os
from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))
# create_app() mounts app/static relative to the working directory.
os.chdir(API_ROOT)

import tests.offline_env  # noqa: F401 -- must run before any app import

# The document covers the whole API surface across deployment modes: under the
# offline default (ENV=development, AUTH_MODE=workos) the self-host routers
# (/setup, /auth) are unmounted and their shapes would be missing from the
# generated contract. Self-host mode mounts a strict superset — nothing
# workos-only unmounts — so exporting under it keeps every existing path
# byte-identical while adding the setup shapes.
os.environ["ENV"] = "selfhost"
os.environ["AUTH_MODE"] = "local"

from app.core.app_factory import create_app
from scripts.openapi_contract import assert_refs_resolve, with_identifier_component_names

OUTPUT = API_ROOT / "openapi.json"


def main() -> None:
    schema = with_identifier_component_names(create_app().openapi())
    assert_refs_resolve(schema)
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    operations = sum(len(methods) for methods in schema["paths"].values())
    print(f"wrote {OUTPUT.relative_to(API_ROOT.parent.parent)}: {operations} operations")


if __name__ == "__main__":
    main()
