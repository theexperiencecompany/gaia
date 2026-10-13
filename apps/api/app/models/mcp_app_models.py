"""MCP Apps UI shapes: the mcp_ui hint attached to a tool, and the resource it names.

Both cross a boundary (the hint rides the tool_calls_data frame to the client and
Mongo; the MCP server serves the resource), so both are parsed once on entry.
"""

from pydantic import BaseModel, ConfigDict, Field


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
