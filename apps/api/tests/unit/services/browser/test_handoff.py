"""Tests for the Redis handoff bridge — one-time resolution, ownership, timeout."""

from typing import Any

import pytest

from app.constants.browser import (
    BROWSER_HANDOFF_CONV_KEY_PREFIX,
    BROWSER_HANDOFF_KEY_PREFIX,
    HANDOFF_KEY_TTL_SECONDS,
    HandoffDecision,
    HandoffStatus,
)
from app.schemas.browser import HandoffRecord
from app.services.analytics_service import AnalyticsEvents
from app.services.browser import handoff as handoff_mod
from app.services.browser.exceptions import BrowserHandoffNotOwned, BrowserUnavailableError


class _FakeRedisCache:
    """In-memory stand-in for redis_cache that also records every call so tests can assert on the exact key, ttl and model a seam was invoked with."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.set_calls: list[tuple[str, object, int | None, type[Any] | None]] = []
        self.get_calls: list[tuple[str, type[Any] | None]] = []
        self.delete_calls: list[str] = []
        self.set_if_absent_calls: list[tuple[str, object, int | None]] = []

    async def get(self, key, model=None):
        self.get_calls.append((key, model))
        return self.store.get(key)

    async def set(self, key, value, ttl=None, model=None):
        self.set_calls.append((key, value, ttl, model))
        self.store[key] = value
        return True

    async def delete(self, key):
        self.delete_calls.append(key)
        self.store.pop(key, None)

    async def set_if_absent(self, key, value, ttl=None, model=None):
        self.set_if_absent_calls.append((key, value, ttl))
        if key in self.store:
            return False
        self.store[key] = value
        return True


@pytest.fixture
def fake_cache(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    return fake


@pytest.fixture
def fake_redis(fake_cache):
    return fake_cache.store


async def test_continue(fake_redis):
    await handoff_mod.create_pending_handoff("h1", "user-1", "conv-h1")
    status = await handoff_mod.resolve_handoff("h1", HandoffDecision.CONTINUE, "user-1")
    assert status == HandoffStatus.COMPLETED


async def test_cancel(fake_redis):
    await handoff_mod.create_pending_handoff("h2", "user-1", "conv-h2")
    status = await handoff_mod.resolve_handoff("h2", HandoffDecision.CANCEL, "user-1")
    assert status == HandoffStatus.CANCELLED


async def test_resolution_is_one_time(fake_redis):
    await handoff_mod.create_pending_handoff("h3", "user-1", "conv-h3")
    first = await handoff_mod.resolve_handoff("h3", HandoffDecision.CONTINUE, "user-1")
    second = await handoff_mod.resolve_handoff("h3", HandoffDecision.CANCEL, "user-1")
    assert first == HandoffStatus.COMPLETED
    assert second == HandoffStatus.COMPLETED


async def test_unknown_returns_none(fake_redis):
    assert await handoff_mod.resolve_handoff("missing", HandoffDecision.CONTINUE, "u") is None


async def test_ownership_enforced(fake_redis):
    await handoff_mod.create_pending_handoff("h4", "owner", "conv-h4")
    with pytest.raises(BrowserHandoffNotOwned) as exc_info:
        await handoff_mod.resolve_handoff("h4", HandoffDecision.CONTINUE, "intruder")
    assert str(exc_info.value) == "Not authorized to resolve this handoff"


async def test_await_returns_when_resolved(fake_redis):
    await handoff_mod.create_pending_handoff("h5", "user-1", "conv-h5")
    await handoff_mod.resolve_handoff("h5", HandoffDecision.CONTINUE, "user-1")
    outcome = await handoff_mod.await_handoff("h5", timeout_seconds=5)
    assert outcome.status == HandoffStatus.COMPLETED


async def test_await_times_out(fake_redis, monkeypatch):
    monkeypatch.setattr(handoff_mod, "HANDOFF_POLL_INTERVAL_SECONDS", 0.001)
    await handoff_mod.create_pending_handoff("h6", "user-1", "conv-h6")
    outcome = await handoff_mod.await_handoff("h6", timeout_seconds=0)
    assert outcome.status == HandoffStatus.TIMEOUT


async def test_await_timeout_outcome_carries_no_message(fake_redis, monkeypatch):
    """A timeout is its own terminal state — it must not leak a stale note."""
    monkeypatch.setattr(handoff_mod, "HANDOFF_POLL_INTERVAL_SECONDS", 0.001)
    await handoff_mod.create_pending_handoff("h6b", "user-1", "conv-h6b", reason="checkout")
    outcome = await handoff_mod.await_handoff("h6b", timeout_seconds=0)
    assert outcome.message is None


async def test_await_handoff_polls_then_picks_up_resolution(fake_redis, monkeypatch):
    """The loop must actually re-check Redis on each poll tick, not just once."""
    await handoff_mod.create_pending_handoff("h6c", "user-1", "conv-h6c")

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Resolve on the first tick so the *next* loop iteration picks it up.
        await handoff_mod.resolve_handoff("h6c", HandoffDecision.CONTINUE, "user-1", "done")

    monkeypatch.setattr(handoff_mod.asyncio, "sleep", fake_sleep)

    outcome = await handoff_mod.await_handoff("h6c", timeout_seconds=30)

    assert outcome.status == HandoffStatus.COMPLETED
    assert outcome.message == "done"
    assert sleep_calls == [handoff_mod.HANDOFF_POLL_INTERVAL_SECONDS]


async def test_await_handoff_stops_exactly_at_deadline(fake_redis, monkeypatch):
    """Stop the loop at loop.time() == deadline using a strict less-than; one extra iteration could turn a timeout into a false completion."""
    await handoff_mod.create_pending_handoff("h6d", "user-1", "conv-h6d")
    await handoff_mod.resolve_handoff("h6d", HandoffDecision.CONTINUE, "user-1")

    class _FakeLoop:
        def __init__(self, times: list[float]) -> None:
            self._times = iter(times)

        def time(self) -> float:
            return next(self._times)

    fake_loop = _FakeLoop([100.0, 105.0])
    monkeypatch.setattr(handoff_mod.asyncio, "get_event_loop", lambda: fake_loop)

    outcome = await handoff_mod.await_handoff("h6d", timeout_seconds=5)

    assert outcome.status == HandoffStatus.TIMEOUT


async def test_get_conversation_pending_handoff_returns_the_stored_id(fake_redis):
    await handoff_mod.create_pending_handoff("h19", "user-1", "conv-h19")

    result = await handoff_mod.get_conversation_pending_handoff("conv-h19")

    assert result == "h19"


async def test_get_conversation_pending_handoff_reads_exact_key_and_model(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    await handoff_mod.create_pending_handoff("h19b", "user-1", "conv-h19b")
    fake.get_calls.clear()

    await handoff_mod.get_conversation_pending_handoff("conv-h19b")

    assert fake.get_calls == [(f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}conv-h19b", str)]


async def test_get_conversation_pending_handoff_returns_none_when_absent(fake_redis):
    assert await handoff_mod.get_conversation_pending_handoff("no-such-conv") is None


async def test_create_pending_handoff_persists_reason(fake_redis):
    await handoff_mod.create_pending_handoff("h7", "user-1", "conv-h7", reason="payment step")
    record = await handoff_mod.get_handoff("h7")
    assert record is not None
    assert record.reason == "payment step"
    assert record.status == HandoffStatus.PENDING


async def test_create_pending_handoff_defaults_reason_to_empty(fake_redis):
    await handoff_mod.create_pending_handoff("h7b", "user-1", "conv-h7b")
    record = await handoff_mod.get_handoff("h7b")
    assert record is not None
    assert record.reason == ""


async def test_create_pending_handoff_sets_conv_lookup(fake_redis):
    await handoff_mod.create_pending_handoff("h8", "user-1", "conv-h8")
    assert fake_redis[f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}conv-h8"] == "h8"


async def test_create_pending_handoff_skips_conv_lookup_when_no_conversation(fake_redis):
    await handoff_mod.create_pending_handoff("h8b", "user-1", "")
    assert all(not key.startswith(BROWSER_HANDOFF_CONV_KEY_PREFIX) for key in fake_redis)


async def test_create_pending_handoff_writes_conv_lookup_with_ttl(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)

    await handoff_mod.create_pending_handoff("h8c", "user-1", "conv-h8c")

    conv_key = f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}conv-h8c"
    conv_calls = [c for c in fake.set_calls if c[0] == conv_key]
    assert len(conv_calls) == 1
    key, value, ttl, _model = conv_calls[0]
    assert key == conv_key
    assert value == "h8c"
    assert ttl == HANDOFF_KEY_TTL_SECONDS


async def test_store_writes_exact_key_ttl_and_model(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    await handoff_mod.create_pending_handoff("h11", "user-1", "conv-h11")

    handoff_calls = [c for c in fake.set_calls if c[0] == f"{BROWSER_HANDOFF_KEY_PREFIX}h11"]
    assert len(handoff_calls) == 1
    key, value, ttl, model = handoff_calls[0]
    assert key == "browser:handoff:h11"
    assert isinstance(value, HandoffRecord)
    assert ttl == HANDOFF_KEY_TTL_SECONDS
    assert model is HandoffRecord


async def test_get_handoff_reads_exact_key_and_model(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    await handoff_mod.create_pending_handoff("h12", "user-1", "conv-h12")
    fake.get_calls.clear()

    await handoff_mod.get_handoff("h12")

    # A pending record also consults the settled marker, the decision of record.
    assert fake.get_calls == [
        ("browser:handoff:h12", HandoffRecord),
        ("browser:handoff:h12:settled", str),
    ]


async def test_get_handoff_unknown_returns_none(fake_redis):
    assert await handoff_mod.get_handoff("does-not-exist") is None


async def test_resolve_handoff_strips_whitespace_from_message(fake_redis):
    await handoff_mod.create_pending_handoff("h13", "user-1", "conv-h13")
    await handoff_mod.resolve_handoff(
        "h13", HandoffDecision.CONTINUE, "user-1", "  grab the item  "
    )
    record = await handoff_mod.get_handoff("h13")
    assert record is not None
    assert record.message == "grab the item"


async def test_resolve_handoff_blank_message_becomes_none(fake_redis):
    await handoff_mod.create_pending_handoff("h14", "user-1", "conv-h14")
    await handoff_mod.resolve_handoff("h14", HandoffDecision.CONTINUE, "user-1", "   ")
    record = await handoff_mod.get_handoff("h14")
    assert record is not None
    assert record.message is None


async def test_resolve_handoff_no_message_argument_becomes_none(fake_redis):
    """Fall through to no note when message is omitted entirely (None), not just when it is blank."""
    await handoff_mod.create_pending_handoff("h14b", "user-1", "conv-h14b")
    await handoff_mod.resolve_handoff("h14b", HandoffDecision.CONTINUE, "user-1")
    record = await handoff_mod.get_handoff("h14b")
    assert record is not None
    assert record.message is None


@pytest.fixture
def captured_events(monkeypatch):
    """Record every capture_event call the module makes, with its exact args."""
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(handoff_mod, "capture_event", lambda *args: calls.append(args))
    return calls


async def test_resolve_handoff_attributes_the_event_to_the_resolving_user(
    fake_redis, captured_events
):
    """Resolution can run in the stream's background task, where no request context exists — the user id must travel explicitly or the event lands on an anonymous profile and never joins that user's funnel."""
    await handoff_mod.create_pending_handoff("h-an1", "user-1", "conv-an1")
    await handoff_mod.resolve_handoff("h-an1", HandoffDecision.CONTINUE, "user-1", "buy the small")

    assert captured_events == [
        (
            "user-1",
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": HandoffDecision.CONTINUE.value, "with_note": True},
        )
    ]


async def test_resolve_handoff_event_reports_a_cancel_without_a_note(fake_redis, captured_events):
    await handoff_mod.create_pending_handoff("h-an2", "user-1", "conv-an2")
    await handoff_mod.resolve_handoff("h-an2", HandoffDecision.CANCEL, "user-1")

    assert captured_events == [
        (
            "user-1",
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": HandoffDecision.CANCEL.value, "with_note": False},
        )
    ]


async def test_resolve_handoff_deletes_conv_lookup(fake_redis):
    await handoff_mod.create_pending_handoff("h15", "user-1", "conv-h15")
    assert f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}conv-h15" in fake_redis
    await handoff_mod.resolve_handoff("h15", HandoffDecision.CONTINUE, "user-1")
    assert f"{BROWSER_HANDOFF_CONV_KEY_PREFIX}conv-h15" not in fake_redis


async def test_resolve_handoff_skips_conv_delete_when_no_conversation(monkeypatch):
    fake = _FakeRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    await handoff_mod.create_pending_handoff("h16", "user-1", "")

    await handoff_mod.resolve_handoff("h16", HandoffDecision.CONTINUE, "user-1")

    assert fake.delete_calls == []


async def test_resolve_handoff_logs_resolution_with_id_and_status(fake_redis, monkeypatch):
    logged: dict[str, object] = {}

    def fake_info(message: str, **kwargs: object) -> None:
        logged["message"] = message
        logged.update(kwargs)

    monkeypatch.setattr(handoff_mod.log, "info", fake_info)
    await handoff_mod.create_pending_handoff("h17", "user-1", "conv-h17")

    await handoff_mod.resolve_handoff("h17", HandoffDecision.CANCEL, "user-1")

    assert logged["handoff_id"] == "h17"
    assert logged["status"] == HandoffStatus.CANCELLED.value


async def test_resolve_handoff_settles_with_one_nx_write_for_the_handoffs_lifetime(fake_cache):
    await handoff_mod.create_pending_handoff("h20", "user-1", "conv-h20")

    await handoff_mod.resolve_handoff("h20", HandoffDecision.CANCEL, "user-1")

    assert fake_cache.set_if_absent_calls == [
        (handoff_mod._settled_key("h20"), "cancelled", HANDOFF_KEY_TTL_SECONDS)
    ]
    stored = fake_cache.store[handoff_mod._key("h20")]
    assert stored.status == HandoffStatus.CANCELLED  # the record itself, not just the marker


async def test_resolve_handoff_true_race_reports_the_decision_that_won_the_marker(fake_cache):
    """Both resolvers read PENDING; the one whose NX write loses reports the winner's decision."""
    await handoff_mod.create_pending_handoff("h22", "user-1", "conv-h22")
    original = fake_cache.set_if_absent

    async def lose_to_a_concurrent_cancel(key, value, ttl=None, model=None):
        fake_cache.store[key] = HandoffStatus.CANCELLED.value  # the other resolver lands first
        return await original(key, value, ttl, model)

    fake_cache.set_if_absent = lose_to_a_concurrent_cancel

    status = await handoff_mod.resolve_handoff("h22", HandoffDecision.CONTINUE, "user-1", "late")

    assert status == HandoffStatus.CANCELLED
    assert fake_cache.store[handoff_mod._key("h22")].status == HandoffStatus.PENDING


