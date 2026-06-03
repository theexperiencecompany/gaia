## Why

E2B sandbox acquire is on the critical path of every chat turn, but we cannot answer *where the milliseconds go* with the data we ship today. `fs_timer(FS_OPS.SBX_ACQUIRE)` records one bucket that mixes cache hits, warm resumes, and cold creates; mount.sh runs as a single 60s timer with no per-step breakdown; the per-user `asyncio.Lock` contention is invisible; and `E2B_WARM_POOL_TARGET_RATIO=2.0` has been a stubbed setting since branch start with no warming logic behind it. Without that visibility we cannot pick the right lever, and without warming we pay the full cold-create cost (hundreds of ms to multiple seconds) on every first user message.

## What Changes

- Split `SBX_ACQUIRE` into labeled modes (`hit`, `resume`, `cold_create`) so dashboards can pivot on path taken, not aggregated wall-clock.
- Add `SBX_LOCK_WAIT` timer around the per-user `PooledSandbox.lock` acquisition so contention shows up as its own bucket.
- Add per-step mount.sh tracing: `SBX_MOUNT_JFS_USER`, `SBX_MOUNT_JFS_SKILLS`, `SBX_MOUNT_BIND`, `SBX_MOUNT_CANARY_WRITE`. Sourced from millisecond markers emitted by `apps/api/scripts/mount_juicefs.sh`, parsed by `_run_mount_script`.
- Add `SBX_ACQUIRE_OVERHEAD` covering health-probe + canary-verify on cache hits so the "tax we pay even when things are warm" is measurable.
- Percentile surface lives in Prometheus + Grafana via the sibling change `fs-metrics-to-prometheus`. No bespoke ring buffer or dev endpoint here.
- New `scripts/bench_sandbox_acquire.py` driver that exercises cold-create, resume, and cache-hit paths N times per shard and prints percentiles — same harness used to verify improvements land.
- Implement the warm pool the settings already promise: per-shard background task keeps `WARM_POOL_TARGET` idle paused sandboxes, hands them out on cold-acquire, refills async. Configurable via existing `E2B_WARM_POOL_TARGET_RATIO`.
- Cache-hit fast path: skip health probe + canary verify when the previous acquire on the same `PooledSandbox` ended within `E2B_CANARY_CACHE_SECONDS` (default 10s) and the watcher is still alive. Saves the 2 round-trips on back-to-back tool calls.
- Optional background pre-acquire: opt-in endpoint `POST /api/v1/sandbox/prewarm` the frontend can hit on conversation-open / focus, hiding cold-start behind user think time.

## Capabilities

### New Capabilities
- `sandbox-metrics`: Per-acquire-mode timing labels, lock-wait timer, mount.sh per-step traces, repeatable benchmark harness. Percentile dashboards delegated to `fs-metrics-prometheus`.
- `sandbox-warm-pool`: Per-shard background warmer keeping a target number of idle paused sandboxes, fast handout on cold-acquire, refill loop driven by `E2B_WARM_POOL_TARGET_RATIO`.
- `sandbox-fast-path`: Cache-hit short-circuit that skips redundant health-probe + canary round-trips within a configurable freshness window, plus optional frontend-triggered prewarm endpoint.

### Modified Capabilities
*(none — this branch has no prior specs in `openspec/specs/`)*

## Impact

- **Code touched**: `apps/api/app/services/storage/metrics.py` (new ops + Redis ring writer), `apps/api/app/services/sandbox/{lifecycle.py,pool.py,__init__.py}` (mode labels, lock-wait, fast-path, warmer task), `apps/api/scripts/mount_juicefs.sh` (millisecond markers), `apps/api/app/api/v1/endpoints/dev.py` or new `sandbox.py` (metrics + prewarm endpoints), `apps/api/app/config/settings.py` (new knobs), `apps/api/app/worker.py` (warmer ARQ task registration), `apps/api/scripts/bench_sandbox_acquire.py` (new).
- **Runtime cost**: Warm pool consumes idle E2B sandbox slots (paused → cheap; track per-shard count vs. E2B account quota). Redis ring buffer ~10 KB per op per hour.
- **No DB migrations.** No template rebuild (mount.sh changes are interpreted at run-time inside the existing template).
- **Settings additions**: `E2B_WARM_POOL_TARGET` (replaces ratio with absolute), `E2B_CANARY_CACHE_SECONDS`, `SANDBOX_METRICS_RING_TTL_SECONDS`, `SANDBOX_METRICS_RING_MAX_SAMPLES`.
- **Risk**: Skipping canary on fast path masks FUSE staleness — bounded by short TTL + watcher-liveness check + an automatic full revalidate after any tool error.
