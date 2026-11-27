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

from app.constants.chat import GROUPED_TOOL_CARDS
from app.models.tool_card_registry import TOOL_CARDS
from app.models.tool_card_schema import with_tool_card_schemas
from app.schemas.errors import NON_JSON_ROUTE_ERROR_RESPONSES

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
        {"/page": {"get": {"responses": dict(NON_JSON_ROUTE_ERROR_RESPONSES)}}},
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


_REF_PREFIX = "#/components/schemas/"


def _published(app: FastAPI) -> dict[str, Any]:
    schemas: dict[str, Any] = with_identifier_component_names(
        with_tool_card_schemas(app.openapi())
    )["components"]["schemas"]
    return schemas


def _member(schemas: dict[str, Any], union: str, tool_name: str) -> dict[str, Any]:
    ref: str = schemas[union]["discriminator"]["mapping"][tool_name]
    member: dict[str, Any] = schemas[ref.removeprefix(_REF_PREFIX)]
    return member


def test_every_registered_tool_card_is_a_member_of_the_published_entry(app: FastAPI) -> None:
    """A client narrows a ToolDataEntry by tool_name to the data its tool's payload model sends."""
    schemas = _published(app)
    assert set(schemas["ToolDataEntry"]["discriminator"]["mapping"]) == set(TOOL_CARDS)
    for tool_name in TOOL_CARDS:
        card = _member(schemas, "ToolDataEntry", tool_name)
        assert card["properties"]["tool_name"] == {"const": tool_name, "type": "string"}
        assert card["properties"]["data"]


def test_a_timeline_card_of_a_grouped_tool_holds_every_calls_data(app: FastAPI) -> None:
    """The timeline folds a grouped tool's calls into one card whose data lists each call's."""
    schemas = _published(app)
    assert schemas["TimelineCard"]["properties"]["card"] == {
        "$ref": _REF_PREFIX + "TimelineToolCard"
    }
    for tool_name in TOOL_CARDS:
        shown = _member(schemas, "TimelineToolCard", tool_name)["properties"]["data"]
        entry = _member(schemas, "ToolDataEntry", tool_name)["properties"]["data"]
        grouped = tool_name in GROUPED_TOOL_CARDS
        assert shown == ({"type": "array", "items": entry} if grouped else entry)


def test_a_payload_model_named_like_another_model_fails_the_export() -> None:
    """Two shapes under one component name would type one tool's card as another model."""
    document = _document({"TodoCardData": {"title": "TodoCardData", "properties": {"other": {}}}})
    with pytest.raises(SystemExit, match="TodoCardData"):
        with_tool_card_schemas(document)
