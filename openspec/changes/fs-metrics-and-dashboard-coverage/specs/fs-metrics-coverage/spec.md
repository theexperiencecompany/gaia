## ADDED Requirements

### Requirement: Cumulative op counter

The system SHALL register a Prometheus counter `fs_op_total` on the default registry with labels `(operation, mode, status)`. Each call to `record_fs_op` SHALL increment this counter by 1 with `mode = labels.get("mode", "none")` and `status = "error" if error else "ok"` (matching the existing histogram's labels exactly).

Lifetime totals SHALL be queryable as `sum by (operation) (fs_op_total)` and SHALL not decay across scrape intervals.

#### Scenario: Counter increments per observation
- **WHEN** `record_fs_op(FS_OPS.TOOL_BASH, duration_ms=100)` is called twice
- **THEN** `fs_op_total{operation="tool_bash",mode="none",status="ok"}` reports `2`

#### Scenario: Error status flows through
- **WHEN** `record_fs_op(FS_OPS.SBX_CREATE, duration_ms=2000, error=RuntimeError("boom"))`
- **THEN** `fs_op_total{operation="sbx_create",mode="none",status="error"}` increments by 1

### Requirement: Last-seen timestamp gauge

The system SHALL register a Prometheus gauge `fs_op_last_seen_unix_seconds` on the default registry with label `(operation,)`. Each call to `record_fs_op` SHALL call `.labels(operation=op).set(time.time())`, recording the wall-clock time of the most recent observation for that op.

The gauge SHALL allow Grafana panels to compute "seconds since last fire" via `time() - fs_op_last_seen_unix_seconds`.

#### Scenario: Timestamp advances on each call
- **WHEN** two `record_fs_op(FS_OPS.TOOL_BASH, ...)` calls happen 5 seconds apart
- **THEN** the second value of `fs_op_last_seen_unix_seconds{operation="tool_bash"}` is exactly 5 seconds greater than the first (within scrape precision)

### Requirement: In-flight gauge driven by fs_timer

The system SHALL register a Prometheus gauge `fs_op_in_flight` on the default registry with label `(operation,)`. The `fs_timer` async context manager SHALL increment this gauge on entry (before the `yield`) and decrement it in the `finally` block (after `record_fs_op` runs), so the value reflects the count of currently-running operations for each op.

The gauge SHALL be crash-safe — any exception path through the `yield` SHALL still execute the decrement via the existing `try/finally`.

#### Scenario: Gauge rises during operation
- **WHEN** an async context `async with fs_timer(FS_OPS.SBX_MOUNT_SCRIPT): await asyncio.sleep(5)` is running
- **THEN** during the sleep, `fs_op_in_flight{operation="sbx_mount_script"}` reads at least `1`
- **AND** after the context exits, the same gauge reads `0`

#### Scenario: Exception path still decrements
- **WHEN** `async with fs_timer(FS_OPS.TOOL_BASH): raise RuntimeError("x")`
- **THEN** the exception propagates AND `fs_op_in_flight{operation="tool_bash"}` returns to its pre-call value

### Requirement: Sandbox pool size gauge

The system SHALL register a Prometheus gauge `sandbox_pool_size` on the default registry with labels `(kind, shard)` where `kind ∈ {"user", "warm"}` and `shard` is the stringified shard id.

The `SandboxPool` (`apps/api/app/services/sandbox/pool.py`) SHALL call `.labels(kind="user", shard=str(shard_id)).set(len(self._entries_for_shard(...)))` after every add or remove of a per-user pool entry. The warm pool (when implemented in the sibling `e2b-perf-metrics-and-improvements` change) SHALL similarly publish under `kind="warm"`. Until the warm pool exists, `kind="warm"` values SHALL be zero.

#### Scenario: User pool reflects refcount changes
- **WHEN** one user acquires a sandbox on shard 0
- **THEN** `sandbox_pool_size{kind="user",shard="0"}` reads at least `1`
- **AND** after `_hard_evict`, the same gauge decrements

### Requirement: Bash exit code counter

`apps/api/app/agents/tools/coding/bash_tool.py` SHALL register a Prometheus counter `tool_bash_exit_code_total` with label `(exit_code,)` and increment it after every `commands.run` invocation. The label value SHALL be one of `0`, `1-126`, `127`, `128-254`, `255`, `timeout` (literal strings, not numbers). The bucketing SHALL be:

- exit code 0 → `"0"`
- 1 ≤ exit code ≤ 126 → `"1-126"`
- exit code 127 → `"127"`
- 128 ≤ exit code ≤ 254 → `"128-254"`
- exit code 255 → `"255"`
- the tool's own timeout sentinel (when `_run_foreground` deadline expired) → `"timeout"`

#### Scenario: Successful echo records exit_code=0
- **WHEN** bash runs `echo hi` successfully
- **THEN** `tool_bash_exit_code_total{exit_code="0"}` increments by `1`

#### Scenario: Command-not-found records 127
- **WHEN** bash runs `definitely_not_a_command`
- **THEN** `tool_bash_exit_code_total{exit_code="127"}` increments by `1`

#### Scenario: Tool timeout records timeout
- **WHEN** a foreground bash run exceeds its configured timeout and is killed by `_run_foreground`
- **THEN** `tool_bash_exit_code_total{exit_code="timeout"}` increments by `1`

### Requirement: Idempotent registration extends to new collectors

All five new collectors (`fs_op_total`, `fs_op_last_seen_unix_seconds`, `fs_op_in_flight`, `sandbox_pool_size`, `tool_bash_exit_code_total`) SHALL be registered through the existing `_register_once` helper so module re-imports under `uvicorn --reload` and test fixture re-loads do not raise.

#### Scenario: Reload does not crash
- **WHEN** the metrics module is imported twice in the same Python process
- **THEN** no exception is raised and the same collector instances are returned on the second import

### Requirement: Worker process exports new collectors

`apps/api/app/workers/metrics.py` SHALL cross-register all five new collectors onto the worker's custom `REGISTRY` via the same pattern used for `_FS_OP_DURATION_SECONDS` and `_FS_OP_BYTES_TOTAL`. The worker's port-9100 `/metrics` SHALL serve all five families when relevant ops fire inside ARQ tasks.

#### Scenario: Worker /metrics shows lifetime counter
- **WHEN** an ARQ task body records any FS op
- **THEN** `curl arq_worker:9100/metrics` includes `fs_op_total{...}` with a positive value

### Requirement: Dashboard v2 — lifetime totals + always-populated panels

The repo SHALL replace `infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json` with a new dashboard that contains at minimum:

- **Lifetime totals table** — columns: `operation`, `total count` (`sum by (operation) (fs_op_total)`), `error count` (`sum by (operation) (fs_op_total{status="error"})`), `last seen` (`time() - fs_op_last_seen_unix_seconds`, formatted as relative time).
- **Mean duration per op** time-series — `rate(fs_op_duration_seconds_sum[30m]) / clamp_min(rate(fs_op_duration_seconds_count[30m]), 1e-9)`.
- **Percentile time-series (p50/p95/p99)** with the rate window widened to `[30m]`.
- **In-flight ops** time-series — `fs_op_in_flight` (no rate).
- **Sandbox pool size** time-series — `sandbox_pool_size`, legend `{{kind}} shard {{shard}}`.
- **Bash exit code distribution** stat or pie panel — `sum by (exit_code) (rate(tool_bash_exit_code_total[1h]))`.
- The existing **Error rate per op** + **Byte throughput per op** + **sbx_acquire by mode** panels SHALL be preserved but their queries SHALL append `or vector(0)` so they render an explicit zero line instead of "No data" when quiet.

The default dashboard time range SHALL be `now-1h`, refresh `10s`.

The previous dashboard layout SHALL be recoverable via git history rather than a sibling `.bak` file; rollback uses `git checkout <prior-sha> -- infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json`.

#### Scenario: Lifetime totals always render
- **WHEN** the dashboard loads in Grafana after any FS op has ever fired
- **THEN** the lifetime totals table contains at least one row with a positive count
- **AND** the row's "last seen" column shows a relative timestamp (not "No data")

#### Scenario: Empty rate panels render zero, not "No data"
- **WHEN** no errors have fired in the last 30 minutes
- **THEN** the **Error rate per op** panel renders a flat zero line for at least one operation

#### Scenario: In-flight gauge spikes during a chat
- **WHEN** a chat turn drives a sandbox acquire
- **THEN** the **In-flight ops** panel shows `fs_op_in_flight{operation="sbx_acquire"}` going from 0 to 1 and back to 0 within the time range
