"""
Custom LangChain adapter for MCP tools.

Three concerns the base ``mcp_use`` adapter doesn't cover:
- schema sanitization — some MCP servers (e.g. Postman) return property names
  with leading underscores (e.g. ``_postman_id``) that Pydantic rejects;
- annotation preservation — the base adapter drops MCP tool ``annotations``,
  but the HIL gate reads ``destructiveHint`` to auto-gate a server-declared
  destructive tool without an LLM classification;
- tool-result parsing — the base adapter stringifies the MCP content list,
  leaking ``TextContent(...)`` pydantic reprs to the model and destroying
  image content entirely.
"""

import asyncio
from typing import Any, NoReturn, cast

from langchain_core.tools import BaseTool

# Module import (not a direct symbol import) so this adapter picks up the
# memoized jsonschema_to_pydantic that resilient_adapter patches onto the module.
import mcp_use.agents.adapters.langchain_adapter as _mcp_use_lc_adapter
from mcp_use.agents.adapters.langchain_adapter import LangChainAdapter
from mcp_use.client.connectors.base import BaseConnector
from mcp_use.errors.error_formatting import format_error
from pydantic import BaseModel

from app.constants.mcp import (
    EMPTY_TOOL_RESULT,
    MCP_MEDIA_DROPPED_NOTICE,
    MCP_UNSUPPORTED_CONTENT_NOTICE,
)
from app.constants.media import MAX_MEDIA_BLOCKS_PER_TOOL_RESULT
from app.utils.image_codec import ImageCodec, InvalidImageError
from app.utils.multimodal import text_content_block
from mcp.types import (
    CallToolResult,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
    Tool as MCPTool,
)

# Key under a LangChain tool's ``metadata`` where we stash the MCP tool's
# ``annotations`` dict. Written here, read by ``app/services/hil/classification``.
MCP_ANNOTATIONS_METADATA_KEY = "mcp_annotations"


async def _tool_result_to_content(result: CallToolResult) -> str | list[dict[str, Any]]:
    """Map MCP content items to LangChain message content.

    Text-only results collapse to a plain string (the common case). Image items
    become inline media blocks so multimodal models see the actual pixels;
    per-lane delivery is decided later, at the request boundary (see
    `app/agents/llm/vision/`).

    MCP servers are third-party code we do not control, so images are held to
    the same budget as any other producer: `ImageCodec` bounds and validates
    each one, and `MAX_MEDIA_BLOCKS_PER_TOOL_RESULT` bounds how many a single
    result may contribute. A rejected image degrades to a note rather than
    failing the tool call — the text half of the result is usually the point.
    """
    images = [item for item in result.content if isinstance(item, ImageContent)]
    kept = images[:MAX_MEDIA_BLOCKS_PER_TOOL_RESULT]
    dropped = len(images) - len(kept)
    # Decoding is CPU-bound and hops to a thread per image, so run the whole
    # (budget-bounded) batch at once rather than serializing the result's images.
    decoded = iter(await asyncio.gather(*(_image_block(item) for item in kept)))

    blocks: list[dict[str, Any]] = []
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
    if any(block["type"] != "text" for block in blocks):
        return blocks
    return "\n".join(block["text"] for block in blocks)


def _non_media_text(item: ContentBlock) -> str:
    """Text for a content item that is neither plain text nor an inline image.

    Never ``str(item)`` — that is the pydantic repr this adapter exists to keep
    out of the model's context. An embedded text resource (what filesystem and
    database servers return) carries real text; anything else has none.
    """
    if isinstance(item, EmbeddedResource) and isinstance(item.resource, TextResourceContents):
        return item.resource.text
    return MCP_UNSUPPORTED_CONTENT_NOTICE.format(kind=type(item).__name__)


async def _image_block(item: ImageContent) -> dict[str, Any]:
    try:
        image = await ImageCodec.from_base64(item.data)
    except InvalidImageError as exc:
        return text_content_block(f"[Image from this result could not be read: {exc}]")
    return image.to_block()


