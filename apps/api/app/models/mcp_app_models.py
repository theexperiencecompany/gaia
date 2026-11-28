"""MCP Apps UI shapes: the mcp_ui hint attached to a tool, the resource it names, and the card it renders on.

Both cross a boundary (the hint rides the tool_calls_data frame to the client and
Mongo; the MCP server serves the resource), so both are parsed once on entry.
"""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.common import ResponseModel


class McpUiMetadata(BaseModel):
    """The ``_meta.ui`` hint on an MCP tool: which resource renders its app.

    ``csp`` and ``permissions`` are whatever the MCP server declared — the MCP
    Apps spec fixes neither shape, and both are forwarded to the client
    verbatim — so they stay ``object``. Forwarded with ``exclude_unset`` so an
    absent key stays absent on the wire; a reader that needs a value gets the
    defaults here.
    """

    model_config = ConfigDict(extra="ignore")

    resource_uri: str
    csp: object = None
    permissions: object = Field(default_factory=list)


class McpUiResource(BaseModel):
    """An MCP App's HTML plus the content-level ``_meta.ui`` hints beside it.

    The served ``csp``/``permissions`` win over the declared ones when present.
    """

    model_config = ConfigDict(extra="ignore")

    html: str | None = None
    csp: object = None
    permissions: object = None


class McpAppData(ResponseModel):
    """The mcp_app card's payload: an MCP App's HTML with the call it renders.

    csp, permissions and tool_result are the MCP server's own JSON, forwarded verbatim; tool_result
    is the call's raw result, or its result text once the tool's output arrives.
    """

    tool_call_id: str
    tool_name: str
    server_url: str
    resource_uri: str
    html_content: str
    tool_result: JsonValue
    csp: JsonValue
    permissions: JsonValue
    tool_arguments: dict[str, JsonValue]
