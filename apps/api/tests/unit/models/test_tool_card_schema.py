"""The OpenAPI rewrite that publishes ToolDataEntry as one typed member per tool card."""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel
import pytest

from app.models import tool_card_schema
from app.models.tool_card_schema import with_tool_card_schemas

_REF = "#/components/schemas/"
_DESCRIPTION = "A tool's card."


class Pin(BaseModel):
    label: str


class Board(BaseModel):
    pins: list[Pin]
    shade: Literal["red", "blue"]
    tag: Pin | None = None


class PinDataCard(BaseModel):
    """A payload model named like the pin_data tool's own entry."""

    label: str


_PIN_OUTPUT: dict[str, Any] = {
    "title": "Pin",
    "type": "object",
    "properties": {"label": {"type": "string", "title": "Label"}},
    "required": ["label"],
}
_BOARD: dict[str, Any] = {
    "properties": {
        "pins": {"items": {"$ref": f"{_REF}Pin-Output"}, "title": "Pins", "type": "array"},
        "shade": {"enum": ["red", "blue"], "title": "Shade", "type": "string"},
        "tag": {"anyOf": [{"$ref": f"{_REF}Pin-Output"}, {"type": "null"}], "default": None},
    },
    "required": ["pins", "shade"],
    "title": "Board",
    "type": "object",
}
_ENVELOPE_PROPERTIES: dict[str, Any] = {
    "tool_name": {"type": "string"},
    "data": {},
    "at": {"type": "string"},
}


