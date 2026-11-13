"""The desktop request/response bridge: a tool parks a request, the desktop app answers over Redis."""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cache import (
    DESKTOP_REQUEST_PREFIX,
    DESKTOP_REQUEST_TTL_GRACE_SECONDS,
    DESKTOP_RESULT_CHANNEL_PREFIX,
)
from app.services.desktop import bridge
from app.services.desktop.bridge import (
    ERROR_REDIS_UNAVAILABLE,
    DesktopRequestForbiddenError,
    DesktopRequestNotFoundError,
    DesktopToolOutcome,
    relay_desktop_result,
    request_desktop_action,
)

pytestmark = pytest.mark.unit

_REPLY = {
    "type": "message",
    "data": json.dumps({"ok": True, "data": {"text": "hi"}, "error": None}),
}


def _pubsub(messages: list[dict[str, object] | None]) -> MagicMock:
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.get_message = AsyncMock(side_effect=messages)
    return pubsub


@contextmanager
def _redis(pubsub: MagicMock, stored: object = None) -> Iterator[SimpleNamespace]:
    """Stand in for redis_cache: a key store plus the pub/sub client under it."""
    cache = SimpleNamespace(
        redis=MagicMock(pubsub=MagicMock(return_value=pubsub), publish=AsyncMock()),
        set=AsyncMock(),
        get=AsyncMock(return_value=stored),
        delete=AsyncMock(),
    )
    with patch.object(bridge, "redis_cache", cache):
        yield cache


class TestRequestDesktopAction:
    async def test_the_request_is_parked_for_its_owner_and_answered_by_the_desktop(self) -> None:
        pubsub = _pubsub([_REPLY])
        publish_chunk = AsyncMock()
        with (
            _redis(pubsub) as cache,
            patch.object(bridge.stream_manager, "publish_chunk", publish_chunk),
        ):
            outcome = await request_desktop_action(
                stream_id="s1", user_id="u1", tool="read_clipboard"
            )

        assert outcome == DesktopToolOutcome(ok=True, data={"text": "hi"}, error=None)
        request_key, pending = cache.set.await_args.args
        request_id = request_key.removeprefix(DESKTOP_REQUEST_PREFIX)
        assert pending == {"user_id": "u1", "stream_id": "s1", "tool": "read_clipboard"}
        assert cache.set.await_args.kwargs == {
            "ttl": int(bridge.DESKTOP_TOOL_TIMEOUT_SECONDS) + DESKTOP_REQUEST_TTL_GRACE_SECONDS
        }
        pubsub.subscribe.assert_awaited_once_with(f"{DESKTOP_RESULT_CHANNEL_PREFIX}{request_id}")
        stream_id, frame = publish_chunk.await_args.args
        assert stream_id == "s1"
        assert json.loads(frame.removeprefix("data: "))["desktop_tool_request"]["request_id"] == (
            request_id
        )
        pubsub.get_message.assert_awaited_with(
            ignore_subscribe_messages=True, timeout=bridge._PUBSUB_POLL_SECONDS
        )
        cache.delete.assert_awaited_once_with(request_key)
        pubsub.unsubscribe.assert_awaited_once_with(f"{DESKTOP_RESULT_CHANNEL_PREFIX}{request_id}")

    async def test_noise_on_the_channel_is_skipped_until_a_real_result_arrives(self) -> None:
        bytes_reply = {
            "type": "message",
            "data": json.dumps({"ok": False, "error": "denied"}).encode(),
        }
        pubsub = _pubsub(
            [
                None,
                {"type": "subscribe", "data": b"1"},
                {"type": "message", "data": "{not json"},
                bytes_reply,
            ]
        )
        with _redis(pubsub), patch.object(bridge.stream_manager, "publish_chunk", AsyncMock()):
            outcome = await request_desktop_action(
                stream_id="s1", user_id="u1", tool="read_clipboard"
            )

        assert outcome == DesktopToolOutcome(ok=False, data=None, error="denied")
        assert pubsub.get_message.await_count == 4

    async def test_without_redis_the_action_fails_without_publishing(self) -> None:
        publish_chunk = AsyncMock()
        with (
            patch.object(bridge, "redis_cache", SimpleNamespace(redis=None)),
            patch.object(bridge.stream_manager, "publish_chunk", publish_chunk),
        ):
            outcome = await request_desktop_action(stream_id="s1", user_id="u1", tool="open_url")

        assert outcome == DesktopToolOutcome(ok=False, error=ERROR_REDIS_UNAVAILABLE)
        publish_chunk.assert_not_awaited()


class TestRelayDesktopResult:
    async def test_the_owner_resolves_the_request_exactly_once(self) -> None:
        pending = {"user_id": "u1", "stream_id": "s1", "tool": "read_clipboard"}
        with _redis(_pubsub([]), stored=pending) as cache:
            await relay_desktop_result(
                request_id="req-1", user_id="u1", ok=True, data={"text": "hi"}, error=None
            )

        cache.get.assert_awaited_once_with(f"{DESKTOP_REQUEST_PREFIX}req-1")
        cache.delete.assert_awaited_once_with(f"{DESKTOP_REQUEST_PREFIX}req-1")
        channel, payload = cache.redis.publish.await_args.args
        assert channel == f"{DESKTOP_RESULT_CHANNEL_PREFIX}req-1"
        assert json.loads(payload) == {"ok": True, "data": {"text": "hi"}, "error": None}

    async def test_an_expired_or_resolved_request_is_gone(self) -> None:
        with _redis(_pubsub([]), stored=None) as cache:
            with pytest.raises(DesktopRequestNotFoundError):
                await relay_desktop_result(
                    request_id="req-1", user_id="u1", ok=True, data=None, error=None
                )

        cache.redis.publish.assert_not_awaited()

    async def test_another_users_result_is_refused(self) -> None:
        pending = {"user_id": "u1", "stream_id": "s1", "tool": "read_clipboard"}
        with _redis(_pubsub([]), stored=pending) as cache:
            with pytest.raises(DesktopRequestForbiddenError):
                await relay_desktop_result(
                    request_id="req-1", user_id="intruder", ok=True, data=None, error=None
                )

        cache.delete.assert_not_awaited()
        cache.redis.publish.assert_not_awaited()
