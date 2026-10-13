"""Composio proxy client — single source of truth for proxy API calls.

Composio dropped support for returning OAuth access_token values in the
connected-accounts API. Every provider request must now go through
composio.tools.proxy(...), which authenticates server-side via the
connected_account_id.

This module wraps that flow so callers only need to supply user_id,
toolkit, and the request shape. The account is the one the current tool
call is scoped to, else the user's primary (see account_scope).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from composio import Composio
import composio_client

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.constants.log_tags import LogTag
from app.services.composio.account_scope import scoped_connected_account_id
from app.services.composio.dead_account import ConnectedAccountGoneError, is_dead_account_error
from app.utils.errors import AppError
from shared.py.wide_events import log

ProxyMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]


@dataclass(frozen=True, kw_only=True)
class ProxyRequest:
    """One provider call through Composio's proxy, addressed by user and toolkit.

    binary_body (a URL the proxy fetches and streams) and body are two
    different things and stay two fields; when both are given the binary one
    is what is sent.
    """

    user_id: str
    toolkit: str
    endpoint: str
    method: ProxyMethod
    body: object = None
    query: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    binary_body: dict[str, str] | None = None


class ProxyResponse(TypedDict):
    """A proxy call's full result: provider status, payload and headers.

    data is the provider's parsed JSON body, so it stays Any — every
    provider answers a different shape and this is the boundary where it lands.
    """

    status: int
    data: Any
    headers: dict[str, Any]


def _get_composio() -> Composio:
    # Lazy import to avoid a circular dependency between proxy_client and
    # the Composio service / custom-tool registry that imports it.
    from app.services.composio.composio_service import get_composio_service

    return get_composio_service().composio


def _resolve_connected_account_id(user_id: str, toolkit: str) -> str:
    if not user_id:
        log.error("composio_proxy_missing_user_id", toolkit=toolkit)
        raise AppError(
            message="Missing user_id for Composio proxy request",
            why="proxy_request requires a user_id to resolve the connected account",
            status_code=500,
            meta={"toolkit": toolkit},
        )
    return scoped_connected_account_id(user_id, toolkit)


def _build_parameters(
    headers: dict[str, str] | None,
    query: Mapping[str, object] | None,
) -> list[dict[str, str]]:
    params: list[dict[str, str]] = []
    if headers:
        for name, value in headers.items():
            params.append({"name": name, "type": "header", "value": str(value)})
    if query:
        for name, query_value in query.items():
            narrowed: object = query_value
            if isinstance(narrowed, (list, tuple)):
                for item in narrowed:
                    params.append({"name": name, "type": "query", "value": str(item)})
            elif narrowed is not None:
                params.append({"name": name, "type": "query", "value": str(narrowed)})
    return params


def _proxy_failure(request: ProxyRequest, error: Exception) -> AppError:
    """Log and build the loud failure for a proxy call the SDK or transport could not complete."""
    log.error(
        f"{LogTag.COMPOSIO} composio.tools.proxy raised",
        user_id=request.user_id,
        toolkit=request.toolkit,
        method=request.method,
        endpoint=request.endpoint,
        error=str(error),
        error_type=type(error).__name__,
    )
    return AppError(
        message=f"Composio tools.proxy failed: {error}",
        why="SDK or transport error while calling the provider",
        status_code=502,
        meta={
            "toolkit": request.toolkit,
            "endpoint": request.endpoint,
            "method": request.method,
            "exception": str(error),
        },
    )


def _proxy_call(request: ProxyRequest) -> ProxyResponse:
    """Send a proxy request and return its status, data and headers."""
    log.set(
        composio_proxy={
            "toolkit": request.toolkit,
            "endpoint": request.endpoint,
            "method": request.method,
            "user_id": request.user_id,
        }
    )

    connected_account_id = _resolve_connected_account_id(request.user_id, request.toolkit)
    parameters = _build_parameters(request.headers, request.query)

    proxy_kwargs: dict[str, Any] = {
        "endpoint": request.endpoint,
        "method": request.method,
        "connected_account_id": connected_account_id,
    }
    if parameters:
        proxy_kwargs["parameters"] = parameters
    if request.binary_body is not None:
        proxy_kwargs["binary_body"] = request.binary_body
    elif request.body is not None:
        proxy_kwargs["body"] = request.body

    try:
        response = _get_composio().tools.proxy(**proxy_kwargs)
    except AppError:
        raise
    except composio_client.NotFoundError as e:
        if not is_dead_account_error(e):
            raise _proxy_failure(request, e) from e
        raise ConnectedAccountGoneError(request.toolkit, str(e)) from e
    except Exception as e:
        raise _proxy_failure(request, e) from e

    status = int(response.status)
    if status >= 400:
        # A provider 401 means Composio's token was rejected and refresh failed —
        # the integration needs reconnecting, not the GAIA session. Surface as 403
        # so the web client routes to reconnect instead of a false "sign in again".
        gaia_status = 403 if status == 401 else (status if 400 <= status < 600 else 502)
        raise AppError(
            message=f"{request.toolkit} API error ({status})",
            why="The provider rejected the request",
            status_code=gaia_status,
            code=INTEGRATION_NOT_CONNECTED if status == 401 else "",
            public={"toolkit": request.toolkit},
            # The endpoint, the provider's status and its raw body are
            # diagnostics: the wide event gets them, the caller never does.
            meta={
                "endpoint": request.endpoint,
                "method": request.method,
                "provider_status": status,
                "provider_response": response.data,
            },
        )

    # Normalize header keys to lowercase. Upstream APIs return mixed casing
    # (e.g. LinkedIn's `X-RestLi-Id`) and Composio forwards them as a plain
    # dict, so callers doing `headers["x-restli-id"]` would otherwise miss.
    raw_headers = response.headers or {}
    normalized_headers = {str(k).lower(): v for k, v in raw_headers.items()}

    return ProxyResponse(
        status=status,
        data=response.data,
        headers=normalized_headers,
    )


def proxy_request_sync(request: ProxyRequest) -> Any:
    """Send an authenticated request to a provider via Composio's proxy.

    Returns the parsed data field; raises AppError on a non-2xx response or
    no active connection. Return stays Any: one function fronts every
    provider's differently-shaped JSON, and annotating it -> object measured
    47 new mypy errors across 16 files (mostly "object has no attribute get").
    """
    response: ProxyResponse = _proxy_call(request)
    return response["data"]


def proxy_request_full_sync(request: ProxyRequest) -> ProxyResponse:
    """Like proxy_request_sync but returns {status, data, headers}.

    Use when the caller needs response headers (e.g. LinkedIn's
    x-restli-id for the new resource ID).
    """
    return _proxy_call(request)


async def proxy_request(request: ProxyRequest) -> Any:
    """Async variant of proxy_request_sync. Runs the SDK call in a worker thread."""
    return await asyncio.to_thread(proxy_request_sync, request)


__all__ = [
    "ProxyMethod",
    "ProxyResponse",
    "proxy_request",
    "proxy_request_sync",
    "proxy_request_full_sync",
]
