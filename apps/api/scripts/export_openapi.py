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
import sys

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))
# create_app() mounts app/static relative to the working directory.
os.chdir(API_ROOT)

import tests.offline_env  # noqa: F401 -- must run before any app import

from app.core.app_factory import create_app

OUTPUT = API_ROOT / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    operations = sum(len(methods) for methods in schema["paths"].values())
    print(f"wrote {OUTPUT.relative_to(API_ROOT.parent.parent)}: {operations} operations")


if __name__ == "__main__":
    main()
