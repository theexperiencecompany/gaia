"""Utilities for the context gathering system."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from pydantic import BaseModel, ConfigDict

from app.constants.log_tags import LogTag
from shared.py.wide_events import log


class _ToolExecutionResponse(BaseModel):
    """Composio's ``ToolExecutionResponse`` envelope, parsed once.

    ``data`` is the provider's own payload and is left unvalidated: Composio
    declares it a dict, but some endpoints hand back the provider's bare list
    (see ``TrelloCardList``), so each caller validates it into its own model.
    """

    model_config = ConfigDict(extra="ignore")

    successful: bool
    error: str | None = None
    data: object = None


# ── Performance tuning ───────────────────────────────────────────────────────

PROVIDER_TIMEOUT_SECONDS = 30

# Dedicated pool, isolated from the default asyncio thread pool, so slow
# Composio calls don't starve async I/O; max_workers=4 caps concurrent calls.
# Do NOT use as the outer run_in_executor target — see context_tool.py.
_CONTEXT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ctx-fetch")


# ── Composio tool executor ───────────────────────────────────────────────────


def execute_tool(
    tool_name: str,
    params: dict[str, object],
    user_id: str,
    output_model: type[BaseModel] | None = None,
) -> object:
    """Execute a Composio tool directly (bypasses hook pipeline) and return its raw data payload; raises if the call fails."""
    # Deferred import: heavy Composio SDK service stack loads only when context enrichment executes a tool
    from app.services.composio.composio_service import (  # noqa: PLC0415 -- deferred
        get_composio_service,
    )

    log.set(tool_name=tool_name, user_id=user_id)
    composio_service = get_composio_service()
    result = _ToolExecutionResponse.model_validate(
        composio_service.composio.tools.execute(
            slug=tool_name,
            arguments=params,
            user_id=user_id,
            dangerously_skip_version_check=True,
        )
    )

    if not result.successful:
        raise Exception(result.error or f"{tool_name} failed")

    data = result.data

    if output_model:
        try:
            validated = output_model.model_validate(data)
            # Tool returns cross into text; python-mode keeps native datetimes.
            return validated.model_dump(mode="json")
        except Exception as e:
            log.warning(
                f"{LogTag.AGENT} Schema validation warning for",
                tool_name=tool_name,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return data

    return data


# ── Parallel provider fetching ──────────────────────────────────────────────


def fetch_all_providers(
    providers: list[str],
    provider_tools: dict[str, str],
    user_id: str,
) -> dict[str, object]:
    """Fetch all providers in parallel by calling each CUSTOM_GATHER_CONTEXT tool.

    Values are each provider's raw CUSTOM_GATHER_CONTEXT payload, whose shape
    is the provider's own and differs per integration.
    """

    def fetch_one(provider: str) -> tuple[str, object | None]:
        tool_slug = provider_tools[provider]
        try:
            data = execute_tool(tool_slug, {}, user_id)
            return provider, data
        except Exception as e:
            log.warning(
                f"{LogTag.AGENT} Provider failed",
                provider=provider,
                tool_slug=tool_slug,
                error=str(e),
                error_type=type(e).__name__,
            )
            return provider, None

    results: dict[str, object] = {}
    # Use the module-level dedicated pool instead of creating a new one per call.
    # This prevents unbounded thread creation under concurrent agent sessions
    # and isolates context-fetching threads from the default asyncio pool.
    futures = {_CONTEXT_EXECUTOR.submit(fetch_one, p): p for p in providers}
    for future, submitted_provider in futures.items():
        try:
            provider, data = future.result(timeout=PROVIDER_TIMEOUT_SECONDS)
            if data is not None:
                results[provider] = data
        except FuturesTimeout:
            log.warning(
                f"{LogTag.AGENT} Provider timed out", provider=submitted_provider, user_id=user_id
            )
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Unexpected error for",
                provider=submitted_provider,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
    return results


# ── Provider resolution ─────────────────────────────────────────────────────


async def resolve_providers(
    requested: list[str] | None,
    user_id: str,
    provider_tools: dict[str, str],
    namespace_fn: Callable[[str], str],
) -> list[str]:
    """Return the list of providers to query: the request, or connected integrations when requested is None."""
    log.set(user_id=user_id, requested_providers=requested)
    if requested:
        return [p.lower() for p in requested if p.lower() in provider_tools]

    from app.services.integrations.integration_service import (  # noqa: PLC0415 -- integration-service stack deferred until provider auto-detection actually runs
        get_user_available_tool_namespaces,
    )

    connected: set[str] = set()
    try:
        connected = await get_user_available_tool_namespaces(user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Could not get connected namespaces",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )

    if connected:
        filtered = [p for p, slug in provider_tools.items() if namespace_fn(slug) in connected]
        if filtered:
            log.info(
                f"{LogTag.AGENT} Auto-selected connected providers",
                filtered_count=len(filtered),
                filtered=filtered,
            )
            return filtered

    log.warning(f"{LogTag.AGENT} No connected providers detected — returning empty list")
    return []
