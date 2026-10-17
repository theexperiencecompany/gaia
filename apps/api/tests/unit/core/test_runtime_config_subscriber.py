"""Unit tests for the runtime-config subscriber (cross-pod invalidation).

The credential service publishes provider-scope updates on the runtime config
channel; this listener applies each through pod-local invalidation without
publishing itself, ignores malformed payloads, and never takes boot down.
"""

import asyncio
import contextlib
import json
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest
from redis.asyncio.client import PubSub

from app.constants.log_tags import LogTag
from app.core import runtime_config_subscriber as subscriber_module
from app.db.redis import redis_cache
from app.services.runtime.config_updates import RUNTIME_CONFIG_CHANNEL
from tests.helpers import WideEventRecorder, captured_wide_event


class FakePubSub:
    """Redis pubsub double: replays a queued message list, then idles."""

    def __init__(self, messages: list[Any]) -> None:
        self.messages = list(messages)
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = None
    ) -> Any:
        if not self.messages:
            # Idle like a real subscription would; the test cancels the task.
            await asyncio.sleep(3600)
            return None
        return self.messages.pop(0)

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed.append(channel)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_task_state():
    """Isolate the module-level task handle between tests."""
    subscriber_module._subscriber_task = None
    yield
    subscriber_module._subscriber_task = None


@pytest.fixture
def applied(monkeypatch) -> list[str]:
    """Record invalidate_locally calls.

    The fan-out itself is covered by the provider-credentials-service tests; these
    pin the listener's wiring.
    """
    calls: list[str] = []

    def _record(provider: str) -> None:
        calls.append(provider)

    monkeypatch.setattr(subscriber_module, "invalidate_locally", _record)
    return calls


# ---------------------------------------------------------------------------
# payload parsing + dispatch
# ---------------------------------------------------------------------------


async def test_valid_payload_applies_invalidation(applied: list[str]) -> None:
    await subscriber_module._apply_update(json.dumps({"scope": "provider:openrouter"}))

    assert applied == ["openrouter"]


async def test_bytes_payload_is_decoded(applied: list[str]) -> None:
    await subscriber_module._apply_update(b'{"scope": "provider:gemini"}')

    assert applied == ["gemini"]


async def test_malformed_json_is_ignored_not_fatal(applied: list[str]) -> None:
    await subscriber_module._apply_update("not-json{")

    assert applied == []


async def test_non_provider_scope_is_ignored(applied: list[str]) -> None:
    await subscriber_module._apply_update(json.dumps({"scope": "something-else"}))

    assert applied == []


async def test_non_dict_payload_is_ignored(applied: list[str]) -> None:
    await subscriber_module._apply_update('["not", "an", "object"]')

    assert applied == []


async def test_a_list_naming_scope_is_not_a_payload(applied: list[str]) -> None:
    await subscriber_module._apply_update('["scope"]')

    assert applied == []


async def test_undecodable_bytes_are_replaced_not_fatal(applied: list[str]) -> None:
    await subscriber_module._apply_update(b'{"scope": "provider:g\xffx"}')

    assert applied == ["g\ufffdx"]


async def test_malformed_json_leaves_a_warning(applied: list[str]) -> None:
    async with captured_wide_event() as event:
        await subscriber_module._apply_update("not-json{")

    assert event["warnings"] == [
        {
            "msg": f"{LogTag.API} Malformed runtime-config update ignored",
            "channel": RUNTIME_CONFIG_CHANNEL,
            "error": "Expecting value: line 1 column 1 (char 0)",
        }
    ]


async def test_each_update_emits_its_scope_and_flags_an_unknown_one(
    applied: list[str],
) -> None:
    recorder = WideEventRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        await subscriber_module._apply_update(json.dumps({"scope": "something-else"}))

    event = recorder.event("runtime_config_update")
    assert event["runtime_config"] == {"scope": "something-else"}
    assert event["warnings"] == [
        {
            "msg": f"{LogTag.API} Runtime-config update with unknown scope ignored",
            "channel": RUNTIME_CONFIG_CHANNEL,
            "scope": "something-else",
        }
    ]


async def test_a_composio_auth_config_save_on_another_pod_drops_this_pods_set(
    applied: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    dropped: list[int] = []
    monkeypatch.setattr(
        subscriber_module, "invalidate_auth_config_cache", lambda: dropped.append(1)
    )

    await subscriber_module._apply_update(json.dumps({"scope": "composio_auth_configs"}))

    assert dropped == [1]
    assert applied == []


# ---------------------------------------------------------------------------
# consume loop
# ---------------------------------------------------------------------------


async def test_consume_applies_each_message_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, applied: list[str]
) -> None:
    pubsub = FakePubSub(
        [
            {"type": "message", "data": json.dumps({"scope": "provider:openrouter"})},
            {"type": "message", "data": b'{"scope": "provider:custom"}'},
        ]
    )

    class FakeRedis:
        def pubsub(self) -> FakePubSub:
            return pubsub

    monkeypatch.setattr(redis_cache, "redis", FakeRedis())

    task = asyncio.create_task(subscriber_module._consume())
    for _ in range(100):
        if len(applied) == 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert applied == ["openrouter", "custom"]
    assert pubsub.subscribed == [RUNTIME_CONFIG_CHANNEL]
    assert pubsub.unsubscribed == [RUNTIME_CONFIG_CHANNEL]
    assert pubsub.closed is True


