"""Composio proxy client — single source of truth for proxy API calls.

Composio dropped support for returning OAuth `access_token` values in the
connected-accounts API. Every provider request must now go through
`composio.tools.proxy(...)`, which authenticates server-side via the
`connected_account_id`.

This module wraps that flow so callers only need to supply `user_id`,
`toolkit`, and the request shape. The connected account lookup is cached
in-process with a short TTL since the value is stable for the lifetime
of a connection.
"""

from __future__ import annotations

import asyncio
from threading import Lock
import time
from typing import Any, Literal

from app.config.oauth_config import get_composio_social_configs
from app.utils.errors import AppError
from shared.py.wide_events import log

ProxyMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]

_CONNECTED_ACCOUNT_CACHE_TTL_SECONDS = 600

_connected_account_cache: dict[tuple[str, str], tuple[str, float]] = {}
_cache_lock = Lock()


def _get_composio() -> Any:
    # Lazy import to avoid a circular dependency between proxy_client and
    # the Composio service / custom-tool registry that imports it.
    from app.services.composio.composio_service import get_composio_service

    return get_composio_service().composio


def _toolkit_to_auth_config_id(toolkit: str) -> str | None:
    target = toolkit.upper()
    for cfg in get_composio_social_configs().values():
        if cfg.toolkit and cfg.toolkit.upper() == target:
            return cfg.auth_config_id
    return None


def _resolve_connected_account_id(user_id: str, toolkit: str) -> str:
    if not user_id:
        raise AppError(
            message="Missing user_id for Composio proxy request",
            why="proxy_request requires a user_id to resolve the connected account",
            status_code=500,
            meta={"toolkit": toolkit},
        )

    cache_key = (user_id, toolkit.upper())
    now = time.time()
    with _cache_lock:
        cached = _connected_account_cache.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    auth_config_id = _toolkit_to_auth_config_id(toolkit)
    if not auth_config_id:
        raise AppError(
            message=f"Unknown Composio toolkit: {toolkit}",
            why="No registered auth config matches this toolkit slug",
            status_code=500,
            meta={"toolkit": toolkit, "user_id": user_id},
        )

    composio = _get_composio()
    try:
        accounts = composio.connected_accounts.list(
            user_ids=[user_id],
            auth_config_ids=[auth_config_id],
            limit=10,
        )
    except AppError:
        raise
    except Exception as e:
        raise AppError(
            message=f"Composio connected_accounts.list failed: {e}",
            why="SDK or transport error while resolving the connected account",
            status_code=502,
            meta={"toolkit": toolkit, "user_id": user_id, "exception": str(e)},
        ) from e

    active = next(
        (
            acc
            for acc in accounts.items
            if acc.status == "ACTIVE" and not acc.auth_config.is_disabled
        ),
        None,
    )
    if active is None:
        raise AppError(
            message=f"No active {toolkit} connection",
            why=f"User {user_id} has no active connected account for {toolkit}",
            fix=f"Reconnect the {toolkit} integration",
            status_code=401,
            meta={"toolkit": toolkit, "user_id": user_id},
        )

    with _cache_lock:
        _connected_account_cache[cache_key] = (
            active.id,
            now + _CONNECTED_ACCOUNT_CACHE_TTL_SECONDS,
        )
    return active.id


def _build_parameters(
    headers: dict[str, str] | None,
    query: dict[str, Any] | None,
) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    if headers:
        for name, value in headers.items():
            params.append({"name": name, "type": "header", "value": str(value)})
    if query:
        for name, value in query.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                for item in value:
                    params.append({"name": name, "type": "query", "value": str(item)})
            else:
                params.append({"name": name, "type": "query", "value": str(value)})
    return params


