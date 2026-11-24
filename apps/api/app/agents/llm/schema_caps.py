"""The size caps a provider holding a reply to its schema enforces by cutting the reply short."""

from pydantic import JsonValue

#: A held string ends mid-sentence at maxLength, a held list at maxItems. Code checks them after.
_SIZE_CAPS = frozenset({"maxLength", "maxItems"})
#: Keywords whose keys are names the schema's author chose, each mapping to a subschema.
_NAMED_SUBSCHEMAS = frozenset({"properties", "patternProperties", "$defs", "definitions"})
#: Keywords whose value is data, never a schema.
_DATA = frozenset({"enum", "const", "default", "examples"})


def without_size_caps(schema: JsonValue) -> JsonValue:
    """Return the JSON schema without its size caps, so a held reply arrives whole and is checked."""
    if isinstance(schema, list):
        return [without_size_caps(node) for node in schema]
    if not isinstance(schema, dict):
        return schema
    stripped: dict[str, JsonValue] = {}
    for key, node in schema.items():
        if key in _SIZE_CAPS:
            continue
        if key in _DATA:
            stripped[key] = node
        elif key in _NAMED_SUBSCHEMAS and isinstance(node, dict):
            stripped[key] = {name: without_size_caps(sub) for name, sub in node.items()}
        else:
            stripped[key] = without_size_caps(node)
    return stripped
