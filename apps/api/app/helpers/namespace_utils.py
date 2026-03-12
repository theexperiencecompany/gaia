"""Namespace utilities for ChromaDB consistency."""

from app.helpers.mcp_helpers import get_tool_namespace_from_url
from shared.py.wide_events import log


def derive_integration_namespace(
    integration_id: str,
    server_url: str | None = None,
    is_custom: bool = False,
) -> str:
    """Derive namespace for ChromaDB indexing and retrieval.

    For custom MCPs: uses URL-derived namespace (domain + path).
    For platform MCPs: uses configured tool_space from subagent_config.
    Fallback: integration_id.

    Note: This assumes each custom integration has a unique server URL.
    If two integrations point to the same domain+path (e.g. api.example.com/v1),
    their tools will share a namespace. This is intentional — same-endpoint tools
    are semantically equivalent and deduplication is desirable.
    """
    if is_custom and server_url:
        namespace = get_tool_namespace_from_url(server_url, fallback=integration_id)
        log.debug(f"Derived namespace '{namespace}' from URL for {integration_id}")
        return namespace
    return integration_id
