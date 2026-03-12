"""Utilities for the context gathering system."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, List, Optional, Set

from shared.py.wide_events import log
from pydantic import BaseModel

# ── Performance tuning ───────────────────────────────────────────────────────

MAX_WORKERS = 8
PROVIDER_TIMEOUT_SECONDS = 30


# ── Composio tool executor ───────────────────────────────────────────────────


def execute_tool(
    tool_name: str,
    params: Dict[str, Any],
    user_id: str,
    output_model: type[BaseModel] | None = None,
) -> Dict[str, Any]:
    """Execute a Composio tool directly (bypasses hook pipeline) and return its data dict.

    Args:
        tool_name: Composio tool name, e.g. "GMAIL_FETCH_EMAILS".
        params: Parameters to pass to the tool.
        user_id: User ID used for authentication.
        output_model: Optional Pydantic model to validate the response data.

    Returns:
        The ``data`` payload from the tool response.

    Raises:
        Exception: If the tool execution fails.
    """
    from app.services.composio.composio_service import get_composio_service

    log.set(tool_name=tool_name, user_id=user_id)
    composio_service = get_composio_service()
    result = composio_service.composio.tools.execute(
        slug=tool_name,
        arguments=params,
        user_id=user_id,
        dangerously_skip_version_check=True,
    )

    if not result["successful"]:
        raise Exception(result.get("error") or f"{tool_name} failed")

    data = result["data"]

    if output_model:
        try:
            validated = output_model.model_validate(data)
            return validated.model_dump()
        except Exception as e:
            log.warning(f"Schema validation warning for {tool_name}: {e}")
            return data

    return data


# ── Parallel provider fetching ──────────────────────────────────────────────


def fetch_all_providers(
    providers: List[str],
    provider_tools: Dict[str, str],
    user_id: str,
) -> Dict[str, Any]:
    """Fetch all providers in parallel by calling each CUSTOM_GATHER_CONTEXT tool."""

    def fetch_one(provider: str) -> tuple:
        tool_slug = provider_tools[provider]
        try:
            data = execute_tool(tool_slug, {}, user_id)
            return provider, data
        except Exception as e:
            log.warning(f"Provider {provider} ({tool_slug}) failed: {e}")
            return provider, None

    results: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, p): p for p in providers}
        for future in futures:
            try:
                provider, data = future.result(timeout=PROVIDER_TIMEOUT_SECONDS)
                if data is not None:
                    results[provider] = data
            except FuturesTimeout:
                provider = futures[future]
                log.warning(f"Provider {provider} timed out")
            except Exception as e:
                provider = futures[future]
                log.error(f"Unexpected error for {provider}: {e}")
    return results


# ── Provider resolution ─────────────────────────────────────────────────────


async def resolve_providers(
    requested: Optional[List[str]],
    user_id: str,
    provider_tools: Dict[str, str],
    namespace_fn: Callable[[str], str],
) -> List[str]:
    """Return the list of providers to query based on request + connected integrations.

    Args:
        requested: Explicit provider list from the caller, or None for auto-detect.
        user_id: User ID used to look up connected integrations.
        provider_tools: Registry mapping provider key -> tool slug.
        namespace_fn: Callable that derives a namespace from a tool slug.
    """
    log.set(user_id=user_id, requested_providers=requested)
    if requested:
        return [p.lower() for p in requested if p.lower() in provider_tools]

    from app.services.integrations.integration_service import (
        get_user_available_tool_namespaces,
    )

    connected: Set[str] = set()
    try:
        connected = await get_user_available_tool_namespaces(user_id)
    except Exception as e:
        log.warning(f"Could not get connected namespaces: {e}")

    if connected:
        filtered = [
            p for p, slug in provider_tools.items() if namespace_fn(slug) in connected
        ]
        if filtered:
            log.info(f"Auto-selected {len(filtered)} connected providers: {filtered}")
            return filtered

    log.warning("No connected providers detected — returning empty list")
    return []
