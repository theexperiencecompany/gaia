# Stress-test tier (`tests/stress/`)

Battle-style tests modeled on hermes-agent's `tests/stress/` (race-for-claim with
"no double-claims" invariants, adversarial scheduling). They hammer real
production code paths — ARQ task functions, webhook endpoints, the SSE stream
manager and its graph driver — under concurrency and replay, and assert the
invariants that keep GAIA from double-processing anything.

## Running

**Not run by default.** These are excluded from the fast suite (`-m "not stress"`
is added to the default `addopts` once the marker is registered) because each
test is a stress battle, not a unit check — they are intentionally adversarial
and slower than the unit tier (30s+ per file in aggregate on a busy machine).

Run the tier once the `api:test:stress` Nx target exists:

```bash
nx run api:test:stress          # equivalent to: cd apps/api && uv run pytest tests/stress -m stress
```

Until that target lands, run directly:

```bash
cd apps/api && uv run pytest tests/stress -q -o addopts=""    # bypasses --strict-markers until `stress` is registered in pytest.ini
```

All tests are **offline-capable**: no Docker, no real Redis/Mongo, no network.
Infrastructure seams (Redis clients, Mongo repositories, PostHog/email senders)
are replaced in-process with fakes that preserve the exact semantics the code
depends on — atomic `SET NX`, cursor-ordered Redis Streams, idempotency markers.
If a test ever needs real infra it will `skip` with a clear message.

## Files

| File | Real code under test | Invariant asserted |
|---|---|---|
| `test_arq_idempotency.py` | `backfill_user_memories` ARQ task (`app/workers/tasks/memory_backfill_tasks.py`) | A retried/replayed job must not redo side effects: the second invocation of the same user returns the `skip` marker and performs **zero** side effects (no memory retain, no notification, no marker write) |
| `test_webhook_replay.py` | Composio webhook endpoint (`app/api/v1/endpoints/webhook_composio.py`) with the real HMAC-SHA256 signature path, and `PaymentWebhookService.process_webhook` (`app/services/payments/payment_webhook_service.py`) | Duplicate delivery of the same signed payload — sequential or concurrent — produces exactly **one** side effect; the dedup claim keys on `webhook-id` (SET-NX), not payload content |
| `test_sse_resume.py` | `StreamManager.subscribe_stream` cursor/resume (`app/core/stream_manager.py`) and the per-chunk cancellation loop of `execute_graph_streaming` (`app/helpers/agent_helpers.py`) | Resume-from-cursor (`Last-Event-ID`) replays only new events; the cancellation flag flips mid-stream and the graph driver stops producing, emits the `cancelled` marker and records the interruption exactly once |
| `test_claim_race.py` | `execute_tracked_todo` Redis lock claim (`app/workers/tasks/tracked_todo_tasks.py`) | N concurrent claims on the same todo: exactly one wins, the losers skip without releasing the winner's lock, and the lock is held for the whole critical section and released afterwards |

## Design rules

- **Deterministic, in-process.** No `time.sleep` / `asyncio.sleep` for timing.
  Concurrency is real `asyncio.Task` scheduling against fakes whose critical
  operations have no `await` between check and set — mirroring Redis's
  single-threaded command atomicity — so exactly-one-winner results are
  reproducible, not probabilistic.
- **Mock the seam, run the logic.** Repositories, Redis clients, and external
  senders are faked; the ARQ task / endpoint handler / stream manager / graph
  driver code itself is the real thing. A stateful fake (the `memory_backfilled`
  marker, the processed-webhook store) is the observable side effect.
- **Every test can fail.** Each invariant has a mutation that breaks it: remove
  the marker guard, bypass the SET-NX dedup, drop the cursor, or stop checking
  the cancel flag, and the test goes red.
- **No fabricated concurrency.** Tests only race code that already claims,
  dedups, or cancels in production. Nothing was invented to give a race test
  somewhere to live.