class SanitizingLangChainAdapter(LangChainAdapter):
    """LangChain adapter that sanitizes MCP schemas and preserves annotations.

    Some MCP servers (e.g. Postman) return tool schemas with field names that
    start with underscores (e.g. ``_postman_id``); Pydantic rejects those
    because underscore-prefixed names are reserved. ``fix_schema`` strips them.

    The base adapter also discards MCP ``annotations``; ``_convert_tool``
    re-attaches them to the tool's ``metadata`` so the HIL gate can honor
    ``destructiveHint``.
    """

    def fix_schema(self, schema: Any) -> Any:  # noqa: ANN401 -- framework contract
        """Fix JSON schema for Pydantic compatibility.

        Signature kept as ``Any`` on purpose: this overrides mcp_use's
        ``LangChainAdapter.fix_schema``, which the base adapter calls with
        arbitrary JSON-schema nodes (dict, list, or scalar) and whose own
        annotation is ``Any``. Narrowing it here would break that contract
        (Type Safety item 14).

        Extends the base fix_schema to also:
        - Strip leading underscores from property names
        - Update 'required' array to match renamed properties

        Args:
            schema: The JSON schema to fix.

        Returns:
            The fixed JSON schema.
        """
        if isinstance(schema, dict):
            # First, apply the base class fixes (type arrays, enums)
            if "type" in schema and isinstance(schema["type"], list):
                schema["anyOf"] = [{"type": t} for t in schema["type"]]
                del schema["type"]

            if "enum" in schema and "type" not in schema:
                schema["type"] = "string"

            # Now fix property names with leading underscores
            if "properties" in schema and isinstance(schema["properties"], dict):
                renamed_props = {}
                rename_map = {}

                for prop_name, prop_value in schema["properties"].items():
                    # Strip leading underscores from property names
                    if prop_name.startswith("_"):
                        new_name = prop_name.lstrip("_")
                        # Ensure the new name is valid (not empty, doesn't start with digit)
                        if not new_name or new_name[0].isdigit():
                            new_name = f"field{new_name}"
                        rename_map[prop_name] = new_name
                        renamed_props[new_name] = self.fix_schema(prop_value)
                    else:
                        renamed_props[prop_name] = self.fix_schema(prop_value)

                schema["properties"] = renamed_props

                # Update 'required' array with renamed property names
                if "required" in schema and isinstance(schema["required"], list):
                    schema["required"] = [rename_map.get(name, name) for name in schema["required"]]
            else:
                # Recursively apply to nested schemas
                for key, value in schema.items():
                    schema[key] = self.fix_schema(value)

        elif isinstance(schema, list):
            return [self.fix_schema(item) for item in schema]

        return schema

    def _convert_tool(self, mcp_tool: MCPTool, connector: BaseConnector) -> BaseTool | None:
        """Convert an MCP tool to LangChain format.

        Mirrors mcp_use's implementation except for two things upstream gets
        wrong for us: result parsing (upstream returns ``str(tool_result.content)``,
        which leaks pydantic reprs and destroys media blocks, see
        ``_tool_result_to_content``), and the MCP ``annotations``, which upstream
        drops but the HIL gate reads for ``destructiveHint``.
        """
        if mcp_tool.name in self.disallowed_tools:
            return None

        adapter_self = self

        class McpToLangChainAdapter(BaseTool):
            name: str = mcp_tool.name or "NO NAME"
            description: str = mcp_tool.description or ""
            args_schema: type[BaseModel] = _mcp_use_lc_adapter.jsonschema_to_pydantic(
                adapter_self.fix_schema(mcp_tool.inputSchema)
            )
            tool_connector: BaseConnector = connector
            handle_tool_error: bool = True

            def __repr__(self) -> str:
                return f"MCP tool: {self.name}: {self.description}"

            def _run(self, **kwargs: Any) -> NoReturn:  # noqa: ANN401 -- contract
                raise NotImplementedError("MCP tools only support async operations")

            async def _arun(self, **kwargs: Any) -> str | list[dict[str, Any]] | dict[str, Any]:  # noqa: ANN401 -- adapts the untyped MCP client into LangChain tools
                try:
                    tool_result: CallToolResult = await self.tool_connector.call_tool(
                        self.name, kwargs
                    )
                    try:
                        return await _tool_result_to_content(tool_result)
                    except Exception as e:
                        # mcp_use ships no py.typed marker, so mypy treats
                        # format_error's real `-> dict` annotation as Any.
                        return cast(dict[str, Any], format_error(e, tool=self.name))
                except Exception as e:
                    if self.handle_tool_error:
                        # mcp_use ships no py.typed marker, so mypy treats
                        # format_error's real `-> dict` annotation as Any.
                        return cast(dict[str, Any], format_error(e, tool=self.name))
                    raise

        tool = McpToLangChainAdapter()
        if mcp_tool.annotations is not None:
            tool.metadata = {
                **(tool.metadata or {}),
                MCP_ANNOTATIONS_METADATA_KEY: mcp_tool.annotations.model_dump(),
            }
        return tool
