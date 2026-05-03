"""User integration management functions."""

import asyncio
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

import httpx

from app.agents.tools.core.registry import get_tool_registry
from shared.py.wide_events import log
from app.config.settings import settings
from app.config.token_repository import token_repository
from app.constants.cache import ONE_DAY_TTL
from app.db.mongodb.collections import user_integrations_collection
from app.db.utils import serialize_document
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.integration_models import (
    IntegrationTool,
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.services.integrations.marketplace import get_integration_details

# Provider-specific OAuth token revocation strategies. Each provider has its
# own request shape — Google/Notion accept ``token`` as form data, Slack
# requires a Bearer header, GitHub takes a DELETE with HTTP Basic auth. A
# local row deletion without upstream revoke leaves live tokens loose on the
# provider side (H7). Providers not listed here proceed with local-only
# delete and a single warning log.

_GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"

_REVOKE_TIMEOUT_SECONDS = 5.0
# Transient-failure retry budget. Total worst-case wall time is
# ``sum(_REVOKE_RETRY_DELAYS_SECONDS) + (len + 1) * _REVOKE_TIMEOUT_SECONDS``,
# bounded so a slow provider can't hold the disconnect handler indefinitely.
_REVOKE_RETRY_DELAYS_SECONDS = (0.5, 2.0)


async def _revoke_with_retry(
    do_request: Callable[[], Awaitable[Optional[httpx.Response]]],
) -> Optional[httpx.Response]:
    """Invoke ``do_request`` with retry on transient errors.

    Retries on:
      - ``httpx.TransportError`` / ``httpx.TimeoutException`` (network blip)
      - 5xx responses (provider blip)
    A 4xx is treated as terminal — those are auth/format errors that won't
    self-resolve and shouldn't be retried.
    """
    last_response: Optional[httpx.Response] = None
    for attempt, delay in enumerate((0.0, *_REVOKE_RETRY_DELAYS_SECONDS)):
        if delay:
            await asyncio.sleep(delay)
        try:
            response = await do_request()
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == len(_REVOKE_RETRY_DELAYS_SECONDS):
                raise
            continue
        if response is None or response.status_code < 500:
            return response
        last_response = response
    return last_response


async def _revoke_form_token(
    client: httpx.AsyncClient, endpoint: str, token_value: str
) -> httpx.Response:
    """Form-body revoke (Google, Notion)."""
    return await client.post(
        endpoint,
        data={"token": token_value},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


async def _revoke_slack(
    client: httpx.AsyncClient, token_value: str
) -> httpx.Response:
    """Slack expects the access token as a Bearer header."""
    return await client.post(
        "https://slack.com/api/auth.revoke",
        headers={"Authorization": f"Bearer {token_value}"},
    )


async def _revoke_github(
    client: httpx.AsyncClient, token_value: str
) -> Optional[httpx.Response]:
    """GitHub revokes with DELETE + Basic auth + JSON body.

    Returns ``None`` when the GitHub OAuth client credentials aren't
    configured; the caller treats that as a logged skip rather than an
    error.
    """
    # GitHub OAuth client creds may not be configured for every deploy
    # (this revoke is best-effort, integrations are mediated by Composio
    # in production). Fall back gracefully when they're absent.
    client_id = getattr(settings, "GITHUB_CLIENT_ID", None)
    client_secret = getattr(settings, "GITHUB_CLIENT_SECRET", None)
    if not client_id or not client_secret:
        return None
    return await client.request(
        "DELETE",
        f"https://api.github.com/applications/{client_id}/grant",
        auth=(client_id, client_secret),
        json={"access_token": token_value},
        headers={"Accept": "application/vnd.github+json"},
    )


_GOOGLE_PROVIDERS = {
    "google",
    "google_calendar",
    "gmail",
    "google_docs",
    "google_drive",
    "youtube",
}


async def _revoke_upstream(user_id: str, integration_id: str) -> None:
    """Best-effort revoke of the OAuth token at the provider.

    Failures are logged (wide event) but not raised: an upstream revoke
    failing must not block the user from disconnecting locally. A copy of
    the token that has already leaked from our DB remains live until the
    user revokes at the provider — this at least kills the happy-path copy.
    """
    try:
        token = await token_repository.get_token(
            user_id=user_id, provider=integration_id, renew_if_expired=False
        )
    except Exception as exc:
        log.info(
            "oauth_revoke_skipped_no_token",
            user_id=user_id,
            integration_id=integration_id,
            reason=str(exc),
        )
        return

    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    if not access_token and not refresh_token:
        return

    # Prefer refresh_token (revokes the whole grant for Google/Notion);
    # fall back to access_token if that's all we have. Slack/GitHub only
    # accept access tokens, so use that for them.
    grant_value = refresh_token or access_token
    bearer_value = access_token or refresh_token

    response: Optional[httpx.Response] = None
    try:
        async with httpx.AsyncClient(timeout=_REVOKE_TIMEOUT_SECONDS) as client:
            if integration_id in _GOOGLE_PROVIDERS:
                response = await _revoke_with_retry(
                    lambda: _revoke_form_token(
                        client, _GOOGLE_REVOKE, grant_value
                    )
                )
            elif integration_id == "notion":
                response = await _revoke_with_retry(
                    lambda: _revoke_form_token(
                        client,
                        "https://api.notion.com/v1/oauth/revoke",
                        grant_value,
                    )
                )
            elif integration_id == "slack":
                response = await _revoke_with_retry(
                    lambda: _revoke_slack(client, bearer_value)
                )
            elif integration_id == "github":
                response = await _revoke_with_retry(
                    lambda: _revoke_github(client, bearer_value)
                )
            else:
                # Unknown provider — caller wanted upstream revoke but we
                # don't know the endpoint shape. Fall through to log+skip.
                return
        if response is None:
            log.info(
                "oauth_revoke_skipped_no_credentials",
                user_id=user_id,
                integration_id=integration_id,
            )
            return
        if response.status_code >= 400:
            log.warning(
                "oauth_revoke_upstream_error",
                user_id=user_id,
                integration_id=integration_id,
                status_code=response.status_code,
            )
        else:
            log.info(
                "oauth_revoke_upstream_ok",
                user_id=user_id,
                integration_id=integration_id,
            )
    except Exception as exc:
        log.warning(
            "oauth_revoke_upstream_failed",
            user_id=user_id,
            integration_id=integration_id,
            error=str(exc),
        )


async def get_user_integrations(user_id: str) -> UserIntegrationsListResponse:
    """Get all integrations a user has added to their workspace."""
    user_integrations = []

    cursor = user_integrations_collection.find({"user_id": user_id}).sort(
        "created_at", -1
    )

    async for doc in cursor:
        try:
            user_int = UserIntegration(**doc)
            integration = await get_integration_details(user_int.integration_id)
            if integration:
                user_integrations.append(
                    UserIntegrationResponse(
                        integration_id=user_int.integration_id,
                        status=user_int.status,
                        created_at=user_int.created_at,
                        connected_at=user_int.connected_at,
                        integration=integration,
                    )
                )
        except Exception as e:
            log.warning(f"Failed to parse user integration: {e}")

    return UserIntegrationsListResponse(
        integrations=user_integrations,
        total=len(user_integrations),
    )


@Cacheable(key_pattern="tools:user:{user_id}:integrations", ttl=ONE_DAY_TTL)
async def get_user_connected_integrations(user_id: str) -> List[Dict[str, Any]]:
    """Get all user integrations (both 'created' and 'connected' status).

    Note: Despite the name, this now returns ALL integrations to allow
    status display in bots and other interfaces.
    """
    results = []
    cursor = user_integrations_collection.find({"user_id": user_id})

    async for doc in cursor:
        results.append(serialize_document(doc))

    return results


@CacheInvalidator(key_patterns=["tools:user:{user_id}:*", "tool_namespaces:{user_id}"])
async def add_user_integration(
    user_id: str,
    integration_id: str,
    initial_status: Optional[Literal["created", "connected"]] = None,
) -> UserIntegration:
    """Add an integration to user's workspace."""
    log.set(integration={"provider": integration_id, "action": "add_user_integration"})
    integration = await get_integration_details(integration_id)
    if not integration:
        raise ValueError(f"Integration '{integration_id}' not found")

    existing = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    if existing:
        raise ValueError(f"Integration '{integration_id}' already added to workspace")

    status: Literal["created", "connected"]
    if initial_status:
        status = initial_status
    else:
        status = "connected" if not integration.requires_auth else "created"
    connected_at = datetime.now(UTC) if status == "connected" else None

    user_integration = UserIntegration(
        user_id=user_id,
        integration_id=integration_id,
        status=status,
        created_at=datetime.now(UTC),
        connected_at=connected_at,
    )

    await user_integrations_collection.insert_one(user_integration.model_dump())
    log.info(f"User {user_id} added integration {integration_id} with status {status}")

    return user_integration


@CacheInvalidator(key_patterns=["tools:user:{user_id}:*", "tool_namespaces:{user_id}"])
async def remove_user_integration(user_id: str, integration_id: str) -> bool:
    """Remove an integration from user's workspace.

    Also attempts to revoke the OAuth token at the provider so the grant
    dies even if a copy of the token has already leaked from our DB.
    Upstream revoke failure is logged and does not block local deletion.
    """
    log.set(
        integration={"provider": integration_id, "action": "remove_user_integration"}
    )

    # Best-effort upstream revoke first; if it fails we still disconnect.
    await _revoke_upstream(user_id, integration_id)

    result = await user_integrations_collection.delete_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )

    if result.deleted_count > 0:
        log.info(f"User {user_id} removed integration {integration_id}")
        return True

    return False


async def check_user_has_integration(user_id: str, integration_id: str) -> bool:
    """Check if a user has added a specific integration."""
    doc = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    return doc is not None


@Cacheable(key_pattern="tools:user:{user_id}:integration_capabilities", ttl=ONE_DAY_TTL)
async def get_user_integration_capabilities(user_id: str) -> Dict[str, Any]:
    """
    Get capabilities (tools) for user's connected integrations + core tools.

    This is optimized for follow-up action generation to avoid passing
    all tools to the LLM. Instead, only tools from user's connected
    integrations plus core built-in tools are included.

    Returns:
        Dict with:
        - integration_names: List of connected integration names
        - tool_names: List of available tool names (core + integrations)
        - capabilities: Dict mapping integration_id -> list of tool info
    """

    # Get core tools that are always available (categories that don't require integration)
    tool_registry = await get_tool_registry()
    core_categories = tool_registry.get_core_categories()

    tool_names_set = set()

    # Add core tool names
    for category in core_categories:
        for tool in category.tools:
            tool_names_set.add(tool.name)

    # Get user's connected integrations
    connected_integrations = await get_user_connected_integrations(user_id)

    integration_names = []
    capabilities = {}

    for user_int_doc in connected_integrations:
        integration_id = user_int_doc.get("integration_id")
        if not integration_id:
            continue

        # Get integration details with tools
        integration = await get_integration_details(integration_id)
        if not integration:
            continue

        integration_names.append(integration.name)

        # Extract tool names and descriptions
        tools_info = []
        integration_tool: IntegrationTool
        for integration_tool in integration.tools:
            tool_names_set.add(integration_tool.name)
            tools_info.append(
                {
                    "name": integration_tool.name,
                    "description": integration_tool.description or "",
                }
            )

        if tools_info:
            capabilities[integration_id] = {
                "name": integration.name,
                "tools": tools_info,
            }

    return {
        "integration_names": integration_names,
        "tool_names": list(tool_names_set),
        "capabilities": capabilities,
    }