@pytest.fixture(autouse=True)
def two_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register a grouped card whose model a route already renders, and a list card of a fresh model."""
    monkeypatch.setattr(
        tool_card_schema, "TOOL_CARDS", {"pin_data": Pin, "board_list_data": list[Board]}
    )
    monkeypatch.setattr(tool_card_schema, "GROUPED_TOOL_CARDS", frozenset({"pin_data"}))


def _document(**extra: Any) -> dict[str, Any]:
    return {
        "components": {
            "schemas": {
                "ToolDataEntry": {
                    "title": "ToolDataEntry",
                    "description": _DESCRIPTION,
                    "type": "object",
                    "properties": deepcopy(_ENVELOPE_PROPERTIES),
                    "required": ["tool_name", "data"],
                },
                "TimelineCard": {
                    "type": "object",
                    "properties": {"card": {"$ref": f"{_REF}ToolDataEntry"}, "id": {}},
                },
                "Pin-Output": deepcopy(_PIN_OUTPUT),
                **extra,
            }
        },
        "paths": {},
    }


def _card(title: str, tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": title,
        "description": _DESCRIPTION,
        "type": "object",
        "properties": {
            **_ENVELOPE_PROPERTIES,
            "tool_name": {"const": tool_name, "type": "string"},
            "data": data,
        },
        "required": ["tool_name", "data"],
    }


def _union(description: str, members: dict[str, str]) -> dict[str, Any]:
    return {
        "description": description,
        "oneOf": [{"$ref": _REF + name} for name in members.values()],
        "discriminator": {
            "propertyName": "tool_name",
            "mapping": {tool: _REF + name for tool, name in members.items()},
        },
    }


def _published_schemas(document: dict[str, Any]) -> dict[str, Any]:
    components = with_tool_card_schemas(document)["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    return schemas


def _exit_message(document: dict[str, Any]) -> object:
    with pytest.raises(SystemExit) as raised:
        with_tool_card_schemas(document)
    return raised.value.code


def test_each_card_is_published_as_its_own_member_and_a_grouped_card_as_a_list() -> None:
    document = _document()
    pin = {"$ref": f"{_REF}Pin-Output"}
    board_list = {"type": "array", "items": {"$ref": f"{_REF}Board"}}

    published = with_tool_card_schemas(document)

    assert published == {
        "components": {
            "schemas": {
                "ToolDataEntry": _union(
                    _DESCRIPTION,
                    {"pin_data": "PinDataCard", "board_list_data": "BoardListDataCard"},
                ),
                "TimelineCard": {
                    "type": "object",
                    "properties": {"card": {"$ref": f"{_REF}TimelineToolCard"}, "id": {}},
                },
                "Pin-Output": _PIN_OUTPUT,
                "Board": _BOARD,
                "ToolCardEnvelope": {
                    **document["components"]["schemas"]["ToolDataEntry"],
                    "title": "ToolCardEnvelope",
                },
                "PinDataCard": _card("PinDataCard", "pin_data", pin),
                "PinDataGroupCard": _card(
                    "PinDataGroupCard", "pin_data", {"type": "array", "items": pin}
                ),
                "BoardListDataCard": _card("BoardListDataCard", "board_list_data", board_list),
                "TimelineToolCard": _union(
                    "A card shown below the thread; a grouped tool's card holds every call's data.",
                    {"pin_data": "PinDataGroupCard", "board_list_data": "BoardListDataCard"},
                ),
            }
        },
        "paths": {},
    }
    assert document == _document()


def test_no_two_published_cards_share_a_mutable_part() -> None:
    schemas = _published_schemas(_document())

    schemas["PinDataCard"]["required"].append("extra")
    schemas["PinDataCard"]["properties"]["at"]["format"] = "date-time"

    for name in ("PinDataGroupCard", "BoardListDataCard", "ToolCardEnvelope"):
        assert schemas[name]["required"] == ["tool_name", "data"]
        assert schemas[name]["properties"]["at"] == {"type": "string"}


def test_a_model_a_route_already_publishes_keeps_the_routes_rendering() -> None:
    board = {**deepcopy(_BOARD), "description": "The route's own rendering."}
    board["properties"] = dict(reversed(board["properties"].items()))
    board["required"] = ["shade", "pins"]

    schemas = _published_schemas(_document(Board=board))

    assert schemas["Board"] == board


def test_an_envelope_without_a_description_publishes_an_empty_one() -> None:
    document = _document()
    del document["components"]["schemas"]["ToolDataEntry"]["description"]

    schemas = _published_schemas(document)

    assert schemas["ToolDataEntry"]["description"] == ""


@pytest.mark.parametrize(
    "board",
    [
        pytest.param(True, id="not-an-object"),
        pytest.param({**_BOARD, "title": "Plank"}, id="title"),
        pytest.param({**_BOARD, "properties": {"pins": {}}}, id="properties"),
        pytest.param({**_BOARD, "properties": []}, id="properties-not-an-object"),
        pytest.param({**_BOARD, "required": ["pins"]}, id="required"),
        pytest.param({**_BOARD, "required": "pins"}, id="required-not-a-list"),
        pytest.param({**_BOARD, "enum": ["red"]}, id="enum"),
    ],
)
def test_a_payload_model_sharing_a_name_with_another_shape_fails_the_export(board: object) -> None:
    assert _exit_message(_document(Board=board)) == (
        "a tool card's payload model publishes a schema another model already owns under the"
        " same name; give it its own name: ['Board']"
    )


def test_a_rendering_under_the_output_name_is_compared_too() -> None:
    document = _document()
    document["components"]["schemas"]["Pin-Output"]["required"] = []

    assert _exit_message(document) == (
        "a tool card's payload model publishes a schema another model already owns under the"
        " same name; give it its own name: ['Pin']"
    )


@pytest.mark.parametrize(
    "entry_name", ["PinDataCard", "PinDataGroupCard", "BoardListDataGroupCard"]
)
def test_a_component_under_a_cards_entry_name_fails_the_export(entry_name: str) -> None:
    assert _exit_message(_document(**{entry_name: {}})) == (
        f"a model is published under a tool card's own entry name; rename the model: ['{entry_name}']"
    )


def test_a_payload_model_under_a_cards_entry_name_fails_the_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tool_card_schema, "TOOL_CARDS", {"pin_data": Pin, "board_list_data": list[PinDataCard]}
    )

    assert _exit_message(_document()) == (
        "a model is published under a tool card's own entry name; rename the model: ['PinDataCard']"
    )


def test_a_document_without_component_schemas_fails_the_export() -> None:
    assert _exit_message({"components": {"schemas": []}}) == (
        "the OpenAPI document has no components.schemas"
    )
    assert _exit_message({"components": []}) == "the OpenAPI document has no components.schemas"


def test_an_envelope_that_is_not_an_object_fails_the_export() -> None:
    assert _exit_message(_document(ToolDataEntry=True)) == "ToolDataEntry is not an object schema"


@pytest.mark.parametrize("key", ["properties", "required"])
def test_an_envelope_without_its_fields_fails_the_export(key: str) -> None:
    document = _document()
    document["components"]["schemas"]["ToolDataEntry"][key] = None

    assert _exit_message(document) == (
        "ToolDataEntry has no properties/required to build cards from"
    )


def test_a_timeline_card_without_properties_fails_the_export() -> None:
    assert _exit_message(_document(TimelineCard={"properties": []})) == (
        "TimelineCard has no properties"
    )
    assert _exit_message(_document(TimelineCard=True)) == "TimelineCard has no properties"
