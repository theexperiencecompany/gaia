"""
Custom LangChain adapter for MCP tools.

Two concerns the base ``mcp_use`` adapter doesn't cover:
- schema sanitization — some MCP servers (e.g. Postman) return property names
  with leading underscores that Pydantic rejects;
- annotation preservation — the base adapter drops MCP tool ``annotations``,
  but the HIL gate reads ``destructiveHint`` to auto-gate a server-declared
  destructive tool without an LLM classification.
"""

from typing import Any

from langchain_core.tools import BaseTool
from mcp_use.agents.adapters.langchain_adapter import LangChainAdapter
from mcp_use.client.connectors.base import BaseConnector

from mcp.types import Tool as MCPTool

# Key under a LangChain tool's ``metadata`` where we stash the MCP tool's
# ``annotations`` dict. Written here, read by ``app/services/hil/classification``.
MCP_ANNOTATIONS_METADATA_KEY = "mcp_annotations"


class SanitizingLangChainAdapter(LangChainAdapter):
    """LangChain adapter that sanitizes MCP schemas and preserves annotations.

    Some MCP servers (e.g. Postman) return tool schemas with field names that
    start with underscores (e.g. ``_postman_id``); Pydantic rejects those
    because underscore-prefixed names are reserved. ``fix_schema`` strips them.

    The base adapter also discards MCP ``annotations``; ``_convert_tool``
    re-attaches them to the tool's ``metadata`` so the HIL gate can honor
    ``destructiveHint``.
    """

    def _convert_tool(self, mcp_tool: MCPTool, connector: BaseConnector) -> BaseTool | None:
        """Build the LangChain tool, then re-attach the dropped MCP annotations."""
        tool = super()._convert_tool(mcp_tool, connector)
        if tool is not None and mcp_tool.annotations is not None:
            tool.metadata = {
                **(tool.metadata or {}),
                MCP_ANNOTATIONS_METADATA_KEY: mcp_tool.annotations.model_dump(),
            }
        return tool

    def fix_schema(self, schema: Any) -> Any:
        """Fix JSON schema for Pydantic compatibility.

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
