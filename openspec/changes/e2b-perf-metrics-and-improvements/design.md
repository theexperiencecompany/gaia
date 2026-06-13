## Context

`apps/api/app/services/storage/metrics.py` already gives us a strong foundation: a per-request ContextVar bucket, the `fs_timer` async context manager, the `FS_OPS` constant table, and an end-of-task `flush_fs_metrics()` that attaches `fs={...}` to the canonical wide event. Seven sandbox lifecycle ops are timed today (`SBX_ACQUIRE`, `SBX_CREATE`, `SBX_CONNECT_RESUME`, `SBX_HEALTH_PROBE`, `SBX_MOUNT_SCRIPT`, `SBX_ENSURE_MOUNTED`, `SBX_CANARY_VERIFY`), plus four tool-level entry points.

What we cannot see from those buckets:

- **Which acquire path actually ran.** `SBX_ACQUIRE` is the union of cache-hit (~50ms — health probe + canary), warm resume (~200–800ms — control plane + resume + ensure mounted), and cold create (~1–3s — control plane + mount.sh + canary write). One bucket means dashboards can't separate the cheap case from the expensive one.
- **Lock-wait time.** `PooledSandbox.lock` is held across the entire critical section (create + mount + health + canary + watcher start). A second concurrent acquire for the same user blocks invisibly inside `acquire_sandbox`.
- **Mount sub-steps.** The 60s `SBX_MOUNT_SCRIPT` timer wraps a shell script that does juicefs format, user mount, skills mount, two bind-mounts, and a chown pass. We cannot tell whether a slow mount is metadata-side, R2-side, or bind-mount side.
- **Cross-request percentiles.** `flush_fs_metrics` emits per-request totals only; p50/p95/p99 require LogQL aggregation, which makes "is the warm pool helping?" a multi-step dashboard query, not a single endpoint poll.

Concurrently, `E2B_WARM_POOL_TARGET_RATIO: float = 2.0` is declared in `settings.py` with a "Phase 2" comment, but is read by zero code. No prewarm path exists. Every first chat message for an idle user pays the full cold-create cost.

## Goals / Non-Goals

**Goals:**
- Make the breakdown of sandbox acquire latency observable at a glance: by mode, by sub-step, with cross-request percentiles.
- Add the warm pool the settings already promise, gated by an existing knob so rollout is a flag flip.
- Cut the back-to-back tool-call tax (health probe + canary on every acquire) when the previous acquire succeeded moments ago.
- Provide a repeatable benchmark harness so improvements have a number attached.

**Non-Goals:**
- Replacing E2B or rearchitecting the sandbox pool. The current `PooledSandbox` model stands.
- Adding a per-conversation sandbox tier or any multi-sandbox-per-user logic.
- Moving from `wide_events` to OpenTelemetry. The Redis ring buffer is a small operator-facing complement, not a replacement.
- Touching the JuiceFS template build (`scripts/build_e2b_template.py`). All changes are interpretable inside the existing `gaia-coder` template.

## Decisions

**1. Acquire path: low-cardinality `mode` label on `SBX_ACQUIRE`, not new ops.**
Reuse the existing `labels` field on `_OpStats` (already supported in `record_fs_op` via `**labels`). Each acquire records `SBX_ACQUIRE` with `mode in {"hit", "resume", "cold_create", "prewarm"}`. Dashboards filter on the label; metric tables stay flat. Considered: separate `SBX_ACQUIRE_HIT`/`SBX_ACQUIRE_RESUME`/`SBX_ACQUIRE_CREATE` constants. Rejected — every consumer would need three queries; labels keep the existing wire contract.

