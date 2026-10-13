"""Namespace utilities for ChromaDB consistency."""

from app.helpers.mcp_helpers import get_tool_namespace_from_url
from shared.py.wide_events import log


def derive_integration_namespace(
    integration_id: str,
    server_url: str | None = None,
    is_custom: bool = False,
) -> str:
    """Derive namespace for ChromaDB indexing and retrieval.

    Custom MCPs use a URL-derived namespace (domain + path); platform MCPs
    use their configured tool_space. Two integrations at the same domain+path
    intentionally share a namespace, since same-endpoint tools dedup cleanly.
    """
    if is_custom and server_url:
        namespace = get_tool_namespace_from_url(server_url, fallback=integration_id)
        log.debug(
            "Derived namespace from URL for", namespace=namespace, integration_id=integration_id
        )
        return namespace
    return integration_id
