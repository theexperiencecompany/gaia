"""
MCP Helper Functions.

Contains helper functions for MCP operations:
- Stub tool creation from cached metadata
- URL helpers for OAuth flows
- Cache invalidation utilities
"""

from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import Field, create_model

from app.config.loggers import langchain_logger as logger
from app.config.settings import settings
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.redis import delete_cache
from app.utils.mcp_utils import extract_type_from_field

if TYPE_CHECKING:
    from app.services.mcp.mcp_client import MCPClient


def get_api_base_url() -> str:
    """Get the backend API base URL for callbacks."""
    return getattr(settings, "API_BASE_URL", "http://localhost:8000")


def get_frontend_url() -> str:
    """Get the frontend base URL for redirects."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:3000")


async def invalidate_mcp_status_cache(user_id: str) -> None:
    """Invalidate OAuth status cache for parity with Composio."""
    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"Invalidated MCP status cache for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate status cache: {e}")


def create_stub_tools_from_cache(
    client: "MCPClient",
    integration_id: str,
    cached_tools: list[dict],
) -> list[BaseTool]:
    """
    Create stub BaseTool objects from cached tool metadata.

    These stub tools have the correct name/description for indexing
    but will connect to the MCP server on-demand when actually executed.
    """

    def make_stub_executor(mcp_client: "MCPClient", int_id: str, tool_name: str):
        """Factory to create stub executor with proper closure."""

        async def _stub_execute(**kwargs):
            filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            logger.debug(
                f"Stub {tool_name}: raw args={kwargs}, filtered={filtered_kwargs}"
            )

            tools = await mcp_client.ensure_connected(int_id)
            real_tool = next((t for t in tools if t.name == tool_name), None)
            if real_tool:
                return await real_tool.ainvoke(filtered_kwargs)
            raise ValueError(f"Tool {tool_name} not found after connecting")

        return _stub_execute

    stub_tools = []
    for tool_meta in cached_tools:
        name = tool_meta.get("name", "unknown")
        description = tool_meta.get("description", "")

        args_schema = tool_meta.get("args_schema")
        logger.debug(f"Stub {name}: args_schema from cache = {args_schema is not None}")

        if (
            args_schema
            and isinstance(args_schema, dict)
            and "properties" in args_schema
        ):
            logger.debug(
                f"Stub {name}: {len(args_schema.get('properties', {}))} properties, "
                f"required={args_schema.get('required', [])}"
            )
            properties = args_schema.get("properties", {})
            required_fields = args_schema.get("required", [])
            fields = {}

            for field_name, field_info in properties.items():
                field_type, default_val, is_optional = extract_type_from_field(
                    field_info
                )

                is_required = field_name in required_fields

                if is_required:
                    field_default = ...
                elif default_val is not None:
                    field_default = default_val
                else:
                    field_default = None

                fields[field_name] = (
                    field_type,
                    Field(
                        default=field_default,
                        description=field_info.get("description", ""),
                    ),
                )

                logger.debug(
                    f"Stub {name}.{field_name}: "
                    f"type={field_type.__name__ if hasattr(field_type, '__name__') else field_type}, "
                    f"default={field_default}, required={is_required}"
                )

            DynamicSchema = create_model(f"{name}Schema", **fields)
        else:
            DynamicSchema = None

        stub_tool = StructuredTool.from_function(
            func=lambda **kwargs: None,
            coroutine=make_stub_executor(client, integration_id, name),
            name=name,
            description=description,
            args_schema=DynamicSchema if DynamicSchema else None,
        )
        stub_tools.append(stub_tool)

    return stub_tools
