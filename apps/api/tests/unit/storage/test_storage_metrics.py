"""FS metrics: per-op aggregation, the Prometheus surface, and fs_timer's guarantees.

Every storage call site funnels through ``fs_timer`` / ``record_fs_op``. Two
failure shapes matter and are both invisible at runtime: the aggregate silently
under-reporting (a slow op that never shows up on a dashboard, an error counted
as a success), and the metrics layer itself breaking the operation it measures
(a swallowed exception, a leaked in-flight gauge that makes every panel read
"stuck").

Known ContextVar wart, verified in-process and pinned by the two isolation
tests below: a task spawned *before* the request records its first FS op gets a
bucket of its own that nobody ever flushes, so its ops reach Prometheus but
never the wide event. Spawned *after*, the same task shares the bucket and is
billed to the request. Whether a fire-and-forget op shows up in ``fs={}`` is
therefore decided by unrelated ordering earlier in the turn.

Boundaries mocked: nothing. The Prometheus collectors are in-process, so the
real registry is read back via ``REGISTRY.get_sample_value``; each test uses a
unique op name so its samples cannot collide with another test's. The only
patched objects are deliberately-broken collector stubs used to prove the
registry-failure guards actually guard.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
import time
from typing import Any
from uuid import uuid4

from prometheus_client import REGISTRY, Gauge
import pytest

from app.services.storage import metrics as m
from app.services.storage.metrics import (
    FsOps,
    _register_once,
    add_fs_bytes,
    flush_fs_metrics,
    fs_timer,
    peek_fs_metrics,
    record_fs_op,
    set_sandbox_pool_size,
)


@pytest.fixture(autouse=True)
def _clean_bucket() -> Iterator[None]:
    """Start every test from an empty ContextVar bucket.

    Sync tests mutate the caller's context directly, so without this a leftover
    bucket from a previous test would make `flush` assertions read another
    test's numbers.
    """
    m._metrics_var.set(None)
    yield
    m._metrics_var.set(None)


@pytest.fixture
def op() -> str:
    return f"test_op_{uuid4().hex}"


def in_flight(op: str) -> float | None:
    return REGISTRY.get_sample_value("fs_op_in_flight", {"operation": op})


def total(op: str, mode: str = "none", status: str = "ok") -> float | None:
    return REGISTRY.get_sample_value(
        "fs_op_total", {"operation": op, "mode": mode, "status": status}
    )


def duration_sum(op: str, mode: str = "none", status: str = "ok") -> float | None:
    return REGISTRY.get_sample_value(
        "fs_op_duration_seconds_sum", {"operation": op, "mode": mode, "status": status}
    )


def byte_total(op: str) -> float | None:
    return REGISTRY.get_sample_value("fs_op_bytes_total", {"operation": op})


class _BrokenCollector:
    """Stands in for a collector whose registry access blows up."""

    def labels(self, **_kw: str) -> Any:
        raise RuntimeError("registry exploded")


class _BrokenDecCollector:
    """inc() works, dec() explodes — the paired-state inconsistency case."""

    class _Child:
        def inc(self, _n: float = 1) -> None:
            return None

        def dec(self, _n: float = 1) -> None:
            raise RuntimeError("dec exploded")

    def labels(self, **_kw: str) -> _BrokenDecCollector._Child:
        return self._Child()


# ── record_fs_op: the wide-event aggregate ───────────────────────────


def test_repeated_calls_for_one_op_collapse_into_a_single_summed_entry(op: str) -> None:
    # A per-call entry (or a last-write-wins overwrite) would make the wide
    # event report one FS call per turn instead of the real fan-out.
    record_fs_op(op, duration_ms=10.0)
    record_fs_op(op, duration_ms=5.5)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 2
    assert snap["total_ms"] == 15.5


def test_max_ms_keeps_the_slowest_call_when_a_faster_one_follows(op: str) -> None:
    # `max_ms = duration_ms` instead of `max(...)` reads fine and hides exactly
    # the outlier the panel exists to surface.
    record_fs_op(op, duration_ms=50.0)
    record_fs_op(op, duration_ms=1.0)

    assert peek_fs_metrics()[op]["max_ms"] == 50.0


def test_an_op_that_never_failed_reports_no_error_fields(op: str) -> None:
    record_fs_op(op, duration_ms=1.0)

    snap = peek_fs_metrics()[op]
    assert snap["errors"] == 0
    assert "last_error_type" not in snap


def test_errors_are_counted_separately_from_calls_and_stamp_the_latest_type(op: str) -> None:
    # `errors` must not be conflated with `count` — the dashboards divide one by
    # the other to get a failure rate.
    record_fs_op(op, duration_ms=1.0)
    record_fs_op(op, duration_ms=1.0, error=ValueError("bad"))
    record_fs_op(op, duration_ms=1.0, error=TimeoutError("slow"))

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 3
    assert snap["errors"] == 2
    assert snap["last_error_type"] == "TimeoutError"


def test_an_op_reporting_no_bytes_omits_the_bytes_key_rather_than_reporting_zero(op: str) -> None:
    # Wire contract: conditionally-emitted keys are absent, not zero, so LogQL
    # can distinguish "op moves no bytes" from "op moved nothing this time".
    record_fs_op(op, duration_ms=1.0)

    assert "bytes" not in peek_fs_metrics()[op]


def test_bytes_from_repeated_writes_accumulate_into_one_total(op: str) -> None:
    record_fs_op(op, duration_ms=1.0, byte_count=100)
    record_fs_op(op, duration_ms=1.0, byte_count=23)

    assert peek_fs_metrics()[op]["bytes"] == 123


def test_a_later_label_value_replaces_the_earlier_one_for_the_same_key(op: str) -> None:
    # Documented last-write-wins. Appending instead would grow the wide event
    # field unboundedly across a long request.
    record_fs_op(op, duration_ms=1.0, mode="warm")
    record_fs_op(op, duration_ms=1.0, mode="cold")

    assert peek_fs_metrics()[op]["labels"] == {"mode": "cold"}


def test_an_op_with_no_labels_omits_the_labels_key(op: str) -> None:
    record_fs_op(op, duration_ms=1.0)

    assert "labels" not in peek_fs_metrics()[op]


def test_millisecond_totals_are_rounded_so_float_noise_stays_out_of_the_log_line(op: str) -> None:
    record_fs_op(op, duration_ms=1.23456)

    snap = peek_fs_metrics()[op]
    assert snap["total_ms"] == 1.235
    assert snap["max_ms"] == 1.235


def test_a_prometheus_failure_still_leaves_the_op_recorded_on_the_wide_event(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The ContextVar bucket is the canonical record and is updated *before* the
    # Prometheus emit. Reordering them would let one registry hiccup erase the
    # entire fs={} field for that request.
    monkeypatch.setattr(m, "_FS_OP_DURATION_SECONDS", _BrokenCollector())

    record_fs_op(op, duration_ms=7.0, byte_count=5)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 1
    assert snap["total_ms"] == 7.0
    assert snap["bytes"] == 5


def test_a_prometheus_failure_is_swallowed_instead_of_propagating_to_the_caller(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # record_fs_op is called from inside `finally` blocks all over storage —
    # raising here would replace the real exception with a metrics error.
    monkeypatch.setattr(m, "_FS_OP_TOTAL", _BrokenCollector())

    record_fs_op(op, duration_ms=1.0)


# ── record_fs_op: the Prometheus surface ─────────────────────────────


def test_each_recorded_op_increments_the_lifetime_counter_exactly_once(op: str) -> None:
    record_fs_op(op, duration_ms=1.0)
    assert total(op) == 1.0
    record_fs_op(op, duration_ms=1.0)
    assert total(op) == 2.0


def test_a_failed_op_is_labelled_error_and_never_lands_in_the_ok_series(op: str) -> None:
    # An inverted status ternary makes every failure look like a success on the
    # error-rate panel — the single most consequential label in this module.
    record_fs_op(op, duration_ms=1.0, error=OSError("boom"))

    assert total(op, status="error") == 1.0
    assert total(op, status="ok") is None


def test_an_op_without_an_acquire_mode_is_labelled_none_rather_than_empty(op: str) -> None:
    record_fs_op(op, duration_ms=1.0)

    assert total(op, mode="none") == 1.0


def test_the_caller_supplied_mode_label_reaches_prometheus(op: str) -> None:
    record_fs_op(op, duration_ms=1.0, mode="warm_pool")

    assert total(op, mode="warm_pool") == 1.0
    assert total(op, mode="none") is None


def test_an_empty_mode_label_falls_back_to_none_instead_of_creating_a_blank_series(
    op: str,
) -> None:
    # `labels.get("mode") or "none"` — a switch to `labels.get("mode", "none")`
    # would silently split the series between "" and "none".
    record_fs_op(op, duration_ms=1.0, mode="")

    assert total(op, mode="none") == 1.0
    assert total(op, mode="") is None


def test_durations_reach_prometheus_in_seconds_not_milliseconds(op: str) -> None:
    # Prometheus histograms are conventionally in seconds and the buckets here
    # top out at 60. Emitting milliseconds would push every real op into +Inf.
    record_fs_op(op, duration_ms=2500.0)

    assert duration_sum(op) == 2.5


def test_an_op_reporting_zero_bytes_never_creates_a_byte_series(op: str) -> None:
    record_fs_op(op, duration_ms=1.0, byte_count=0)

    assert byte_total(op) is None


def test_reported_bytes_are_added_to_the_byte_counter(op: str) -> None:
    record_fs_op(op, duration_ms=1.0, byte_count=4096)

    assert byte_total(op) == 4096.0


def test_the_last_seen_gauge_carries_wall_clock_time_not_a_monotonic_reading(op: str) -> None:
    # "last seen N minutes ago" columns subtract this from now(); a monotonic
    # clock would render every op as decades stale.
    before = time.time()
    record_fs_op(op, duration_ms=1.0)

    seen = REGISTRY.get_sample_value("fs_op_last_seen_unix_seconds", {"operation": op})
    assert seen is not None
    assert before <= seen <= time.time()


def test_a_real_op_constant_records_under_its_own_stable_name() -> None:
    # Op names are the dashboard's pivot key; recording under a mangled name
    # would leave every panel empty while the code looks fine.
    record_fs_op(FsOps.TOOL_READ, duration_ms=1.0)

    assert "tool_read" in peek_fs_metrics()


# ── add_fs_bytes ─────────────────────────────────────────────────────


def test_adding_bytes_after_the_fact_does_not_inflate_the_call_count(op: str) -> None:
    # The write tool times the round-trip then reports the payload size. If this
    # bumped `count`, every write would be reported as two FS operations.
    add_fs_bytes(op, 512)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 0
    assert snap["total_ms"] == 0.0
    assert snap["bytes"] == 512


def test_bytes_added_after_a_timed_op_land_on_the_same_entry(op: str) -> None:
    record_fs_op(op, duration_ms=3.0)
    add_fs_bytes(op, 64)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 1
    assert snap["bytes"] == 64


@pytest.mark.parametrize("n", [0, -1, -4096])
def test_a_non_positive_byte_count_records_nothing_at_all(op: str, n: int) -> None:
    # Dropping the guard would create a phantom zero-count entry for the op and
    # (for negatives) make the byte total run backwards.
    add_fs_bytes(op, n)

    assert peek_fs_metrics() == {}
    assert byte_total(op) is None


def test_added_bytes_reach_the_prometheus_byte_counter(op: str) -> None:
    add_fs_bytes(op, 10)
    add_fs_bytes(op, 5)

    assert byte_total(op) == 15.0


def test_a_broken_byte_counter_does_not_break_the_caller_or_the_aggregate(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(m, "_FS_OP_BYTES_TOTAL", _BrokenCollector())

    add_fs_bytes(op, 99)

    assert peek_fs_metrics()[op]["bytes"] == 99


# ── flush / peek / isolation ─────────────────────────────────────────


def test_flushing_returns_the_metrics_once_and_leaves_the_bucket_empty(op: str) -> None:
    # Without the reset a long-lived worker loop re-attaches the same numbers to
    # every subsequent wide event, multiplying the reported FS cost.
    record_fs_op(op, duration_ms=1.0)

    assert flush_fs_metrics()[op]["count"] == 1
    assert flush_fs_metrics() == {}


def test_peeking_leaves_the_bucket_intact_for_the_later_flush(op: str) -> None:
    record_fs_op(op, duration_ms=1.0)

    assert peek_fs_metrics()[op]["count"] == 1
    assert flush_fs_metrics()[op]["count"] == 1


def test_a_request_that_touched_no_files_flushes_an_empty_dict() -> None:
    # `log.set(fs=flush_fs_metrics())` runs unconditionally on every request.
    assert flush_fs_metrics() == {}
    assert peek_fs_metrics() == {}


def test_recording_after_a_flush_starts_a_fresh_bucket(op: str) -> None:
    record_fs_op(op, duration_ms=10.0)
    flush_fs_metrics()
    record_fs_op(op, duration_ms=1.0)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 1
    assert snap["total_ms"] == 1.0


async def test_two_concurrent_requests_do_not_see_each_others_fs_metrics() -> None:
    # The whole ContextVar design exists for this: an ARQ worker running many
    # tasks on one loop must not bill one job's FS time to another.
    seen: dict[str, dict[str, Any]] = {}

    async def request(name: str) -> None:
        record_fs_op(name, duration_ms=1.0)
        await asyncio.sleep(0)
        seen[name] = dict(flush_fs_metrics())

    await asyncio.gather(request("op_a"), request("op_b"))

    assert set(seen["op_a"]) == {"op_a"}
    assert set(seen["op_b"]) == {"op_b"}
    assert flush_fs_metrics() == {}


async def test_a_background_task_spawned_by_a_request_bills_its_fs_work_to_that_request(
    op: str,
) -> None:
    # A chat turn fans FS work out into fire-and-forget tasks (the artifact
    # forwarder, the last-active touch). Their cost belongs on the turn's wide
    # event, and it only gets there because the child inherits the bucket the
    # request already created. Guarding this because it holds only while the
    # bucket exists at spawn time — see the module note on orphaned buckets.
    record_fs_op(op, duration_ms=1.0)

    async def background() -> None:
        await asyncio.sleep(0)
        record_fs_op(f"{op}_bg", duration_ms=2.0)

    await asyncio.create_task(background())

    flushed = flush_fs_metrics()
    assert set(flushed) == {op, f"{op}_bg"}
    assert flushed[f"{op}_bg"]["total_ms"] == 2.0


# ── fs_timer ─────────────────────────────────────────────────────────


async def test_a_successful_timer_records_one_op_with_a_real_elapsed_duration(op: str) -> None:
    async with fs_timer(op):
        await asyncio.sleep(0.02)

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 1
    assert snap["errors"] == 0
    assert snap["total_ms"] >= 15.0


async def test_a_failing_body_is_still_recorded_with_its_error_type(op: str) -> None:
    # The failure path's latency is the whole point of timing it — a bare
    # `except: raise` that forgets to stamp `err` would report the failure as a
    # successful op.
    with pytest.raises(OSError):
        async with fs_timer(op):
            raise OSError("mount gone")

    snap = peek_fs_metrics()[op]
    assert snap["count"] == 1
    assert snap["errors"] == 1
    assert snap["last_error_type"] == "OSError"
    assert total(op, status="error") == 1.0


async def test_the_original_exception_escapes_the_timer_unchanged(op: str) -> None:
    # Never swallow, never re-wrap: callers upstream catch specific types.
    boom = OSError("mount gone")

    with pytest.raises(OSError) as excinfo:
        async with fs_timer(op):
            raise boom

    assert excinfo.value is boom


async def test_a_cancelled_operation_is_recorded_as_an_error_and_still_propagates(
    op: str,
) -> None:
    # CancelledError is a BaseException. Narrowing the handler to `Exception`
    # would record every client-disconnect mid-write as a clean success.
    with pytest.raises(asyncio.CancelledError):
        async with fs_timer(op):
            raise asyncio.CancelledError

    snap = peek_fs_metrics()[op]
    assert snap["errors"] == 1
    assert snap["last_error_type"] == "CancelledError"


async def test_the_in_flight_gauge_rises_inside_the_body_and_returns_to_zero(op: str) -> None:
    async with fs_timer(op):
        assert in_flight(op) == 1.0

    assert in_flight(op) == 0.0


async def test_a_failing_body_still_releases_the_in_flight_gauge(op: str) -> None:
    # A leaked increment makes the op read as permanently stuck on the
    # contention panel, and it never recovers for the life of the process.
    with pytest.raises(RuntimeError):
        async with fs_timer(op):
            raise RuntimeError("boom")

    assert in_flight(op) == 0.0


async def test_a_cancelled_body_still_releases_the_in_flight_gauge(op: str) -> None:
    with pytest.raises(asyncio.CancelledError):
        async with fs_timer(op):
            raise asyncio.CancelledError

    assert in_flight(op) == 0.0


async def test_two_concurrent_timers_on_one_op_are_both_counted_in_flight(op: str) -> None:
    both_in = asyncio.Event()
    release = asyncio.Event()
    entered = 0

    async def run() -> None:
        nonlocal entered
        async with fs_timer(op):
            entered += 1
            if entered == 2:
                both_in.set()
            await release.wait()

    tasks = [asyncio.create_task(run()) for _ in range(2)]
    await both_in.wait()
    assert in_flight(op) == 2.0

    release.set()
    await asyncio.gather(*tasks)
    assert in_flight(op) == 0.0


async def test_nested_timers_for_the_same_op_release_the_gauge_once_each(op: str) -> None:
    # An acquire that internally re-times itself must not drive the gauge
    # negative on the way out.
    async with fs_timer(op):
        async with fs_timer(op):
            assert in_flight(op) == 2.0
        assert in_flight(op) == 1.0

    assert in_flight(op) == 0.0
    assert peek_fs_metrics()[op]["count"] == 2


async def test_a_registry_that_fails_on_increment_still_runs_the_body_and_records_the_op(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Documented: the increment is guarded so a registry bug never breaks the
    # yield. Unguarded, a metrics fault would abort the storage operation.
    monkeypatch.setattr(m, "_FS_OP_IN_FLIGHT", _BrokenCollector())
    ran = False

    async with fs_timer(op):
        ran = True

    assert ran is True
    assert peek_fs_metrics()[op]["count"] == 1


async def test_a_registry_that_fails_on_decrement_still_records_the_op(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Documented: the decrement is guarded so a paired-state inconsistency never
    # blocks record_fs_op. Moving the record inside that try would lose the op.
    monkeypatch.setattr(m, "_FS_OP_IN_FLIGHT", _BrokenDecCollector())

    async with fs_timer(op):
        pass

    assert peek_fs_metrics()[op]["count"] == 1


async def test_a_registry_that_fails_on_decrement_does_not_mask_the_bodys_exception(
    op: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unguarded raise inside `finally` replaces the real error with a metrics
    # error, and the caller loses the reason the FS op failed.
    monkeypatch.setattr(m, "_FS_OP_IN_FLIGHT", _BrokenDecCollector())

    with pytest.raises(OSError):
        async with fs_timer(op):
            raise OSError("mount gone")


async def test_timer_labels_reach_both_the_wide_event_and_prometheus(op: str) -> None:
    async with fs_timer(op, mode="reuse"):
        pass

    assert peek_fs_metrics()[op]["labels"] == {"mode": "reuse"}
    assert total(op, mode="reuse") == 1.0


async def test_a_timer_reports_no_bytes_of_its_own(op: str) -> None:
    # fs_timer splats **labels into record_fs_op, which also has a `bytes`
    # keyword; a collision there would fabricate byte volume out of a label.
    async with fs_timer(op, mode="reuse"):
        pass

    assert "bytes" not in peek_fs_metrics()[op]
    assert byte_total(op) is None


# ── set_sandbox_pool_size ────────────────────────────────────────────


def test_pool_size_is_last_writer_wins_rather_than_cumulative() -> None:
    # A pool that shrank must read as shrunk. `.inc()` instead of `.set()`
    # produces a monotonically rising line that never comes back down.
    shard = uuid4().hex
    set_sandbox_pool_size("user", shard, 3)
    set_sandbox_pool_size("user", shard, 1)

    assert REGISTRY.get_sample_value("sandbox_pool_size", {"kind": "user", "shard": shard}) == 1.0


def test_pool_sizes_for_different_kinds_are_tracked_independently() -> None:
    shard = uuid4().hex
    set_sandbox_pool_size("user", shard, 3)
    set_sandbox_pool_size("warm", shard, 7)

    assert REGISTRY.get_sample_value("sandbox_pool_size", {"kind": "user", "shard": shard}) == 3.0
    assert REGISTRY.get_sample_value("sandbox_pool_size", {"kind": "warm", "shard": shard}) == 7.0


def test_an_empty_pool_is_published_as_zero_rather_than_skipped() -> None:
    shard = uuid4().hex
    set_sandbox_pool_size("warm", shard, 0)

    assert REGISTRY.get_sample_value("sandbox_pool_size", {"kind": "warm", "shard": shard}) == 0.0


def test_a_registry_failure_never_breaks_the_pool_mutation_that_published_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is called from inside the sandbox pool's add/remove path — raising
    # here would abandon a sandbox mid-checkout.
    monkeypatch.setattr(m, "_SANDBOX_POOL_SIZE", _BrokenCollector())

    set_sandbox_pool_size("user", "0", 1)


# ── _register_once ───────────────────────────────────────────────────


def test_re_importing_the_module_reuses_the_already_registered_collector() -> None:
    # `uvicorn --reload` and the worker's registry re-import this module. If the
    # duplicate registration were not tolerated the process would die at import.
    again = _register_once(
        "fs_op_in_flight",
        lambda: Gauge(
            name="fs_op_in_flight",
            documentation="duplicate registration",
            labelnames=("operation",),
        ),
    )

    assert again is m._FS_OP_IN_FLIGHT


def test_a_registration_failure_for_an_unknown_collector_is_not_swallowed() -> None:
    # The except branch only exists to absorb a *duplicate*. Returning None (or
    # the missing collector) for a genuinely broken definition would surface far
    # later as an AttributeError at the first record_fs_op call.
    def boom() -> Gauge:
        raise ValueError("bad bucket definition")

    with pytest.raises(ValueError, match="bad bucket definition"):
        _register_once(f"never_registered_{uuid4().hex}", boom)


def test_a_single_byte_is_recorded_on_both_surfaces(op: str) -> None:
    # The smallest positive count: a `> 1` guard on either surface would drop
    # it while every larger fixture in this file still passed.
    record_fs_op(op, duration_ms=1.0, byte_count=1)

    assert peek_fs_metrics()[op]["bytes"] == 1
    assert byte_total(op) == 1.0


def test_a_negative_byte_count_records_no_bytes(op: str) -> None:
    # `if byte_count:` and `if byte_count > 0:` differ exactly here — a
    # negative count must not touch either surface.
    record_fs_op(op, duration_ms=1.0, byte_count=-5)

    assert "bytes" not in peek_fs_metrics()[op]
    assert byte_total(op) is None
