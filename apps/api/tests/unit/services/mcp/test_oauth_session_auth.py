"""StoredOAuthTokenAuth: what a live MCP session puts on the wire as its token changes underneath it."""

from collections.abc import Iterator

import httpx
import pytest

from app.services.mcp.oauth_session_auth import StoredOAuthTokenAuth

MCP_URL = "https://mcp.test/mcp"


class _TokenOwner:
    """Hands out the stored token, and a fresh one once asked about a rejected token."""

    def __init__(self, stored: str | None, after_refresh: str | None) -> None:
        self.stored = stored
        self.after_refresh = after_refresh
        self.asked: list[str | None] = []

    async def __call__(self, rejected: str | None) -> str | None:
        self.asked.append(rejected)
        if rejected is not None:
            self.stored = self.after_refresh
        return self.stored


class _Server:
    """Answers each request with the next status and records the raw headers it received."""

    def __init__(self, statuses: list[int]) -> None:
        self._statuses: Iterator[int] = iter(statuses)
        self.received: list[list[tuple[bytes, bytes]]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.received.append(list(request.headers.raw))
        return httpx.Response(next(self._statuses))


async def _send(owner: _TokenOwner, server: _Server) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(server.handle), auth=StoredOAuthTokenAuth(owner)
    ) as client:
        return await client.post(MCP_URL)


def _authorization(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    return [(name, value) for name, value in headers if name.lower() == b"authorization"]


@pytest.mark.unit
class TestStoredOAuthTokenAuth:
    async def test_a_request_carries_the_stored_token(self) -> None:
        owner, server = _TokenOwner("t1", "t2"), _Server([200])

        response = await _send(owner, server)

        assert response.status_code == 200
        assert [_authorization(h) for h in server.received] == [[(b"Authorization", b"Bearer t1")]]
        assert owner.asked == [None]

    async def test_a_rejected_token_is_refreshed_and_the_request_resent_once(self) -> None:
        owner, server = _TokenOwner("t1", "t2"), _Server([401, 200])

        response = await _send(owner, server)

        assert response.status_code == 200
        assert [_authorization(h) for h in server.received] == [
            [(b"Authorization", b"Bearer t1")],
            [(b"Authorization", b"Bearer t2")],
        ]
        assert owner.asked == [None, "t1"]

    @pytest.mark.parametrize("after_refresh", ["t1", None])
    async def test_no_resend_when_the_refresh_brings_no_new_token(
        self, after_refresh: str | None
    ) -> None:
        owner, server = _TokenOwner("t1", after_refresh), _Server([401])

        response = await _send(owner, server)

        assert response.status_code == 401
        assert len(server.received) == 1
        assert owner.asked == [None, "t1"]

    async def test_a_non_401_failure_never_refreshes(self) -> None:
        owner, server = _TokenOwner("t1", "t2"), _Server([403])

        response = await _send(owner, server)

        assert response.status_code == 403
        assert owner.asked == [None]

    async def test_without_a_token_nothing_is_sent_and_a_401_is_final(self) -> None:
        owner, server = _TokenOwner(None, "t2"), _Server([401])

        response = await _send(owner, server)

        assert response.status_code == 401
        assert _authorization(server.received[0]) == []
        assert owner.asked == [None]

    def test_a_sync_client_fails_loud(self) -> None:
        owner = _TokenOwner("t1", "t2")
        with (
            httpx.Client(
                transport=httpx.MockTransport(_Server([200]).handle),
                auth=StoredOAuthTokenAuth(owner),
            ) as client,
            pytest.raises(RuntimeError, match=r"MCP OAuth to mcp\.test needs an async client"),
        ):
            client.post(MCP_URL)
