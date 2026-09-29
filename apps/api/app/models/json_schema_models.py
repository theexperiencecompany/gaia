"""The JSON Schema keywords GAIA reads off one schema node."""

from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field, JsonValue


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
    const: JsonValue
    description: JsonValue
    additionalProperties: JsonValue


class JsonSchemaRef(BaseModel):
    """A schema node's $ref pointer, a key no TypedDict field can name; any value is kept."""

    model_config = ConfigDict(extra="ignore")

    ref: JsonValue = Field(default=None, alias="$ref")