async def test_resolve_handoff_lost_race_reports_the_decision_that_landed_first(
    fake_redis, fake_cache
):
    """Card, chat reply and auto-resolver can all see PENDING; only the first write settles it."""
    await handoff_mod.create_pending_handoff("h19", "user-1", "conv-h19")
    fake_redis[handoff_mod._settled_key("h19")] = HandoffStatus.CANCELLED.value

    status = await handoff_mod.resolve_handoff("h19", HandoffDecision.CONTINUE, "user-1", "late")

    stored = fake_redis[handoff_mod._key("h19")]
    assert status == HandoffStatus.CANCELLED
    assert (handoff_mod._settled_key("h19"), str) in fake_cache.get_calls
    assert stored.status == HandoffStatus.PENDING  # the loser wrote nothing
    assert stored.message is None


async def test_a_claimed_marker_counts_as_settled_even_if_the_record_write_never_landed(fake_redis):
    """A resolver that died between the marker and the record must not strand the waiting run."""
    await handoff_mod.create_pending_handoff("h21", "user-1", "conv-h21")
    fake_redis[handoff_mod._settled_key("h21")] = HandoffStatus.COMPLETED.value

    record = await handoff_mod.get_handoff("h21")
    outcome = await handoff_mod.await_handoff("h21", timeout_seconds=1)

    assert record is not None
    assert record.status == HandoffStatus.COMPLETED
    assert outcome.status == HandoffStatus.COMPLETED


