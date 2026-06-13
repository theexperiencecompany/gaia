## 1. Phase A — Metrics groundwork

> Percentile surface delegated to change `fs-metrics-to-prometheus` (see its tasks). The wide-event `fs={...}` log field continues to carry per-request totals.

- [ ] 1.1 Extend `FS_OPS` in `apps/api/app/services/storage/metrics.py` with new constants: `SBX_LOCK_WAIT`, `SBX_ACQUIRE_OVERHEAD`, `SBX_MOUNT_JFS_USER`, `SBX_MOUNT_JFS_SKILLS`, `SBX_MOUNT_BIND_WORKSPACE`, `SBX_MOUNT_BIND_SKILLS`, `SBX_MOUNT_CANARY_WRITE`. Keep names ≤32 chars and snake_case.
- [ ] 1.2 In `apps/api/app/services/sandbox/lifecycle.py:acquire_sandbox`, wrap the `async with entry.lock:` block with `fs_timer(FS_OPS.SBX_LOCK_WAIT)` so wait time is measured separately from work-under-lock.
- [ ] 1.3 In `_acquire_or_create`, set a local `mode` variable tracking which branch executed (`hit`, `resume`, `cold_create`, plus `hit_fast`/`prewarm` placeholders for later phases). Pass `mode=...` as a label into the outer `fs_timer(FS_OPS.SBX_ACQUIRE, mode=mode)`.
- [ ] 1.4 On the cache-hit branch, wrap the health probe + canary verify pair inside one `fs_timer(FS_OPS.SBX_ACQUIRE_OVERHEAD)` so the floor cost of the safety tax is its own bucket.
- [ ] 1.5 Edit `apps/api/scripts/mount_juicefs.sh` to wrap each heavy step with `start=$(date +%s%3N); ...; printf "GAIA_TIMING %s %s\n" <step> $(( $(date +%s%3N) - start ))`. Steps: `mount_user`, `mount_skills`, `bind_workspace`, `bind_skills`, `canary_write`. Verify the script still exits 0 / 1 as before.
- [ ] 1.6 In `_run_mount_script`, after `commands.run` returns, regex-match `^GAIA_TIMING (\w+) (\d+)$` per line of captured stdout, map to FS op constants, and call `record_fs_op(op, duration_ms=<int>)` for each. Wrap in `try/except` with a single `log.warning` on parse failure — never raise.
- [ ] 1.7 Write `apps/api/scripts/bench_sandbox_acquire.py`. CLI args `--user-id`, `--iterations`, `--shards`, `--modes`. For each mode, force the path (cold: `_hard_evict` between iterations; resume: pause then acquire; hit: acquire twice in a row). Print a markdown table of p50/p95/p99/samples per mode/shard. Mirror the script structure of `apps/api/scripts/materialize_user_workspace.py`.
- [ ] 1.8 Run `nx lint api && nx type-check api` and fix any new diagnostics.
- [ ] 1.9 Manually verify with the dev server: send 5 chat turns, then check the Grafana **FS Ops** dashboard (provisioned by `fs-metrics-to-prometheus`) and confirm `sbx_acquire`, `sbx_lock_wait`, mount sub-steps, and the `sbx_acquire` mode breakdown are all populated with non-zero values.

## 2. Phase B — Warm pool (ships dark)

