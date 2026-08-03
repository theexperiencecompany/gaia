"""MCP configuration models (Pydantic)."""

from typing import Any, Literal, TypedDict

from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import BaseModel

# Auth kinds a probe can report. The extra ``unknown`` (vs MCPConfig.auth_type)
# is what probing reports when the server could not be reached at all.
ProbedAuthType = Literal["none", "oauth", "bearer", "unknown"]


class McpAuthChallenge(TypedDict, total=False):
    """Parsed ``WWW-Authenticate`` challenge from a 401 on the MCP endpoint.

    A ``TypedDict``, not a model (Type Safety item 6): it never crosses a
    validation boundary — ``extract_auth_challenge`` builds it field by field
    from response headers — and every key is optional because a server may send
    a bare ``WWW-Authenticate`` with none of the OAuth hints. An empty dict is
    the "no auth required" signal, so ``total=False`` is load-bearing.
    """

    raw: str
    resource_metadata: str
    scope: str
    error: str
    error_description: str


class McpProbeResult(TypedDict, total=False):
    """What probing an MCP server reports about its auth requirements.

    ``TypedDict`` because the value stays a plain dict at runtime: it is
    threaded through the integration-connection service and read with
    ``.get()`` at several call sites (see Type Safety item 13 — a model here
    would be a behaviour change, not a typing fix). ``oauth_challenge`` is
    present only on the OAuth path; ``error`` only when the probe itself failed.
    """

    requires_auth: bool
    auth_type: ProbedAuthType
    oauth_challenge: McpAuthChallenge
    error: str


class OAuthErrorResponse(TypedDict):
    """An OAuth error body parsed per RFC 6749 Section 5.2.

    A ``TypedDict``, not a model: ``parse_oauth_error_response`` fills every key
    itself (falling back to the raw response text when the body is not JSON), so
    there is nothing left to validate.
    """

    error: str
    error_description: str | None
    error_uri: str | None
    status_code: int


class DCRClientRegistration(TypedDict, total=False):
    """The two RFC 7591 registration fields GAIA reads back from storage.

    The full registration response is persisted verbatim as JSON, but only the
    credentials are ever consumed. Naming them keeps ``.get("client_id")``
    typed ``str | None`` instead of ``Any``; ``total=False`` because a server
    that issues a public client returns no ``client_secret``.
    """

    client_id: str
    client_secret: str


class MCPUseServerConfig(TypedDict, total=False):
    """One entry under ``mcpServers`` in the config handed to ``mcp_use``.

    ``total=False`` mirrors how the config is assembled key by key: ``auth`` is
    ``None`` for unauthenticated servers, and ``headers`` only appears when a
    bearer token or the Composio platform key has to be injected.
    """

    url: str
    transport: str
    auth: str | None
    headers: dict[str, str]


class MCPUseConfig(TypedDict):
    """The ``mcp_use`` client config: server entries keyed by integration id."""

    mcpServers: dict[str, MCPUseServerConfig]


class McpUiResourceDetails(TypedDict):
    """An MCP App's HTML plus the content-level ``_meta.ui`` hints beside it.

    Stays a ``TypedDict``: the streaming layer in ``app/helpers/agent_helpers``
    guards this value with ``isinstance(..., dict)`` before reading it, so a
    model here would silently stop emitting ``mcp_app`` events (Type Safety
    item 13). ``csp`` and ``permissions`` are whatever the MCP server put under
    ``_meta.ui`` — the MCP Apps spec fixes neither shape, and both are forwarded
    to the client verbatim — so they stay ``Any`` (item 8).
    """

    html: str
    csp: Any
    permissions: Any


