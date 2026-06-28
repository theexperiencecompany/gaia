from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class FaviconAuditItem(_CamelModel):
    """One MCP server's favicon under the legacy vs patched resolver."""

    integration_id: str
    name: str
    source: str = Field(description="platform or custom")
    managed_by: str
    server_url: str | None = Field(
        None, description="MCP server URL, if this is an MCP integration"
    )
    stored_icon_url: str | None = Field(
        None, description="icon_url currently persisted on the integration (custom only)"
    )
    before_url: str | None = Field(
        None, description="Legacy resolver: Google S2 on the registered domain (MCP only)"
    )
    after_url: str | None = Field(
        None, description="Patched resolver: per-host resolution (MCP only)"
    )
    changed: bool = Field(description="Whether before and after differ")


class FaviconAuditResponse(_CamelModel):
    environment: str
    total: int
    changed: int
    items: list[FaviconAuditItem]
