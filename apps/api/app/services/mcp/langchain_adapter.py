"""
Custom LangChain adapter with schema sanitization for MCP tools.

This adapter fixes field name issues that cause Pydantic validation failures
when MCP servers return tool schemas with leading underscores (e.g., _postman_id).
"""

from typing import Any

from mcp_use.agents.adapters.langchain_adapter import LangChainAdapter


class SanitizingLangChainAdapter(LangChainAdapter):
    """LangChain adapter that sanitizes field names in schemas.

    Some MCP servers (e.g., Postman) return tool schemas with field names
    that start with underscores (e.g., `_postman_id`). Pydantic rejects these
    because underscore-prefixed names are reserved for internal use.

    This adapter overrides `fix_schema` to strip leading underscores from
    property names while preserving the original behavior.
    """

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
                    schema["required"] = [
                        rename_map.get(name, name) for name in schema["required"]
                    ]
            else:
                # Recursively apply to nested schemas
                for key, value in schema.items():
                    schema[key] = self.fix_schema(value)

        elif isinstance(schema, list):
            return [self.fix_schema(item) for item in schema]

        return schema