def _proxy_call(
    *,
    user_id: str,
    toolkit: str,
    endpoint: str,
    method: ProxyMethod,
    body: Any | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    binary_body: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Internal: send a proxy request and return data/status/headers as a dict."""
    log.set(
        composio_proxy={
            "toolkit": toolkit,
            "endpoint": endpoint,
            "method": method,
            "user_id": user_id,
        }
    )

    connected_account_id = _resolve_connected_account_id(user_id, toolkit)
    parameters = _build_parameters(headers, query)

    proxy_kwargs: dict[str, Any] = {
        "endpoint": endpoint,
        "method": method,
        "connected_account_id": connected_account_id,
    }
    if parameters:
        proxy_kwargs["parameters"] = parameters
    if binary_body is not None:
        proxy_kwargs["binary_body"] = binary_body
    elif body is not None:
        proxy_kwargs["body"] = body

    try:
        response = _get_composio().tools.proxy(**proxy_kwargs)
    except AppError:
        raise
    except Exception as e:
        raise AppError(
            message=f"Composio tools.proxy failed: {e}",
            why="SDK or transport error while calling the provider",
            status_code=502,
            meta={
                "toolkit": toolkit,
                "endpoint": endpoint,
                "method": method,
                "exception": str(e),
            },
        ) from e

    status = int(response.status)
    if status >= 400:
        raise AppError(
            message=f"{toolkit} API error ({status})",
            why=f"Provider returned non-2xx for {method} {endpoint}",
            status_code=status if 400 <= status < 600 else 502,
            meta={
                "toolkit": toolkit,
                "endpoint": endpoint,
                "method": method,
                "provider_status": status,
                "provider_response": response.data,
            },
        )

    # Normalize header keys to lowercase. Upstream APIs return mixed casing
    # (e.g. LinkedIn's `X-RestLi-Id`) and Composio forwards them as a plain
    # dict, so callers doing `headers["x-restli-id"]` would otherwise miss.
    raw_headers = response.headers or {}
    normalized_headers = {str(k).lower(): v for k, v in raw_headers.items()}

    return {
        "status": status,
        "data": response.data,
        "headers": normalized_headers,
    }


def proxy_request_sync(
    *,
    user_id: str,
    toolkit: str,
    endpoint: str,
    method: ProxyMethod,
    body: Any | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    binary_body: dict[str, str] | None = None,
) -> Any:
    """Send an authenticated request to a provider via Composio's proxy.

    Returns the parsed `data` field from the proxy response. Raises
    `AppError` on non-2xx provider responses or when the user has no
    active connection for the toolkit.
    """
    return _proxy_call(
        user_id=user_id,
        toolkit=toolkit,
        endpoint=endpoint,
        method=method,
        body=body,
        query=query,
        headers=headers,
        binary_body=binary_body,
    )["data"]


def proxy_request_full_sync(
    *,
    user_id: str,
    toolkit: str,
    endpoint: str,
    method: ProxyMethod,
    body: Any | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    binary_body: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Like `proxy_request_sync` but returns `{status, data, headers}`.

    Use when the caller needs response headers (e.g. LinkedIn's
    `x-restli-id` for the new resource ID).
    """
    return _proxy_call(
        user_id=user_id,
        toolkit=toolkit,
        endpoint=endpoint,
        method=method,
        body=body,
        query=query,
        headers=headers,
        binary_body=binary_body,
    )


async def proxy_request(
    *,
    user_id: str,
    toolkit: str,
    endpoint: str,
    method: ProxyMethod,
    body: Any | None = None,
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    binary_body: dict[str, str] | None = None,
) -> Any:
    """Async variant of `proxy_request_sync`. Runs the SDK call in a worker thread."""
    return await asyncio.to_thread(
        proxy_request_sync,
        user_id=user_id,
        toolkit=toolkit,
        endpoint=endpoint,
        method=method,
        body=body,
        query=query,
        headers=headers,
        binary_body=binary_body,
    )


def invalidate_connected_account_cache(
    user_id: str | None = None, toolkit: str | None = None
) -> None:
    """Clear cached `connected_account_id` entries.

    Call after a user disconnects or reconnects an integration so the next
    proxy request re-resolves the account.
    """
    with _cache_lock:
        if user_id is None and toolkit is None:
            _connected_account_cache.clear()
            return
        normalized_toolkit = toolkit.upper() if toolkit else None
        keys_to_remove = [
            key
            for key in _connected_account_cache
            if (user_id is None or key[0] == user_id)
            and (normalized_toolkit is None or key[1] == normalized_toolkit)
        ]
        for key in keys_to_remove:
            _connected_account_cache.pop(key, None)


__all__ = [
    "ProxyMethod",
    "proxy_request",
    "proxy_request_sync",
    "proxy_request_full_sync",
    "invalidate_connected_account_cache",
]
