"""
Custom LangChain adapter for MCP tools.

Three concerns the base mcp_use adapter doesn't cover:
- schema sanitization — some MCP servers (e.g. Postman) return property names
  with leading underscores (e.g. _postman_id) that Pydantic rejects;
- annotation preservation — the base adapter drops MCP tool annotations,
  but the HIL gate reads destructiveHint to auto-gate a server-declared
  destructive tool without an LLM classification;
- tool-result parsing — the base adapter stringifies the MCP content list,
  leaking TextContent(...) pydantic reprs to the model and destroying
  image content entirely.
"""

import asyncio
from collections.abc import Iterable
import copy
from typing import NoReturn, TypedDict, cast

from langchain_core.tools import BaseTool

# Module import (not a direct symbol import) so this adapter picks up the
# memoized jsonschema_to_pydantic that resilient_adapter patches onto the module.
import mcp_use.agents.adapters.langchain_adapter as _mcp_use_lc_adapter
from mcp_use.agents.adapters.langchain_adapter import LangChainAdapter
from mcp_use.client.connectors.base import BaseConnector
from mcp_use.errors.error_formatting import format_error
from pydantic import BaseModel, JsonValue, TypeAdapter

from app.constants.mcp import (
    EMPTY_TOOL_RESULT,
    MCP_MEDIA_DROPPED_NOTICE,
    MCP_UNSUPPORTED_CONTENT_NOTICE,
)
from app.constants.media import MAX_MEDIA_BLOCKS_PER_TOOL_RESULT
from app.models.json_schema_models import JsonSchemaNode
from app.utils.image_codec import ImageCodec, InvalidImageError
from app.utils.multimodal import (
    ContentBlock,
    extract_text_content,
    has_media_blocks,
    text_content_block,
)
from mcp.types import (
    CallToolResult,
    ContentBlock as McpContentBlock,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
    Tool as MCPTool,
)


class _FormattedToolError(TypedDict):
    """mcp_use's format_error payload, which mcp_use itself types as a bare dict."""

    error: str
    details: str
    stack: str
    code: JsonValue
    tool: str


# JSON Schema keywords the argument-name mapping walks into.
_SCHEMA_COMBINATORS = ("anyOf", "oneOf", "allOf")
# Keywords whose subschema the argument-name mapping follows into a value.
_ITEMS = "items"
_ADDITIONAL_PROPERTIES = "additionalProperties"
# A tool call's validated arguments, dumped to plain JSON; raises on a value JSON cannot hold.
_ARGUMENTS: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])

# Key under a LangChain tool's ``metadata`` where we stash the MCP tool's
# ``annotations`` dict. Written here, read by ``app/services/hil/classification``.
MCP_ANNOTATIONS_METADATA_KEY = "mcp_annotations"


async def _tool_result_to_content(result: CallToolResult) -> str | list[ContentBlock]:
    """Map MCP content items to LangChain message content.

    Text-only results collapse to a plain string; image items become inline
    media blocks. Each image is bounded/validated by ImageCodec, capped at
    MAX_MEDIA_BLOCKS_PER_TOOL_RESULT; a rejected image degrades to a note
    rather than failing the tool call.
    """
    images = [item for item in result.content if isinstance(item, ImageContent)]
    kept = images[:MAX_MEDIA_BLOCKS_PER_TOOL_RESULT]
    dropped = len(images) - len(kept)
    # Decoding is CPU-bound and hops to a thread per image, so run the whole
    # (budget-bounded) batch at once rather than serializing the result's images.
    decoded = iter(await asyncio.gather(*(_image_block(item) for item in kept)))

    blocks: list[ContentBlock] = []
    for item in result.content:
        if isinstance(item, TextContent):
            blocks.append(text_content_block(item.text))
        elif isinstance(item, ImageContent):
            block = next(decoded, None)
            if block is not None:
                blocks.append(block)
        else:
            blocks.append(text_content_block(_non_media_text(item)))
    if dropped:
        blocks.append(text_content_block(MCP_MEDIA_DROPPED_NOTICE.format(count=dropped)))

    if not blocks:
        return EMPTY_TOOL_RESULT
    if has_media_blocks(list(blocks)):
        return blocks
    return extract_text_content(blocks)


