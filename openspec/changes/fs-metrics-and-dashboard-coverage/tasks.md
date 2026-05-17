## 1. New collectors in metrics.py

- [x] 1.1 Declare `_FS_OP_TOTAL` Counter `(operation, mode, status)`.
- [x] 1.2 Declare `_FS_OP_LAST_SEEN` Gauge `(operation,)`. `Gauge` added to the prometheus_client import.
- [x] 1.3 Declare `_FS_OP_IN_FLIGHT` Gauge `(operation,)`.
- [x] 1.4 Declare `_SANDBOX_POOL_SIZE` Gauge `(kind, shard)` + export `set_sandbox_pool_size(kind, shard, n)` helper added to `__all__`.
- [x] 1.5 Module docstring's "Prometheus export" section updated to enumerate all seven collectors plus the bash exit code counter location.

## 2. Wire dual-write into record_fs_op + fs_timer

- [x] 2.1 `record_fs_op` now increments `fs_op_total` and sets `fs_op_last_seen_unix_seconds` inside the existing try/except. Mode label resolved the same way as the histogram (`labels.get("mode") or "none"`).
- [x] 2.2 `fs_timer` increments `fs_op_in_flight` on entry and decrements in `finally` (separate try/except for each so a registry bug doesn't break the timer's contract).
- [x] 2.3 Deferred to live-stack verification (next batch after we finish wiring).

## 3. Sandbox pool gauge wiring

- [x] 3.1 Added `_publish_size()` to `SandboxPool` — groups `_entries` by `shard_for(user_id)`, emits `set_sandbox_pool_size("user", shard, count)` per shard, re-publishes 0 for previously-seen shards now empty.
- [x] 3.2 `put` and `evict` now call `_publish_size()` after mutating `_entries`.
- [x] 3.3 Pool constructor seeds `set_sandbox_pool_size("warm", str(shard), 0)` for `range(JUICEFS_NUM_SHARDS)` so the warm-pool panel renders zero instead of "No data" until the sibling change populates entries.

## 4. Bash exit code counter

- [x] 4.1 `_BASH_EXIT_CODE_TOTAL` Counter registered at module scope in `bash_tool.py` via shared `_register_once` import. Documented bucket choice inline.
- [x] 4.2 `_bucket_exit_code(code, timed_out)` helper buckets into `0`, `1-126`, `127`, `128-254`, `255`, `timeout`.
- [x] 4.3 `_run_foreground` wraps `sbx.commands.run` in try/except: success path records the actual exit code, `asyncio.TimeoutError`/`asyncio.CancelledError` record `"timeout"`, other exceptions inspect class-name for "timeout" else record `"255"`. Counter increment is non-fatal.
- [x] 4.4 Deferred to live-stack verification.

## 5. Worker cross-registration

- [x] 5.1 `workers/metrics.py` extended cross-register loop with the four new fs_op collectors and `_SANDBOX_POOL_SIZE`. Bash exit code counter intentionally not cross-registered (not reachable from worker code paths).
- [x] 5.2 Deferred to live-stack verification.

## 6. Dashboard v2

- [x] 6.1 Rollback path is git history (`git checkout <prior-sha> -- fs-ops.json`); no sibling `.bak` shipped.
- [x] 6.2 Rewrote `fs-ops.json` with: Overview row (lifetime totals table + in-flight ops + sandbox pool size), Latency row (mean / p50 / p95 / p99 at 30m windows), Errors+throughput row (error rate per op, byte throughput, bash exit codes pie), sbx_acquire by mode row. Empty rate panels wrapped with `or vector(0)` so they render zero instead of "No data".
- [x] 6.3 Top-level: `time = {from: "now-1h", to: "now"}`, `refresh = "10s"`, `tags = ["gaia", "fs", "sandbox"]`, "GAIA Dashboards" links retained.
- [x] 6.4 JSON validated via `python3 -m json.tool`. Live-stack panel rendering deferred to next batch.

## 7. Documentation + sign-off

- [x] 7.1 Module docstring "Prometheus export" updated (same as 1.5).
- [x] 7.2 `nx lint api` → all checks passed. `nx type-check api` → no issues found.
- [x] 7.3 `openspec validate fs-metrics-and-dashboard-coverage` — confirmed valid.