**2. Mount sub-steps: emitted by the shell, parsed in Python.**
`mount_juicefs.sh` prints `GAIA_TIMING <step> <ms>` markers to stdout (no behavior change — script still succeeds even if the API doesn't parse). `_run_mount_script` in `apps/api/app/services/sandbox/lifecycle.py` greps the captured stdout for those markers after `commands.run` returns and replays them through `record_fs_op` with the right op constant. Keeps the shell side trivial (one `start=$(date +%s%3N); ...; printf "GAIA_TIMING %s %s\n" step $((end-start))`), keeps the Python side responsible for taxonomy. Considered: Python-side `commands.run` per step. Rejected — multiplies envd round-trips.

**3. Cross-request percentiles: Redis-backed ring per op.**
At the end of every `wide_task` (when `flush_fs_metrics()` already runs), additionally `LPUSH` a compact per-op tuple `(ts, count, total_ms, max_ms, mode)` to `sandbox_metrics:{op}` with `LTRIM` to `SANDBOX_METRICS_RING_MAX_SAMPLES` (default 10 000) and `EXPIRE SANDBOX_METRICS_RING_TTL_SECONDS` (default 3600). The dev endpoint reads the list, computes p50/p95/p99 in Python, returns JSON. Considered: Postgres time-series table. Rejected for now — Redis covers the dashboarding use case, requires no migration, and self-evicts. The path stays open if we need long retention later.

**4. Warm pool: per-shard background ARQ task, not a custom event loop.**
Add `prewarm_sandbox_pool` to `apps/api/app/workers/tasks/sandbox_tasks.py`, run every 30s via cron in `worker.py`. The task iterates shards (via `shard_router`), counts paused sandboxes per shard, and creates the delta up to `E2B_WARM_POOL_TARGET` (absolute count, default 2 per shard). Each warmed sandbox is created, mount.sh runs once, then `pause()` immediately — total cost amortized off the user request path. Stored in a per-shard `WARM_POOL` deque guarded by an `asyncio.Lock`. On a cold acquire, `_acquire_or_create` checks the deque first; on miss, falls back to today's flow. Considered: keep warm pool inside `SandboxPool` only. Rejected — `SandboxPool` is per-user; warm sandboxes are not yet assigned to a user, so they live one level up.

**5. Cache-hit fast path: timestamp-based, not lock-protected counter.**
Each `PooledSandbox` already has `last_canary_ts` set after a successful verify. On the next acquire, if `now - last_canary_ts < E2B_CANARY_CACHE_SECONDS` (default 10s) **and** `entry.watcher and entry.watcher.is_alive()`, skip the health probe and canary read. Record `SBX_ACQUIRE` with `mode="hit_fast"`. Any tool error inside the resulting sandbox call resets `last_canary_ts = None` so the next acquire goes through the full path. Considered: removing canary entirely. Rejected — E2B GH#884 stale-FUSE recovery is the whole reason canary exists; we shorten the window, not eliminate it.

**6. Prewarm endpoint: idempotent fire-and-forget, no streaming response.**
`POST /api/v1/sandbox/prewarm` returns `202 Accepted` immediately and schedules `acquire_sandbox(user_id)` on a background task that releases on its own. Rate-limited via the existing `tiered_rate_limit` decorator (one prewarm per user per 30s). If the user already has a hot `PooledSandbox`, the call is a no-op. Frontend hooks: `conversation:open`, tab visibility-change to visible.

**7. Benchmark harness: standalone script, not pytest.**
`apps/api/scripts/bench_sandbox_acquire.py` runs N×M acquires (cold/resume/hit) for a test user across all shards, prints a markdown table of p50/p95/p99 per mode, and exits. Mirrors the existing pattern in `apps/api/scripts/materialize_user_workspace.py`. Not a CI test — too expensive and hits real E2B.

## Risks / Trade-offs

- **Fast path masks FUSE staleness.** A pause/resume cycle inside the 10s window would not trigger remount. → `_schedule_pause` already stops the watcher before pausing; on next acquire the watcher liveness check fails and we go through the slow path. Plus any tool error resets the cache. Net risk: a sandbox killed externally within 10s with the watcher still believing it lives. Mitigation: `entry.sandbox` is the same object; E2B's `commands.run` will raise on a dead sandbox and reset.
- **Warm pool quota.** E2B accounts have a concurrent sandbox cap. → `E2B_WARM_POOL_TARGET` is an absolute count per shard with a hard ceiling at `min(E2B_WARM_POOL_TARGET, E2B_ACCOUNT_LIMIT // shard_count // 2)` enforced inside the task. Also: warmed sandboxes are paused (cheap on E2B's accounting); live count is only N during the seconds between create and pause.
- **Mount markers introduce shell complexity.** → Each marker is two lines (`start=...`, `printf ...`). Total <30 lines. Adds zero failure modes — even if the API never parses, the script still mounts.
- **Redis ring writer in hot path.** → One `LPUSH` + `LTRIM` per op per request. Both O(1). Wrapped in `try/except`; ring write failure logs a warning, never blocks the wide event flush.
- **Histogram drift across replicas.** Redis-backed, so all replicas write into the same ring — the endpoint reads a single ring and computes percentiles globally. No per-replica drift.
- **Prewarm endpoint abuse.** → Tiered rate limit (one per 30s per user). Bypasses paid-tier checks since the cost is internal-only.

## Migration Plan

Each phase is independently deployable and rollback-safe via setting flips:

1. **Phase A — Metrics only (zero behavior change).** Add labels to `SBX_ACQUIRE`, new mount sub-step constants, mount.sh markers, Redis ring writer, dev endpoint. Benchmark harness lands here. Sets the baseline numbers used to evaluate Phase B/C.
2. **Phase B — Warm pool, off by default.** Land the warmer task + pool deque + acquire-side handout. `E2B_WARM_POOL_TARGET=0` keeps it dormant. Flip to 2 per shard in staging, validate p99 cold-acquire drop via dev endpoint, then prod.
3. **Phase C — Fast path + prewarm endpoint.** `E2B_CANARY_CACHE_SECONDS=0` disables; default 10s once Phase A shows it's safe. Frontend prewarm hook is decoupled — backend ships first.

Rollback: each phase is a setting flip back to 0 / default. No data state to migrate.

## Open Questions

- **Should mount.sh markers also emit JuiceFS daemon PID + uptime?** Useful for correlating slow mounts with restarts, but parsing adds complexity. Deferred unless the slow-mount question surfaces in practice.
- **Per-conversation vs. per-user prewarm.** Frontend may emit prewarm at conversation-open *and* at typing. Decide post-Phase-A based on whether typing → prewarm is detectably better.
- **Multi-replica warm pool ownership.** Two API replicas could try to warm the same shard concurrently. Acceptable in v1 (creates one extra sandbox, gets paused, no functional issue). If quota pressure shows up, add a Redis `SETNX` lease per shard around the warmer task body.