async def test_resolve_handoff_already_settled_keeps_original_status_and_note(fake_redis):
    await handoff_mod.create_pending_handoff("h18", "user-1", "conv-h18")
    first = await handoff_mod.resolve_handoff("h18", HandoffDecision.CANCEL, "user-1", "first note")
    second = await handoff_mod.resolve_handoff(
        "h18", HandoffDecision.CONTINUE, "user-1", "second note"
    )
    record = await handoff_mod.get_handoff("h18")
    assert first == HandoffStatus.CANCELLED
    assert second == HandoffStatus.CANCELLED
    assert record is not None
    assert record.message == "first note"


class _FailingRedisCache:
    """Redis whose writes never land — the outage case for the handoff bridge."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, key: str, model: object = None) -> object:
        return self.store.get(key)

    async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
        return False  # every write fails

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


async def test_persistence_failure_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """A handoff that was never persisted can never be resolved by the awaiting run — fail loudly instead of stranding both sides in a silent stall."""
    fake = _FailingRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    with pytest.raises(BrowserUnavailableError, match="persist handoff"):
        await handoff_mod.create_pending_handoff("h9", "user-1", "conv-h9")


async def test_persistence_failure_message_names_the_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the exact failure text (not just a substring) so the id and the 'storage unavailable' cause both stay intact for whoever reads the error."""
    fake = _FailingRedisCache()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)
    with pytest.raises(BrowserUnavailableError) as exc_info:
        await handoff_mod.create_pending_handoff("h9b", "user-1", "conv-h9b")
    assert str(exc_info.value) == "Could not persist handoff h9b (storage unavailable)."