async def test_consume_skips_non_messages_and_keeps_listening(
    monkeypatch: pytest.MonkeyPatch, applied: list[str]
) -> None:
    pubsub = FakePubSub(
        [
            None,
            {"type": "subscribe", "data": 1},
            {"type": "message"},
            {"type": "message", "data": json.dumps({"scope": "provider:openrouter"})},
        ]
    )

    class FakeRedis:
        def pubsub(self) -> FakePubSub:
            return pubsub

    monkeypatch.setattr(redis_cache, "redis", FakeRedis())

    task = asyncio.create_task(subscriber_module._consume())
    for _ in range(100):
        if applied:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert applied == ["openrouter"]


async def test_an_idle_subscriber_waits_for_a_message_instead_of_polling(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
    applied: list[str],
) -> None:
    reads = 0
    open_pubsub = fake_redis.pubsub

    def counting_pubsub() -> PubSub:
        pubsub = open_pubsub()
        read = pubsub.get_message

        async def counted(**kwargs: Any) -> Any:
            nonlocal reads
            reads += 1
            # Yield first, so a loop that polls without waiting cannot starve this test.
            await asyncio.sleep(0)
            return await read(**kwargs)

        monkeypatch.setattr(pubsub, "get_message", counted)
        return pubsub

    monkeypatch.setattr(fake_redis, "pubsub", counting_pubsub)

    task = asyncio.create_task(subscriber_module._consume())
    for _ in range(200):
        await asyncio.sleep(0)
    idle_reads = reads
    await fake_redis.publish(RUNTIME_CONFIG_CHANNEL, json.dumps({"scope": "provider:gemini"}))
    for _ in range(100):
        if applied:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # The subscribe ack, then one read that blocks until the publish.
    assert idle_reads == 2
    assert applied == ["gemini"]


async def test_a_dropped_connection_surfaces_even_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenPubSub(FakePubSub):
        async def get_message(
            self, ignore_subscribe_messages: bool = False, timeout: float | None = None
        ) -> Any:
            raise ConnectionError("connection lost")

        async def unsubscribe(self, channel: str) -> None:
            raise RuntimeError("socket already closed")

    class FakeRedis:
        def pubsub(self) -> BrokenPubSub:
            return BrokenPubSub([])

    monkeypatch.setattr(redis_cache, "redis", FakeRedis())

    with pytest.raises(ConnectionError, match="connection lost"):
        await subscriber_module._consume()


async def test_consume_without_redis_exits_quietly(
    monkeypatch: pytest.MonkeyPatch, applied: list[str]
) -> None:
    monkeypatch.setattr(redis_cache, "redis", None)

    await asyncio.wait_for(subscriber_module._consume(), timeout=1.0)

    assert applied == []


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------


async def test_start_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[int] = []

    async def _wait_forever() -> None:
        started.append(1)
        await asyncio.Event().wait()

    monkeypatch.setattr(redis_cache, "redis", object())
    monkeypatch.setattr(subscriber_module, "_consume", _wait_forever)

    subscriber_module.start_runtime_config_subscriber()
    first = subscriber_module._subscriber_task
    assert first is not None
    await asyncio.sleep(0)  # let the listener body run once

    subscriber_module.start_runtime_config_subscriber()

    assert subscriber_module._subscriber_task is first
    assert started == [1]

    await subscriber_module.stop_runtime_config_subscriber()
    assert subscriber_module._subscriber_task is None


async def test_stop_without_start_is_a_noop() -> None:
    await subscriber_module.stop_runtime_config_subscriber()


async def test_listener_loop_disabled_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable the listener loudly with no Redis; boot must not crash."""
    monkeypatch.setattr(redis_cache, "redis", None)

    await asyncio.wait_for(subscriber_module._listener_loop(), timeout=1.0)


async def test_listener_loop_without_redis_warns_it_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_cache, "redis", None)

    async with captured_wide_event() as event:
        await asyncio.wait_for(subscriber_module._listener_loop(), timeout=1.0)

    assert [w["msg"] for w in event["warnings"]] == [
        f"{LogTag.API} Runtime-config subscriber disabled (no Redis connection)"
    ]


async def test_listener_loop_resubscribes_after_each_drop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[int] = []
    third_attempt = asyncio.Event()

    async def _flaky_consume() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError(f"drop {len(attempts)}")
        third_attempt.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(redis_cache, "redis", object())
    monkeypatch.setattr(subscriber_module, "_consume", _flaky_consume)
    monkeypatch.setattr(subscriber_module, "_RESUBSCRIBE_SECONDS", 0)

    async with captured_wide_event() as event:
        task = asyncio.create_task(subscriber_module._listener_loop())
        await asyncio.wait_for(third_attempt.wait(), timeout=1.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert event["warnings"] == [
        {
            "msg": f"{LogTag.API} Runtime-config subscriber dropped, resubscribing",
            "error": f"drop {n}",
            "error_type": "ConnectionError",
        }
        for n in (1, 2)
    ]