def _non_media_text(item: McpContentBlock) -> str:
    """Text for a content item that is neither plain text nor an inline image.

    Never str(item) — that is the pydantic repr this adapter exists to keep
    out of the model's context. An embedded text resource (what filesystem and
    database servers return) carries real text; anything else has none.
    """
    if isinstance(item, EmbeddedResource) and isinstance(item.resource, TextResourceContents):
        return item.resource.text
    return MCP_UNSUPPORTED_CONTENT_NOTICE.format(kind=type(item).__name__)


async def _image_block(item: ImageContent) -> ContentBlock:
    try:
        image = await ImageCodec.from_base64(item.data)
    except InvalidImageError as exc:
        return text_content_block(f"[Image from this result could not be read: {exc}]")
    return image.to_block()


def _model_names(properties: Iterable[str]) -> dict[str, str]:
    """Map a node's server property names to the names the model sees.

    Pydantic rejects a leading underscore, so _id is shown as id; a name the node
    already uses (the server also has id) gets a numeric suffix instead of colliding.
    """
    names = list(properties)
    taken = {name for name in names if not name.startswith("_")}
    model_names: dict[str, str] = {}
    for name in names:
        if name in taken:
            model_names[name] = name
            continue
        stripped = name.lstrip("_")
        base = stripped if stripped and not stripped[0].isdigit() else f"field{stripped}"
        candidate, attempt = base, 1
        while candidate in taken:
            attempt += 1
            candidate = f"{base}_{attempt}"
        taken.add(candidate)
        model_names[name] = candidate
    return model_names


