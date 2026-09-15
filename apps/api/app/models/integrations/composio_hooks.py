"""What Composio hands the hook system, typed.

Composio's SDK describes its hook boundary with TypedDicts (ToolExecuteParams,
ToolExecutionResponse) and a tool's input schema as a raw JSON-schema dict
(Tool.input_parameters). These models are where those are parsed, once, so
every hook reads attributes instead of guessing keys.
"""

from collections.abc import Callable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)


class ComposioToolCall(BaseModel):
    """The keys of ``ToolExecuteParams`` the hooks read.

    ``arguments`` is a shallow copy of the SDK's bag (Pydantic rebuilds the dict;
    the values are the SDK's own objects), so a hook that edits it writes it back
    with ``params["arguments"] = call.arguments``. Values stay ``object``: the tool
    schema, not GAIA, validates them, and the agent path delivers Composio's
    schema-generated Pydantic models among them.
    """

    model_config = ConfigDict(extra="ignore")

    arguments: dict[str, object] = Field(default_factory=dict)
    user_id: str | None = None


class ComposioToolResponse(BaseModel):
    """Composio's ``{data, error, successful}`` execution envelope.

    ``data`` is kept exactly as the SDK handed it over: the SDK types it as a
    dict, but it has been observed as a list (Reddit comment listings) and as a
    bare string (attachment error paths), and every hook passes the raw value
    through unprocessed on its failure paths.
    """

    model_config = ConfigDict(extra="ignore")

    data: object
    error: str | None = None
    successful: bool = True


class RunMetadata(BaseModel):
    """The LangGraph run ``metadata`` the tool wrapper forwards; ``user_id`` names the caller."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None


class RunnableConfigTransport(BaseModel):
    """``__runnable_config__``: the slice of a ``RunnableConfig`` that
    ``langchain_composio_service`` tucks into a tool call's arguments so the hooks
    learn the calling user. Our transport, never a tool argument."""

    model_config = ConfigDict(extra="ignore")

    metadata: RunMetadata | None = None


class JsonSchemaNode(BaseModel):
    """One node of a tool's input JSON schema: the keys the hooks read or set.

    ``extra="allow"``: a modifier writes the node back onto ``Tool.input_parameters``
    after editing it, so every key the provider set must survive the round trip.
    ``as_schema()`` emits only the keys that were present or assigned, so a key the
    provider omitted is not invented as ``null``, and in the order the provider sent
    them followed by newly assigned keys in assignment order — the schema reaches the
    model as JSON text, so key order is part of what it sees.
    """

    model_config = ConfigDict(extra="allow")

    _key_order: list[str] = PrivateAttr(default_factory=list)

    type: str | list[str] | None = None
    description: str | None = None
    default: object = None
    minLength: int | None = None
    properties: "dict[str, JsonSchemaNode] | None" = None
    required: list[str] | None = None
    items: "JsonSchemaNode | list[JsonSchemaNode] | None" = None
    anyOf: "list[JsonSchemaNode] | None" = None
    oneOf: "list[JsonSchemaNode] | None" = None
    allOf: "list[JsonSchemaNode] | None" = None
    file_uploadable: bool | None = None

    @model_validator(mode="wrap")
    @classmethod
    def _record_key_order(
        cls, value: object, handler: "Callable[[object], JsonSchemaNode]"
    ) -> "JsonSchemaNode":
        node = handler(value)
        if isinstance(value, dict):
            node._key_order = [str(key) for key in value]
        return node

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if not name.startswith("_") and name not in self._key_order:
            self._key_order.append(name)

    @model_serializer(mode="wrap")
    def _dump_in_key_order(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        dumped: dict[str, object] = handler(self)
        ordered = {key: dumped[key] for key in self._key_order if key in dumped}
        return {**ordered, **dumped}

    @classmethod
    def parse(cls, input_parameters: object) -> "JsonSchemaNode | None":
        """Parse a tool's input_parameters, or return None when it is not a mapping.

        Composio types the attribute as a dict, but callers can hand over non-dict
        values, and a modifier leaves those untouched.
        """
        if not isinstance(input_parameters, dict):
            return None
        return cls.model_validate(input_parameters)

    def as_schema(self) -> dict[str, object]:
        """Return the node as the JSON-schema dict Composio's Tool.input_parameters holds."""
        return self.model_dump(exclude_unset=True)
