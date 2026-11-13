"""The export's own guards: component names and the refs that point at them.

Every TypeScript type is imported under its component's name, so a name
pydantic built from a module path or a generic's type arguments renames a
client type when unrelated code moves; and a hand-written ref outlives the
model it names the moment pydantic splits that model into Input/Output,
leaving the body typed unknown with nothing failing.
"""

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi import FastAPI
import pytest
from scripts.openapi_contract import assert_refs_resolve, with_identifier_component_names

from app.schemas.errors import HTML_ROUTE_ERROR_RESPONSES

API_ROOT = Path(__file__).resolve().parents[2]

# Imports the guards in a fresh interpreter and reports whether the import touched os.environ.
_IMPORT_PROBE = """
import json, os
before = dict(os.environ)
import scripts.openapi_contract
after = dict(os.environ)
print(json.dumps({k: [before.get(k), after.get(k)] for k in set(before) | set(after)
                  if before.get(k) != after.get(k)}))
"""


def _document(schemas: dict[str, Any], paths: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"components": {"schemas": schemas}, "paths": paths or {}}


def test_every_ref_in_the_exported_document_resolves(app: FastAPI) -> None:
    """The document the TypeScript is generated from names only components it carries."""
    assert_refs_resolve(with_identifier_component_names(app.openapi()))


def test_a_dual_use_envelope_dangles_the_hand_written_ref() -> None:
    """A hand-written envelope ref dangles once the model splits into Input/Output."""
    document = _document(
        {"ErrorEnvelope-Input": {}, "ErrorEnvelope-Output": {}},
        {"/page": {"get": {"responses": dict(HTML_ROUTE_ERROR_RESPONSES)}}},
    )
    with pytest.raises(SystemExit, match="ErrorEnvelope"):
        assert_refs_resolve(with_identifier_component_names(document))


def test_a_generic_parameterisation_is_refused() -> None:
    """Model[dict[str, Any]] exports as Model_dict_str__Any__ — a name, not a type."""
    with pytest.raises(SystemExit, match="NotificationResponse_dict_str__Any__"):
        with_identifier_component_names(_document({"NotificationResponse_dict_str__Any__": {}}))


def test_a_module_path_mangled_name_is_refused() -> None:
    """Two models sharing a class name: FastAPI mangles both by module path."""
    with pytest.raises(SystemExit, match="app__models__todo__Todo"):
        with_identifier_component_names(_document({"app__models__todo__Todo": {}}))


def test_two_renames_landing_on_one_name_are_refused() -> None:
    """The dash is dropped, so two components can rename onto each other."""
    with pytest.raises(SystemExit, match="FooBar"):
        with_identifier_component_names(_document({"Foo-Bar": {}, "FooBar-": {}}))


def test_a_rename_onto_an_existing_component_is_refused() -> None:
    """The survivor would silently take the other component's body."""
    with pytest.raises(SystemExit, match="FooBar"):
        with_identifier_component_names(_document({"Foo-Bar": {}, "FooBar": {}}))


def test_renaming_rewrites_every_ref_to_the_renamed_component() -> None:
    """The rename is only safe if the refs move with it."""
    renamed = with_identifier_component_names(
        _document(
            {"Todo-Input": {}},
            {"/todos": {"post": {"requestBody": {"$ref": "#/components/schemas/Todo-Input"}}}},
        )
    )
    assert set(renamed["components"]["schemas"]) == {"TodoInput"}
    assert renamed["paths"]["/todos"]["post"]["requestBody"]["$ref"] == (
        "#/components/schemas/TodoInput"
    )
    assert_refs_resolve(renamed)


def test_importing_the_guards_leaves_the_environment_alone() -> None:
    """Regression: the export selected self-host in os.environ at import, flipping later tests to it."""
    probe = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(probe.stdout.splitlines()[-1]) == {}
