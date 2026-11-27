"""Bearer auth for a live MCP session that asks the token owner for the access token on every request.

A session outlives its access token, so it never holds one: each request reads the
current token, and a 401 asks the owner to refresh the rejected one and retries once.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

import httpx

TokenSource = Callable[[str | None], Awaitable[str | None]]


class StoredOAuthTokenAuth(httpx.Auth):
    """httpx auth whose token comes from a TokenSource; the argument is the token the server just rejected."""

    def __init__(self, token_source: TokenSource) -> None:
        self._token_source = token_source

    def sync_auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        raise RuntimeError(
            f"MCP OAuth to {request.url.host} needs an async client; the token store is async only"
        )

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token = await self._token_source(None)
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        response = yield request

        if response.status_code != httpx.codes.UNAUTHORIZED or not token:
            return
        fresh = await self._token_source(token)
        if fresh and fresh != token:
            request.headers["Authorization"] = f"Bearer {fresh}"
            yield request
