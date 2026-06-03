## Why

Live smoke test exposed two issues with the metrics surface that landed in `fs-metrics-to-prometheus`:

1. **The dashboard goes empty between bursts.** Every panel uses `rate(...[5m])`, so 5+ minutes after a chat turn the dashboard looks identical to a never-used one. Sandbox traffic in this product is naturally spiky — one chat, then idle for ten minutes — so the default view shows nothing 90% of the time even though metrics ARE flowing.
2. **The metrics inventory is shallow.** We have per-op duration + bytes, nothing else. We cannot answer at-a-glance: how many sandboxes are alive right now? How many FS ops are in flight? When did each op type last fire? What's the bash exit-code distribution? Was that "slow acquire" 1 of 1 or 1 of 100?

Both are addressable cheaply because every measurement already funnels through `record_fs_op`. Adding a gauge or counter there is one new line; the dashboard rebuild is a single JSON file.

## What Changes

**New collectors** (registered alongside the existing two on the default registry, cross-registered on the worker registry the same way):

- `fs_op_total` (Counter, labels `operation, mode, status`) — cumulative count. Never decays. Backs "has this op EVER fired" + lifetime totals tables.
- `fs_op_last_seen_unix_seconds` (Gauge, labels `operation`) — Unix timestamp of the most recent observation. Lets dashboards show "fired 2 minutes ago" even when the rate window is empty.
- `fs_op_in_flight` (Gauge, labels `operation`) — incremented on `fs_timer` enter, decremented on exit. Exposes contention and stuck operations directly.
- `sandbox_pool_size` (Gauge, labels `kind={user,warm}, shard`) — set by the sandbox pool on add/remove. Currently impossible to answer "how many sandboxes does GAIA have alive?" from metrics alone.
- `tool_bash_exit_code_total` (Counter, label `exit_code` as string, bucketed into `0`, `1-126`, `127`, `128-254`, `255`, `timeout`) — recorded by `bash_tool.py` after every `commands.run` returns. Surfaces non-zero exits without log scraping.

**FS Ops dashboard v2** (`infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json`) — rebuild so it's useful when there's no traffic:

- **Lifetime totals table** at the top — `sum by (operation) (fs_op_total)` — always populated once any op has ever run. Sortable by op name, count, error count.
- **Last seen** column in that same table — `time() - fs_op_last_seen_unix_seconds` formatted as "5m ago" / "2h ago". Shows what's quiet vs. fresh.
- **Mean duration per op** panel — `rate(fs_op_duration_seconds_sum[30m]) / clamp_min(rate(fs_op_duration_seconds_count[30m]), 1e-9)`. Wider window, doesn't go to "No data" for a quiet system.
- **Percentile time-series** kept but widen to `[30m]` window so they stay populated through normal idle periods.
- **In-flight ops** time-series — straight `fs_op_in_flight` (gauge, no rate). One spike per long-running op.
- **Sandbox pool size** time-series — `sandbox_pool_size` per shard + kind. Shows warm pool effectiveness once Phase B of the sibling change lands.
- **Bash exit codes** stat panel — `sum by (exit_code) (rate(tool_bash_exit_code_total[1h]))`. Surfaces failures.
- **Default time range** widened to `now-1h` instead of `now-15m`. Refresh stays 10s.
- The two empty placeholder rows (Error rate + throughput, sbx_acquire by mode) keep the same queries but are wrapped in `or vector(0)` so they render an explicit zero line instead of "No data" — clearer that the system is healthy, not broken.

**No infra changes.** Same default registry, same scrape config, same JSON-provisioned Grafana.

## Capabilities

### New Capabilities
- `fs-metrics-coverage`: Adds the five new collector families (`fs_op_total`, `fs_op_last_seen_unix_seconds`, `fs_op_in_flight`, `sandbox_pool_size`, `tool_bash_exit_code_total`) with the wiring inside `record_fs_op` / `fs_timer` / `bash_tool` / `pool.py`, plus the dashboard v2 rebuild. Follows the same idempotent-registration + default-registry + worker-cross-register pattern established by the sibling capability `fs-metrics-prometheus` — extends, does not modify.

### Modified Capabilities
*(none — sibling `fs-metrics-prometheus` is unmodified; this change extends the pattern with new requirements)*

## Impact

- **Code touched**: `apps/api/app/services/storage/metrics.py` (5 new collectors + wiring), `apps/api/app/services/sandbox/pool.py` (set `sandbox_pool_size` on add/remove), `apps/api/app/agents/tools/coding/bash_tool.py` (record exit code), `apps/api/app/workers/metrics.py` (cross-register new collectors — one tuple addition), Grafana dashboard JSON.
- **Cardinality budget**: `fs_op_total` reuses existing label set (≤250 series). `fs_op_in_flight` is per-op (≤25 series). `fs_op_last_seen_unix_seconds` per-op (≤25 series). `sandbox_pool_size` is `kind × shard ≤ 2 × 8 = 16 series`. `tool_bash_exit_code_total` is 6 buckets. Total new series < 350.
- **No new dependencies, no migrations, no new endpoints.**
- **Risk**: `fs_op_in_flight` mutation lives inside `fs_timer`; an unbalanced enter/exit would leak. Guard with `try/finally` (already the structure of `fs_timer`).
- **Dashboard rollback**: git history is the rollback path — `git checkout <prior-sha> -- infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json` restores v1 if the new layout has surprises.
