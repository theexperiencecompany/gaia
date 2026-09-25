"""The JSON Schema keywords GAIA reads off one schema node."""

from typing import TypedDict

from pydantic import JsonValue


class JsonSchemaNode(TypedDict, total=False):
    """One node of a provider-supplied JSON Schema, by the keywords GAIA reads.

    Provider and observed schemas are never validated, so a keyword whose value
    varies by provider stays JsonValue and every read keeps its isinstance guard.
    """

    type: str | list[str]
    properties: dict[str, JsonValue]
    required: list[str]
    items: JsonValue
    anyOf: JsonValue
    oneOf: JsonValue
    enum: JsonValue
    additionalProperties: JsonValue