class OAuthDiscovery(BaseModel):
    """Resolved OAuth discovery result for an MCP integration.

    Wraps the RFC 8414 authorization server metadata (``as_metadata``) together
    with the resource binding, the RFC 9728 Protected Resource Metadata (``prm``,
    present only on the RFC 9728 path) and the WWW-Authenticate challenge scope
    (``initial_scope``).
    """

    as_metadata: OAuthMetadata
    resource: str
    initial_scope: str | None = None
    discovery_method: str
    prm: ProtectedResourceMetadata | None = None

    @property
    def scopes_supported(self) -> list[str]:
        """Scopes advertised by the resource (RFC 9728) or auth server (RFC 8414)."""
        if self.prm and self.prm.scopes_supported:
            return self.prm.scopes_supported
        return self.as_metadata.scopes_supported or []


class MCPConfig(BaseModel):
    """Configuration for MCP (Model Context Protocol) integration."""

    server_url: str
    requires_auth: bool = False
    auth_type: Literal["none", "oauth", "bearer"] | None = None
    transport: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    client_id_env: str | None = None
    client_secret_env: str | None = None
    oauth_scopes: list[str] | None = None
    oauth_metadata: dict[str, str] | None = None


class OAuthScope(BaseModel):
    """OAuth scope configuration."""

    scope: str
    description: str


class ComposioConfig(BaseModel):
    """Configuration for Composio integration."""

    auth_config_id: str
    toolkit: str
    toolkit_version: str | None = None


class SubAgentConfig(BaseModel):
    """Configuration for sub-agent metadata."""

    has_subagent: bool = False
    agent_name: str
    tool_space: str
    handoff_tool_name: str
    domain: str
    capabilities: str
    use_cases: str
    system_prompt: str
    use_direct_tools: bool = False
    disable_retrieve_tools: bool = False
    specific_tools: list[str] | None = None
    # Toolkit tools to drop from this provider's space: neither bound nor
    # retrievable/indexed. Use to retire a stock Composio tool that a custom
    # tool supersedes (e.g. GMAIL_FETCH_EMAILS -> GMAIL_FETCH_MESSAGES).
    exclude_tools: list[str] | None = None
    auto_bind_tools: list[str] | None = None
    # Local/general tools (by name) to bind into this subagent's initial set AND
    # its spawned chunk-reader children — e.g. query_json/grep for a subagent
    # that offloads large results and must mine them sandbox-free. Unlike
    # auto_bind_tools (provider tools, parent-only; children get the hardcoded
    # read/bash/finish set), these propagate to spawned readers so a fan-out
    # child can use them too. Declare per-integration here instead of branching
    # on the provider name in the subagent factory.
    extra_initial_tools: list[str] | None = None
    memory_prompt: str | None = None
    # When False, finish_task is omitted from the subagent's tool set. The
    # subagent must terminate naturally with an AIMessage. The streaming
    # layer's complete_message accumulator captures that text directly —
    # no special-case extraction needed. Use False for read-only / answer-
    # only subagents (e.g. doc fetchers). Default True preserves the
    # explicit-completion contract for action subagents.
    include_finish_task: bool = True


class VariableExtraction(BaseModel):
    """Configuration for a single variable to extract from a tool response."""

    name: str  # Variable name (e.g., "username", "user_id", "email")
    field_path: str  # Dot-notation path to extract (e.g., "data.username")


class ToolMetadataConfig(BaseModel):
    """Configuration for one tool and its variables to extract."""

    tool: str  # Tool to call (e.g., "TWITTER_USER_LOOKUP_ME")
    variables: list[VariableExtraction]  # Variables to extract from this tool's response


class ProviderMetadataConfig(BaseModel):
    """Configuration for fetching provider-specific user metadata.

    Supports multiple tools, each with multiple variables to extract.

    Example:
        metadata_config=ProviderMetadataConfig(
            tools=[
                ToolMetadataConfig(
                    tool="TWITTER_USER_LOOKUP_ME",
                    variables=[
                        VariableExtraction(name="username", field_path="data.username"),
                        VariableExtraction(name="user_id", field_path="data.id"),
                    ],
                ),
            ],
        )
    """

    tools: list[ToolMetadataConfig]  # List of tools to call and variables to extract