def _alternatives(schema: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Return the node and every anyOf/oneOf/allOf option under it: one value may match any."""
    found = [schema]
    for combinator in _SCHEMA_COMBINATORS:
        options = schema.get(combinator)
        if not isinstance(options, list):
            continue
        for option in options:
            if isinstance(option, dict):
                found.extend(_alternatives(option))
    return found


def _declared_nodes(schema: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    declared: list[dict[str, JsonValue]] = []
    for alternative in _alternatives(schema):
        node: JsonSchemaNode = cast(JsonSchemaNode, alternative)
        if "properties" in alternative and isinstance(node["properties"], dict):
            declared.append(node["properties"])
    return declared


def _group_model_names(schema: dict[str, JsonValue]) -> dict[str, str]:
    """Name a node's properties and its combinator options' together: they share one object's keys."""
    return _model_names(dict.fromkeys(name for props in _declared_nodes(schema) for name in props))


def _any_of(candidates: list[JsonValue]) -> JsonValue:
    """Return the one schema a value must match, or any of several."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return {"anyOf": candidates}


def _keyword_schema(schema: dict[str, JsonValue], keyword: str) -> JsonValue:
    """Return a keyword's schema (items, additionalProperties) across the node's alternatives."""
    return _any_of([alt[keyword] for alt in _alternatives(schema) if keyword in alt])


def _to_server_names(value: JsonValue, schema: JsonValue) -> JsonValue:
    """Map the model's argument keys back to the server's, named exactly as the schema was built."""
    if not isinstance(schema, dict):
        return value
    if isinstance(value, list):
        items = _keyword_schema(schema, _ITEMS)
        return [_to_server_names(item, items) for item in value]
    if not isinstance(value, dict):
        return value
    declared = _declared_nodes(schema)
    server_names = {model: server for server, model in _group_model_names(schema).items()}
    renamed: dict[str, JsonValue] = {}
    for key, item in value.items():
        server_name = server_names.get(key, key)
        declared_schemas = [props[server_name] for props in declared if server_name in props]
        item_schema = (
            _any_of(declared_schemas)
            if declared_schemas
            else _keyword_schema(schema, _ADDITIONAL_PROPERTIES)
        )
        renamed[server_name] = _to_server_names(item, item_schema)
    return renamed


class SanitizingLangChainAdapter(LangChainAdapter):
    """LangChain adapter that sanitizes MCP schemas and preserves annotations.

    Some MCP servers (e.g. Postman) return tool schemas with field names that
    start with underscores (e.g. _postman_id); Pydantic rejects those
    because underscore-prefixed names are reserved. fix_schema strips them.

    The base adapter also discards MCP annotations; _convert_tool
    re-attaches them to the tool's metadata so the HIL gate can honor
    destructiveHint.
    """

    def fix_schema(self, schema: JsonValue) -> JsonValue:
        """Fix a JSON schema for Pydantic: type arrays, bare enums, underscore-prefixed properties."""
        return self._sanitize(schema, None)

    def _sanitize(self, schema: JsonValue, group_names: dict[str, str] | None) -> JsonValue:
        """Sanitize one node; a combinator option is named in its parent's group, one object's keys."""
        if isinstance(schema, list):
            return [self._sanitize(item, None) for item in schema]
        if not isinstance(schema, dict):
            return schema
        node: JsonSchemaNode = cast(JsonSchemaNode, schema)

        types = node.get("type")
        if isinstance(types, list):
            node["anyOf"] = [{"type": t} for t in types]
            del node["type"]
        if "enum" in node and "type" not in node:
            node["type"] = "string"

        names = group_names if group_names is not None else _group_model_names(schema)
        has_properties = "properties" in schema and isinstance(node["properties"], dict)
        for key, value in schema.items():
            if key in _SCHEMA_COMBINATORS and isinstance(value, list):
                schema[key] = [self._sanitize(option, names) for option in value]
            elif not has_properties:
                schema[key] = self._sanitize(value, None)
        if not has_properties:
            return schema

        node["properties"] = {
            names[name]: self._sanitize(value, None) for name, value in node["properties"].items()
        }
        required = node.get("required")
        if isinstance(required, list):
            node["required"] = [names.get(name, name) for name in required]
        return schema

    def _convert_tool(self, mcp_tool: MCPTool, connector: BaseConnector) -> BaseTool | None:
        """Convert an MCP tool to LangChain format.

        Mirrors mcp_use's implementation except: result parsing avoids pydantic
        reprs and lost media, MCP annotations survive for the HIL gate, and the
        server is called by mcp_name so name can be renamed on GAIA's side.
        """
        if mcp_tool.name in self.disallowed_tools:
            return None

        adapter_self = self

        class McpToLangChainAdapter(BaseTool):
            name: str = mcp_tool.name or "NO NAME"
            mcp_name: str = mcp_tool.name
            description: str = mcp_tool.description or ""
            args_schema: type[BaseModel] = _mcp_use_lc_adapter.jsonschema_to_pydantic(
                adapter_self.fix_schema(copy.deepcopy(mcp_tool.inputSchema))
            )
            server_schema: dict[str, JsonValue] = mcp_tool.inputSchema
            tool_connector: BaseConnector = connector
            handle_tool_error: bool = True

            def __repr__(self) -> str:
                return f"MCP tool: {self.name}: {self.description}"

            def _run(self, **kwargs: object) -> NoReturn:
                raise NotImplementedError("MCP tools only support async operations")

            async def _arun(
                self, **kwargs: object
            ) -> str | list[ContentBlock] | _FormattedToolError:
                try:
                    # Nested objects arrive as Pydantic models, under the model's names.
                    # Equivalent under mutation: the generated models hold only JSON-native values.
                    as_json = _ARGUMENTS.dump_python(kwargs, mode="json")  # pragma: no mutate
                    arguments = _to_server_names(as_json, self.server_schema)
                    tool_result: CallToolResult = await self.tool_connector.call_tool(
                        self.mcp_name, arguments
                    )
                    try:
                        return await _tool_result_to_content(tool_result)
                    except Exception as e:
                        return cast(_FormattedToolError, format_error(e, tool=self.name))
                except Exception as e:
                    if self.handle_tool_error:
                        return cast(_FormattedToolError, format_error(e, tool=self.name))
                    raise

        tool = McpToLangChainAdapter()
        if mcp_tool.annotations is not None:
            tool.metadata = {
                **(tool.metadata or {}),
                MCP_ANNOTATIONS_METADATA_KEY: mcp_tool.annotations.model_dump(),
            }
        return tool