- [ ] 2.1 Create `apps/api/app/services/sandbox/warm_pool.py` with: module-level `_pool: dict[int, deque[AsyncSandbox]]` keyed by `shard_id`, per-shard `asyncio.Lock` map, `try_pop(shard_id)`, `push(shard_id, sbx)`, `size(shard_id)`, `clear()`. All async.
- [ ] 2.2 Add settings: `E2B_WARM_POOL_TARGET: int = 0` (default disables), `WARM_POOL_REFRESH_SECONDS: int = 30`, `E2B_WARM_POOL_ACCOUNT_CEILING: int = 50` (hard quota cap). Remove or alias the older `E2B_WARM_POOL_TARGET_RATIO`.
- [ ] 2.3 Write `prewarm_sandbox_pool(ctx)` ARQ task in `apps/api/app/workers/tasks/sandbox_tasks.py`. Body: iterate shards from `shard_router`, for each compute `delta = max(0, target - size(shard_id))`, respect the ceiling, then per-slot call `_create_fresh_sandbox(user_id=None, shard_id=...)`, run mount.sh, `pause()`, `push()`. Wrap in `async with wide_task("prewarm_sandbox_pool")`.
- [ ] 2.4 Register the cron in `apps/api/app/worker.py` to run every `WARM_POOL_REFRESH_SECONDS`. Early-return inside the task body when `E2B_WARM_POOL_TARGET == 0`.
- [ ] 2.5 Adapt `_create_fresh_sandbox` to accept `user_id: str | None`. When None, skip the host-side `ensure_user_workspace` seed (the sandbox is unassigned until handout) and skip the Mongo `e2b_sandboxes` write.
- [ ] 2.6 In `_acquire_or_create`, before `_create_fresh_sandbox`, call `warm_pool.try_pop(shard_id)`. On hit: `resume()` the sandbox, bind it via the existing Mongo upsert, install it into `SandboxPool`, set `mode = "cold_create"`, record `served_from="warm_pool"` label on `SBX_ACQUIRE`. On miss: fall back to today's path.
- [ ] 2.7 Add structured log lines to the warmer task: per-iteration `log.info("[warm_pool] tick", shard=..., size=..., target=..., created=...)` and a counter visible in the wide event.
- [ ] 2.8 Wire warm-pool shutdown into `unified_shutdown` so paused sandboxes are gracefully killed on graceful API termination (kill on shutdown is acceptable — they're cheap to recreate).
- [ ] 2.9 Run `nx lint api && nx type-check api`. Flip `E2B_WARM_POOL_TARGET=2` in dev only. Verify via `bench_sandbox_acquire.py --modes cold_create --iterations 10` that p99 drops materially vs Phase A baseline. Capture both numbers in the PR description.

## 3. Phase C — Fast path + prewarm endpoint

- [ ] 3.1 Add settings: `E2B_CANARY_CACHE_SECONDS: int = 0` (default disables), `E2B_PREWARM_RATE_LIMIT_SECONDS: int = 30`.
- [ ] 3.2 In `_acquire_or_create` cache-hit branch, before invoking health probe + canary, check `entry.last_canary_ts` + `entry.watcher and entry.watcher.is_alive()` + `(now - entry.last_canary_ts) < E2B_CANARY_CACHE_SECONDS`. If all true: set `mode="hit_fast"`, skip both probes, jump to refcount increment.
- [ ] 3.3 In the tool-error exit path inside `acquire_sandbox`'s context exit (or wherever exceptions bubble out of the `yield`), set `entry.last_canary_ts = None` so the next acquire revalidates. Also reset on `commands.run` non-zero exit if currently captured at that layer.
- [ ] 3.4 Verify `_hard_evict` already drops the pool entry (no reset needed) and that `_schedule_pause` stops the watcher before pausing — so `watcher.is_alive()` correctly returns False after pause.
- [ ] 3.5 Create `apps/api/app/api/v1/endpoints/sandbox.py` with `POST /api/v1/sandbox/prewarm`. Auth via `Depends(get_current_user)`, rate-limit via `@tiered_rate_limit("sandbox_prewarm")` (one per 30s). Schedule `asyncio.create_task(_prewarm_user(user_id))` and return `Response(status_code=202)`.
- [ ] 3.6 Implement `_prewarm_user(user_id)` as: `async with acquire_sandbox(user_id): pass`. The context-manager exit re-schedules the idle pause as normal. On any exception, swallow and log `log.warning`.
- [ ] 3.7 Register the new router in `apps/api/app/api/v1/routes.py`. Add a `sandbox_prewarm` config entry to `apps/api/app/config/rate_limits.py` (per-tier limits; "free": 30s, "pro": 10s, etc — match existing patterns).
- [ ] 3.8 Run `nx lint api && nx type-check api`. Smoke-test: `curl -X POST .../api/v1/sandbox/prewarm` → 202; immediately follow with a chat turn and confirm `sbx_acquire.labels.mode in {"hit", "hit_fast"}` (not `cold_create`).
- [ ] 3.9 Flip `E2B_CANARY_CACHE_SECONDS=10` in dev. Run `bench_sandbox_acquire.py --modes hit --iterations 50` and confirm the fast-path mode appears with sub-millisecond `sbx_acquire_overhead` (i.e. zero, since it's skipped) and lower overall `sbx_acquire` p50 than Phase A baseline.

## 4. Documentation & cleanup

- [ ] 4.1 Update `apps/api/app/services/sandbox/__init__.py` docstring to mention warm pool + fast path + the new metric ops list.
- [ ] 4.2 Add a section to `apps/api/CLAUDE.md` ("E2B perf knobs") summarizing the four new settings, what each does, and where the metrics dashboard lives.
- [ ] 4.3 Final pass: `nx lint api && nx type-check api && nx run-many -t type-check --projects=web,desktop && nx run-many -t lint --projects=web,desktop`. All green before considering work complete.
