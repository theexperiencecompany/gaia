"""Publish ToolDataEntry in the OpenAPI document as the discriminated union of every tool's card.

The stored and streamed entry is read as JSON (its data is the tool's payload, dumped where the
tool built it), so the runtime type stays the shared ToolDataEntry; the document is where clients
learn each tool's data. A timeline card of a grouped tool holds every call's data as a list.
"""

from copy import deepcopy

from pydantic import JsonValue, TypeAdapter
from pydantic.json_schema import GenerateJsonSchema

from app.constants.chat import GROUPED_TOOL_CARDS
from app.models.tool_card_registry import TOOL_CARDS

_REF_PREFIX = "#/components/schemas/"
_ENTRY_SCHEMA = "ToolDataEntry"
_TIMELINE_CARD_SCHEMA = "TimelineCard"
_TIMELINE_ENTRY_SCHEMA = "TimelineToolCard"
# The entry as it is read back: any tool name, data unchecked; a stored card may predate its model.
_ENVELOPE_SCHEMA = "ToolCardEnvelope"
_DISCRIMINATOR = "tool_name"
# FastAPI's name for the response rendering of a model it renders both ways.
_OUTPUT_SUFFIX = "-Output"

_Schema = dict[str, JsonValue]


def _schema_name(tool_name: str, suffix: str) -> str:
    return "".join(part.capitalize() for part in tool_name.split("_")) + suffix


def _list_of(schema: JsonValue) -> _Schema:
    return {"type": "array", "items": schema}


def _entry(envelope: _Schema, tool_name: str, title: str, data: JsonValue) -> _Schema:
    """One card: the shared envelope with tool_name fixed and data typed."""
    properties = envelope["properties"]
    required = envelope["required"]
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise SystemExit(f"{_ENTRY_SCHEMA} has no properties/required to build cards from")
    return {
        **deepcopy(envelope),
        "title": title,
        "properties": {
            **deepcopy(properties),
            _DISCRIMINATOR: {"const": tool_name, "type": "string"},
            "data": data,
        },
    }


def _union(members: dict[str, str], description: str) -> _Schema:
    refs: list[JsonValue] = [{"$ref": _REF_PREFIX + name} for name in members.values()]
    mapping: dict[str, JsonValue] = {tool: _REF_PREFIX + name for tool, name in members.items()}
    return {
        "description": description,
        "oneOf": refs,
        "discriminator": {"propertyName": _DISCRIMINATOR, "mapping": mapping},
    }


def _shape(schema: JsonValue) -> tuple[object, ...]:
    """What makes two renderings of a schema the same model: its title, keys and required keys."""
    if not isinstance(schema, dict):
        return (schema,)
    properties = schema.get("properties")
    required = schema.get("required")
    return (
        schema.get("title"),
        sorted(properties) if isinstance(properties, dict) else None,
        sorted(map(str, required)) if isinstance(required, list) else None,
        schema.get("enum"),
    )


def _published_name(schemas: dict[str, JsonValue], name: str) -> str:
    output = f"{name}{_OUTPUT_SUFFIX}"
    return output if name not in schemas and output in schemas else name


def _renamed(node: JsonValue, names: dict[str, str]) -> JsonValue:
    """Point every $ref at the name its model is published under."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            name = ref.removeprefix(_REF_PREFIX)
            return {**node, "$ref": _REF_PREFIX + names.get(name, name)}
        return {key: _renamed(value, names) for key, value in node.items()}
    if isinstance(node, list):
        return [_renamed(item, names) for item in node]
    return node


def _payload_schemas() -> tuple[dict[str, JsonValue], _Schema]:
    """Each tool's data schema, and the payload models' definitions they reference."""
    generator = GenerateJsonSchema(ref_template=_REF_PREFIX + "{model}")
    data, defs = generator.generate_definitions(
        [
            (tool_name, "serialization", TypeAdapter(data).core_schema)
            for tool_name, data in TOOL_CARDS.items()
        ]
    )
    return (
        {tool_name: schema for (tool_name, _), schema in data.items()},
        {str(name): body for name, body in defs.items()},
    )


def with_tool_card_schemas(document: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Return a copy of the document with ToolDataEntry and TimelineCard.card typed per tool."""
    document = deepcopy(document)
    components = document["components"]
    if not isinstance(components, dict) or not isinstance(schemas := components["schemas"], dict):
        raise SystemExit("the OpenAPI document has no components.schemas")
    data, defs = _payload_schemas()
    # A model a route already publishes keeps the route's rendering, under its output name.
    names = {name: _published_name(schemas, name) for name in defs}
    clashes = sorted(
        name
        for name, published in names.items()
        if published in schemas and _shape(schemas[published]) != _shape(defs[name])
    )
    if clashes:
        raise SystemExit(
            "a tool card's payload model publishes a schema another model already owns under the"
            f" same name; give it its own name: {clashes}"
        )
    taken = sorted(
        name
        for tool_name in data
        for name in (_schema_name(tool_name, "Card"), _schema_name(tool_name, "GroupCard"))
        if name in schemas or name in names.values()
    )
    if taken:
        raise SystemExit(
            f"a model is published under a tool card's own entry name; rename the model: {taken}"
        )
    data = {tool: _renamed(value, names) for tool, value in data.items()}
    schemas.update(
        {name: _renamed(body, names) for name, body in defs.items() if names[name] not in schemas}
    )

    envelope = schemas[_ENTRY_SCHEMA]
    if not isinstance(envelope, dict):
        raise SystemExit(f"{_ENTRY_SCHEMA} is not an object schema")
    schemas[_ENVELOPE_SCHEMA] = {**deepcopy(envelope), "title": _ENVELOPE_SCHEMA}
    entries: dict[str, str] = {}
    shown: dict[str, str] = {}
    for tool_name, tool_data in data.items():
        entries[tool_name] = _schema_name(tool_name, "Card")
        schemas[entries[tool_name]] = _entry(envelope, tool_name, entries[tool_name], tool_data)
        shown[tool_name] = entries[tool_name]
        if tool_name in GROUPED_TOOL_CARDS:
            shown[tool_name] = _schema_name(tool_name, "GroupCard")
            schemas[shown[tool_name]] = _entry(
                envelope, tool_name, shown[tool_name], _list_of(tool_data)
            )

    description = envelope.get("description")
    schemas[_ENTRY_SCHEMA] = _union(entries, description if isinstance(description, str) else "")
    schemas[_TIMELINE_ENTRY_SCHEMA] = _union(
        shown, "A card shown below the thread; a grouped tool's card holds every call's data."
    )
    timeline_card = schemas[_TIMELINE_CARD_SCHEMA]
    if not isinstance(timeline_card, dict) or not isinstance(
        properties := timeline_card["properties"], dict
    ):
        raise SystemExit(f"{_TIMELINE_CARD_SCHEMA} has no properties")
    properties["card"] = {"$ref": _REF_PREFIX + _TIMELINE_ENTRY_SCHEMA}
    return document