async def test_store_succeeds_when_redis_confirms_the_write(fake_redis) -> None:
    """Do not raise when set() returns a truthy result, the inverse of the failure case."""
    await handoff_mod.create_pending_handoff("h9c", "user-1", "conv-h9c")
    record = await handoff_mod.get_handoff("h9c")
    assert record is not None
    assert record.status == HandoffStatus.PENDING


async def test_resolve_persistence_failure_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settling a handoff whose status write fails must not silently drop the user's decision — the endpoint surfaces the storage failure instead."""

    class _FlakyRedis:
        def __init__(self) -> None:
            self.store: dict[str, object] = {}
            self.fail_writes = False

        async def get(self, key: str, model: object = None) -> object:
            return self.store.get(key)

        async def set(self, key: str, value: object, ttl: int = 3600, model: object = None) -> bool:
            if self.fail_writes:
                return False
            self.store[key] = value
            return True

        async def delete(self, key: str) -> None:
            self.store.pop(key, None)

        async def set_if_absent(
            self, key: str, value: object, ttl: int = 3600, model: object = None
        ) -> bool:
            if self.fail_writes or key in self.store:
                return False
            self.store[key] = value
            return True

    fake = _FlakyRedis()
    monkeypatch.setattr(handoff_mod, "redis_cache", fake)

    fake.store["browser:handoff:h10"] = HandoffRecord(
        status=HandoffStatus.PENDING,
        user_id="user-1",
        conversation_id="conv-h10",
    )
    fake.store["browser:conv:conv-h10"] = "h10"
    fake.fail_writes = True
    with pytest.raises(BrowserUnavailableError) as exc_info:
        await handoff_mod.resolve_handoff("h10", HandoffDecision.CONTINUE, "user-1")
    assert str(exc_info.value) == "Could not persist handoff h10 (storage unavailable)."
