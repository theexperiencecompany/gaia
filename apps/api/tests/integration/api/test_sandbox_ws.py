"""Integration tests for the sandbox bridge socket + session registry.

Covers the Task 5 contract: short-lived sandbox JWT auth (bad token
rejected), the connect-time paywall, stale-token cutoff after recreate,
per-user ownership on every open, and open/msg/close frame relay in both
directions.

The WS upgrade itself cannot go through the httpx-based ``test_client``
fixture (ASGI transport has no websocket support), so the handler is driven
directly with a mocked socket — the same approach as
``tests/unit/api/test_device_ws.py`` — while token mint/verify, the
registry, and the connector run for real against mocked Redis. One smoke
test boots the full app through ``test_client`` to prove the router mounts
cleanly alongside the device router.
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
from fastapi.exceptions import WebSocketException
from jose import jwt
import pytest

from app.api.v1.endpoints import sandbox_ws as ws_module
from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.constants.sandbox import SANDBOX_TOKEN_AUDIENCE
from app.db.redis import redis_cache
from app.models.mcp_config import MCPConfig
from app.services.mcp.device_connector import DeviceConnector
from app.services.mcp.sandbox_connector import SandboxConnectionError, SandboxConnector
from app.services.mcp.sandbox_exec import SandboxExecError, run_sandbox_command
from app.services.sandbox.bridge_registry import (
    SandboxOwnershipError,
    check_sandbox_ownership,
    get_online_sandbox_id,
    get_sandbox_owner,
    is_online,
    mark_offline,
    mark_online,
    sandbox_down_channel,
    send_sandbox_down,
)
from app.services.sandbox.bridge_token import (
    mint_sandbox_bridge_token,
    verify_sandbox_bridge_token,
)

pytestmark = pytest.mark.integration

_MODULE = "app.api.v1.endpoints.sandbox_ws"
_USER = "user-1"
_SANDBOX = "sbx-1"


@pytest.fixture(autouse=True)
def fresh_redis_client():
    """Each test starts with no Redis, so presence checks read offline, not a leaked loop."""
    redis_cache.redis = None
    yield
    redis_cache.redis = None


def _fake_redis(**overrides):
    redis = MagicMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.exists = AsyncMock(return_value=0)
    redis.publish = AsyncMock()
    redis.eval = AsyncMock()
    for key, value in overrides.items():
        setattr(redis, key, value)
    return redis


def _socket(token: str | None = "sandbox-jwt") -> MagicMock:
    ws = MagicMock()
    ws.headers = {"authorization": f"Bearer {token}"} if token else {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _repo(sandbox_id: str | None) -> MagicMock:
    record = MagicMock()
    record.sandbox_id = sandbox_id
    repo = MagicMock()
    repo.get_for_user = AsyncMock(return_value=record)
    return repo


async def _run_handler(ws, *, repo=None, paid=True):
    """Drive the WS handler with relay loops stubbed; the receive loop disconnects at once."""
    with (
        patch.object(ws_module, "e2b_sandbox_repository", repo or _repo(None)),
        patch.object(ws_module, "is_paid", AsyncMock(return_value=paid)),
        patch.object(ws_module, "mark_online", AsyncMock()),
        patch.object(ws_module, "mark_offline", AsyncMock()),
        patch.object(ws_module, "sandbox_connection_manager", MagicMock()),
        patch.object(ws_module, "_down_relay", AsyncMock()),
        patch.object(ws_module, "_heartbeat", AsyncMock()),
        patch.object(
            ws_module, "_receive_loop", AsyncMock(side_effect=WebSocketDisconnect())
        ) as receive,
    ):
        await ws_module.sandbox_ws(ws)
    return receive


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


class TestSandboxBridgeToken:
    def test_mint_verify_roundtrip(self):
        token, expires_in = mint_sandbox_bridge_token(_USER, _SANDBOX)
        assert expires_in == 15 * 60
        assert verify_sandbox_bridge_token(token) == {
            "user_id": _USER,
            "sandbox_id": _SANDBOX,
        }

    def test_tampered_token_rejected(self):
        token, _ = mint_sandbox_bridge_token(_USER, _SANDBOX)
        assert verify_sandbox_bridge_token(token + "x") is None

    def test_wrong_role_rejected(self):
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": _USER,
                "sandbox_id": _SANDBOX,
                "aud": SANDBOX_TOKEN_AUDIENCE,
                "role": "device",
                "iat": now,
                "exp": now + timedelta(minutes=15),
            },
            settings.AGENT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        assert verify_sandbox_bridge_token(token) is None

    def test_expired_token_rejected(self):
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": _USER,
                "sandbox_id": _SANDBOX,
                "aud": SANDBOX_TOKEN_AUDIENCE,
                "role": "sandbox",
                "iat": now - timedelta(minutes=30),
                "exp": now - timedelta(minutes=15),
            },
            settings.AGENT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        assert verify_sandbox_bridge_token(token) is None


# ---------------------------------------------------------------------------
# Handler auth + gates
# ---------------------------------------------------------------------------


class TestSandboxWsAuth:
    async def test_missing_token_rejected(self):
        ws = _socket(token=None)
        with pytest.raises(WebSocketException) as exc:
            await ws_module.sandbox_ws(ws)
        assert exc.value.code == 1008
        assert exc.value.reason == "sandbox token missing or invalid"
        ws.accept.assert_not_awaited()

    async def test_bad_token_rejected(self):
        ws = _socket(token="not-a-jwt")
        with pytest.raises(WebSocketException) as exc:
            await ws_module.sandbox_ws(ws)
        assert exc.value.code == 1008
        assert exc.value.reason == "sandbox token missing or invalid"
        ws.accept.assert_not_awaited()

    async def test_stale_token_rejected_after_recreate(self):
        """A bridge redialing on a pre-recreate token is cut off: the record names the new sandbox."""
        token, _ = mint_sandbox_bridge_token(_USER, "sbx-old")
        ws = _socket(token=token)
        with pytest.raises(WebSocketException) as exc:
            await _run_handler(ws, repo=_repo("sbx-new"))
        assert exc.value.code == 1008
        assert exc.value.reason == "sandbox token stale"
        ws.accept.assert_not_awaited()

    async def test_free_user_rejected_before_accept(self):
        token, _ = mint_sandbox_bridge_token(_USER, _SANDBOX)
        ws = _socket(token=token)
        manager = MagicMock()
        mark_online_mock = AsyncMock()
        with (
            patch.object(ws_module, "e2b_sandbox_repository", _repo(None)),
            patch.object(ws_module, "is_paid", AsyncMock(return_value=False)),
            patch.object(ws_module, "sandbox_connection_manager", manager),
            patch.object(ws_module, "mark_online", mark_online_mock),
        ):
            with pytest.raises(WebSocketException) as exc:
                await ws_module.sandbox_ws(ws)
        assert exc.value.code == 1008
        assert exc.value.reason == "subscription required"
        ws.accept.assert_not_awaited()
        manager.add.assert_not_called()
        mark_online_mock.assert_not_awaited()

    async def test_paid_user_connects_and_presence_claimed(self):
        token, _ = mint_sandbox_bridge_token(_USER, _SANDBOX)
        ws = _socket(token=token)
        manager = MagicMock()
        mark_online_mock = AsyncMock()
        mark_offline_mock = AsyncMock()
        with (
            patch.object(ws_module, "e2b_sandbox_repository", _repo(None)),
            patch.object(ws_module, "is_paid", AsyncMock(return_value=True)),
            patch.object(ws_module, "sandbox_connection_manager", manager),
            patch.object(ws_module, "mark_online", mark_online_mock),
            patch.object(ws_module, "mark_offline", mark_offline_mock),
            patch.object(ws_module, "_down_relay", AsyncMock()),
            patch.object(ws_module, "_heartbeat", AsyncMock()),
            patch.object(
                ws_module, "_receive_loop", AsyncMock(side_effect=WebSocketDisconnect())
            ) as receive,
        ):
            await ws_module.sandbox_ws(ws)
        ws.accept.assert_awaited_once()
        manager.add.assert_called_once_with(_SANDBOX, ws)
        mark_online_mock.assert_awaited_once_with(_SANDBOX, _USER)
        assert receive.await_args.args[:2] == (ws, _SANDBOX)


# ---------------------------------------------------------------------------
# Registry: online set + ownership
# ---------------------------------------------------------------------------


class TestBridgeRegistry:
    async def test_mark_online_claims_presence_and_owner(self):
        redis = _fake_redis()
        with patch.object(redis_cache, "redis", redis):
            await mark_online(_SANDBOX, _USER)
        assert redis.set.await_count == 2
        channels = {call.args[0] for call in redis.set.await_args_list}
        assert channels == {f"sandbox:presence:{_SANDBOX}", f"sandbox:owner:{_USER}"}

    async def test_owner_and_reverse_lookup(self):
        redis = _fake_redis(get=AsyncMock(side_effect=[_USER.encode(), _SANDBOX.encode()]))
        with patch.object(redis_cache, "redis", redis):
            assert await get_sandbox_owner(_SANDBOX) == _USER
            assert await get_online_sandbox_id(_USER) == _SANDBOX
        assert redis.get.await_args_list[0].args == (f"sandbox:presence:{_SANDBOX}",)
        assert redis.get.await_args_list[1].args == (f"sandbox:owner:{_USER}",)

    async def test_ownership_match_passes(self):
        redis = _fake_redis(get=AsyncMock(return_value=_USER))
        with patch.object(redis_cache, "redis", redis):
            await check_sandbox_ownership(_SANDBOX, _USER)

    async def test_ownership_mismatch_rejected(self):
        redis = _fake_redis(get=AsyncMock(return_value="other-user"))
        with patch.object(redis_cache, "redis", redis):
            with pytest.raises(SandboxOwnershipError, match="not an active sandbox owned by"):
                await check_sandbox_ownership(_SANDBOX, _USER)

    async def test_offline_sandbox_rejected(self):
        with patch.object(redis_cache, "redis", None):
            assert await is_online(_SANDBOX) is False
            with pytest.raises(SandboxOwnershipError, match="offline"):
                await check_sandbox_ownership(_SANDBOX, _USER)

    async def test_send_down_publishes_to_sandbox_channel(self):
        redis = _fake_redis()
        with patch.object(redis_cache, "redis", redis):
            await send_sandbox_down(_SANDBOX, {"t": "mcp.open", "sid": "s1"})
        redis.publish.assert_awaited_once()
        channel, _payload = redis.publish.await_args.args
        assert channel == sandbox_down_channel(_SANDBOX) == "sandbox:down:sbx-1"

    async def test_send_down_without_redis_raises(self):
        with patch.object(redis_cache, "redis", None):
            with pytest.raises(RuntimeError, match="no Redis connection"):
                await send_sandbox_down(_SANDBOX, {"t": "ping"})

    async def test_mark_offline_compares_and_deletes(self):
        redis = _fake_redis()
        with patch.object(redis_cache, "redis", redis):
            await mark_offline(_SANDBOX, _USER)
        assert redis.eval.await_count == 2


# ---------------------------------------------------------------------------
# Relay: down subscribe + upstream routing
# ---------------------------------------------------------------------------


class TestSandboxRelay:
    async def test_down_relay_subscribes_to_sandbox_channel(self):
        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()

        async def _no_message(**kwargs):
            await asyncio.sleep(0.01)

        pubsub.get_message = AsyncMock(side_effect=_no_message)
        redis = MagicMock()
        redis.pubsub = MagicMock(return_value=pubsub)
        event = asyncio.Event()
        with patch.object(redis_cache, "redis", redis):
            task = asyncio.create_task(ws_module._down_relay(_socket(), _SANDBOX, event))
            await asyncio.wait_for(event.wait(), 5)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        pubsub.subscribe.assert_awaited_once_with("sandbox:down:sbx-1")

    async def test_upstream_frames_routed_by_pod(self):
        msg = json.dumps({"t": "mcp.msg", "sid": "s1", "pod": "pod-a", "data": "{}"})
        stdout = json.dumps({"t": "exec.stdout", "sid": "s2", "pod": "pod-b", "data": "hi"})
        no_pod = json.dumps({"t": "mcp.msg", "sid": "s3", "data": "{}"})
        hello = json.dumps({"t": "hello", "servers": ["splitwise"]})
        ws = _socket()
        ws.receive_text = AsyncMock(
            side_effect=[msg, stdout, no_pod, hello, "not-json", WebSocketDisconnect()]
        )
        published: list[str] = []

        async def _publish(pod: str, raw: str) -> None:
            published.append(raw)

        with patch.object(ws_module, "publish_up_to_pod", AsyncMock(side_effect=_publish)):
            with pytest.raises(WebSocketDisconnect):
                await ws_module._receive_loop(ws, _SANDBOX, {"last_recv": 0.0})
        assert published == [msg, stdout]

    async def test_down_relay_without_redis_still_signals_ready(self):
        ready = asyncio.Event()
        with patch.object(redis_cache, "redis", None):
            await ws_module._down_relay(_socket(), _SANDBOX, ready)
        assert ready.is_set()


# ---------------------------------------------------------------------------
# MCP transport: sandbox:// routing + ownership
# ---------------------------------------------------------------------------


class TestSandboxTransport:
    def test_connector_reuses_device_framing(self):
        connector = SandboxConnector(_SANDBOX, _USER, "splitwise")
        assert isinstance(connector, DeviceConnector)
        assert connector.public_identifier == "sandbox:sbx-1:splitwise"

    async def test_connector_send_down_addresses_sandbox_channel(self):
        from app.services.mcp import sandbox_connector as connector_module

        redis = _fake_redis()
        with (
            patch.object(redis_cache, "redis", redis),
            patch.object(connector_module, "send_sandbox_down", AsyncMock()) as send_down_mock,
        ):
            connector = SandboxConnector(_SANDBOX, _USER, "splitwise")
            await connector._send_down({"t": "mcp.close", "sid": "s1"})
        send_down_mock.assert_awaited_once_with(_SANDBOX, {"t": "mcp.close", "sid": "s1"})

    async def test_connector_offline_raises_connection_error(self):
        connector = SandboxConnector(_SANDBOX, _USER, "splitwise")
        with patch.object(redis_cache, "redis", None):
            with pytest.raises(SandboxConnectionError, match="no Redis connection"):
                await connector._check_online()

    async def test_connector_wrong_owner_raises(self):
        redis = _fake_redis(
            exists=AsyncMock(return_value=1),
            get=AsyncMock(return_value="other-user"),
        )
        connector = SandboxConnector(_SANDBOX, _USER, "splitwise")
        with patch.object(redis_cache, "redis", redis):
            with pytest.raises(SandboxConnectionError, match="not an active sandbox owned"):
                await connector._check_online()

    async def test_open_session_routes_sandbox_transport(self):
        from app.services.mcp.mcp_client import MCPClient, _parse_sandbox_server_url

        assert _parse_sandbox_server_url("sandbox://user-1/splitwise") == (
            "user-1",
            "splitwise",
        )
        with pytest.raises(ValueError, match="Malformed sandbox server URL"):
            _parse_sandbox_server_url("sandbox://only-user")

        client = MCPClient(_USER)
        config = MCPConfig(server_url="sandbox://user-1/splitwise", transport="sandbox")
        sentinel = object()
        with patch.object(
            MCPClient, "_build_sandbox_client", AsyncMock(return_value=sentinel)
        ) as build:
            result = await client._open_session("splitwise", config)
        assert result is sentinel
        build.assert_awaited_once()

    async def test_build_sandbox_client_rejects_other_users_url(self):
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(_USER)
        config = MCPConfig(server_url="sandbox://other-user/splitwise", transport="sandbox")
        with pytest.raises(ValueError, match="not an active sandbox owned"):
            await client._build_sandbox_client("splitwise", config)

    async def test_build_sandbox_client_rejects_offline_sandbox(self):
        import app.services.mcp.mcp_client as client_module
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(_USER)
        config = MCPConfig(server_url="sandbox://user-1/splitwise", transport="sandbox")
        with patch.object(client_module, "get_online_sandbox_id", AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="offline"):
                await client._build_sandbox_client("splitwise", config)

    async def test_build_sandbox_client_wraps_live_sandbox(self):
        import app.services.mcp.mcp_client as client_module
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(_USER)
        config = MCPConfig(server_url="sandbox://user-1/splitwise", transport="sandbox")
        with (
            patch.object(client_module, "get_online_sandbox_id", AsyncMock(return_value=_SANDBOX)),
            patch.object(
                MCPClient, "_wrap_tunnel_connector", AsyncMock(return_value="wrapped")
            ) as wrap,
        ):
            result = await client._build_sandbox_client("splitwise", config)
        assert result == "wrapped"
        connector = wrap.await_args.args[1]
        assert isinstance(connector, SandboxConnector)
        assert connector.sandbox_id == _SANDBOX
        assert connector.user_id == _USER
        assert connector.server_key == "splitwise"


# ---------------------------------------------------------------------------
# Exec-open ownership
# ---------------------------------------------------------------------------


class TestSandboxExecOwnership:
    async def test_exec_open_rejected_for_other_users_sandbox(self):
        redis = _fake_redis(get=AsyncMock(return_value="other-user"))
        with (
            patch.object(redis_cache, "redis", redis),
            patch("app.services.mcp.sandbox_exec.send_sandbox_down", AsyncMock()) as send_down_mock,
        ):
            with pytest.raises(SandboxExecError, match="not an active sandbox owned"):
                await run_sandbox_command(_USER, _SANDBOX, "echo hi")
        send_down_mock.assert_not_awaited()

    async def test_exec_open_rejected_when_offline(self):
        with patch.object(redis_cache, "redis", None):
            with pytest.raises(SandboxExecError, match="no Redis connection"):
                await run_sandbox_command(_USER, _SANDBOX, "echo hi")


# ---------------------------------------------------------------------------
# Router mount smoke
# ---------------------------------------------------------------------------


class TestSandboxRouterMount:
    async def test_app_boots_with_sandbox_router(self, test_client):
        response = await test_client.get("/api/v1/ping")
        assert response.status_code == 200
