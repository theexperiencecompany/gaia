"""Unit tests for the runtime-config subscriber (cross-pod invalidation, F4).

The credential service publishes ``{"scope": "provider:<name>"}`` on
RUNTIME_CONFIG_CHANNEL; this listener must apply each remote update through the
service's pod-local invalidation (cache drop → registry reset → aux LLM caches)
without publishing anything itself, ignore malformed payloads, and never take
boot down — no Redis or a dropped connection degrades to a log line.
"""

import asyncio
import contextlib
import json
from typing import Any

import pytest

from app.core import runtime_config_subscriber as subscriber_module
from app.db.redis import redis_cache
from app.services.providers.provider_credentials_service import RUNTIME_CONFIG_CHANNEL


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
    """Record invalidate_locally calls (the fan-out itself is covered by the
    provider-credentials-service tests; these pin the listener's wiring)."""
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


def test_parse_provider_strips_prefix() -> None:
    assert subscriber_module._parse_provider('{"scope": "provider:tavily"}') == "tavily"


def test_parse_provider_handles_bytes() -> None:
    assert subscriber_module._parse_provider(b'{"scope": "provider:ollama"}') == "ollama"


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
    """No Redis provider → the listener disables itself with a loud log instead
    of crashing boot (start() still returns cleanly)."""
    monkeypatch.setattr(redis_cache, "redis", None)

    await asyncio.wait_for(subscriber_module._listener_loop(), timeout=1.0)
