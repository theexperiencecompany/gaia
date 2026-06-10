# fs-metrics-prometheus Specification

## Purpose
TBD - created by archiving change fs-metrics-to-prometheus. Update Purpose after archive.
## Requirements
### Requirement: FS op duration histogram

The system SHALL register a Prometheus histogram named `fs_op_duration_seconds` at module scope in `apps/api/app/services/storage/metrics.py` with labels `(operation, mode, status)` and bucket boundaries `(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)` seconds. The histogram SHALL be registered against the default `prometheus_client.REGISTRY` so the existing API `/metrics` endpoint and the worker's port-9100 server both serve it.

Every call to `record_fs_op(op, *, duration_ms, error=None, ...)` SHALL emit one `observe(duration_ms / 1000.0)` on this histogram with labels:
- `operation` = the FS op constant value (e.g. `"sbx_acquire"`).
- `mode` = `labels.get("mode", "none")` — only `sbx_acquire` and a handful of acquire-path ops carry this.
- `status` = `"error"` if `error is not None`, else `"ok"`.

#### Scenario: Successful op observation
- **WHEN** a call records `FS_OPS.SBX_ACQUIRE` with `duration_ms=42.5`, `mode="hit"`
- **THEN** `/metrics` on the same process includes a line matching `fs_op_duration_seconds_bucket{operation="sbx_acquire",mode="hit",status="ok",le="0.05"} 1`

#### Scenario: Failed op observation
- **WHEN** a call records `FS_OPS.TOOL_BASH` with `duration_ms=120` and a non-None error
- **THEN** the corresponding histogram observation carries `status="error"`

#### Scenario: Default mode label
- **WHEN** a call records `FS_OPS.SBX_HEALTH_PROBE` with no `mode` label
- **THEN** the observation carries `mode="none"`

### Requirement: FS op byte counter

The system SHALL register a Prometheus counter `fs_op_bytes_total` with label `(operation)` against the default registry. `record_fs_op` SHALL increment it by `bytes` only when `bytes > 0`. `add_fs_bytes(op, n)` SHALL also increment it when `n > 0`.

#### Scenario: Write reports bytes
- **WHEN** `record_fs_op(FS_OPS.WRITE_SESSION_FILE, duration_ms=4.2, bytes=2048)` is called
- **THEN** `/metrics` includes `fs_op_bytes_total{operation="write_session_file"} 2048` (or higher if accumulated across calls)

#### Scenario: Zero-byte op does not bump counter
- **WHEN** `record_fs_op(FS_OPS.STAT_ARTIFACT, duration_ms=0.5, bytes=0)` is called
- **THEN** the counter for `stat_artifact` is unchanged

### Requirement: Idempotent registration under reload

The system SHALL register both collectors through a `_register_once(name, factory)` helper that catches `ValueError("Duplicated timeseries...")` from `prometheus_client` and returns the previously-registered collector by looking it up in `REGISTRY._names_to_collectors`. Module re-imports under `uvicorn --reload` or duplicate test-fixture loads SHALL NOT raise.

#### Scenario: Reload preserves collector
- **WHEN** the metrics module is imported twice in the same Python process
- **THEN** no exception is raised
- **AND** subsequent `record_fs_op` calls observe into the same underlying collector

### Requirement: Prometheus emit is non-fatal

The system SHALL wrap the Prometheus `observe` and `inc` calls inside `record_fs_op` / `add_fs_bytes` in `try/except Exception` blocks. Any exception SHALL be logged once at `WARNING` level with structured fields `{op, error_type}` and SHALL NOT propagate. The ContextVar bucket update SHALL run regardless.

#### Scenario: Prometheus failure does not break wide event
- **WHEN** the Prometheus client raises during `observe()`
- **THEN** `record_fs_op` returns normally
- **AND** the corresponding `_bucket()` entry is still mutated so `flush_fs_metrics()` emits the wide-event field

### Requirement: Label cardinality discipline

The histogram SHALL accept only the labels `operation`, `mode`, `status`. The counter SHALL accept only `operation`. The module SHALL include a docstring comment at the collector declarations enumerating the allowed labels and stating that adding a new label requires updating both this spec and the collector signature.

High-cardinality identifiers (`user_id`, `conv_id`, `shard_id`, file paths, run ids) SHALL NOT be added as labels. They remain available on the wide event for per-request inspection.

#### Scenario: Series count is bounded
- **WHEN** the API process has served 1000 requests across 50 users, 200 conversations, and 8 shards
- **THEN** the active series count for `fs_op_duration_seconds` is bounded by `len(FS_OPS) * 5 modes * 2 statuses ≤ 250`

### Requirement: Worker process exports the same metrics

The same `record_fs_op` funnel is reused inside ARQ tasks (e.g., `prune_inactive_sessions`, `prewarm_sandbox_pool`). The worker's existing standalone metrics server (`apps/api/app/workers/metrics.py:start_metrics_server` on `ARQ_METRICS_PORT`) SHALL serve `fs_op_duration_seconds` and `fs_op_bytes_total` alongside the worker's pre-existing `arq_task_*` metrics. No worker-side code changes SHOULD be required — collectors registered with the default registry are picked up automatically.

#### Scenario: Worker /metrics carries fs ops
- **WHEN** an ARQ task body calls `record_fs_op(FS_OPS.LIST_STALE_SESSIONS, duration_ms=3.1)`
- **THEN** a subsequent `GET arq_worker:9100/metrics` response contains `fs_op_duration_seconds_bucket{operation="list_stale_sessions",...}` lines

### Requirement: Grafana dashboard

The repo SHALL ship `infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json` containing at minimum:
- Time-series panel: per-op p50/p95/p99 of `fs_op_duration_seconds` over the selected time range, using `histogram_quantile(...)` PromQL.
- Time-series panel: per-op error rate as `sum by (operation) (rate(fs_op_duration_seconds_count{status="error"}[5m])) / sum by (operation) (rate(fs_op_duration_seconds_count[5m]))`.
- Time-series panel: throughput as `sum by (operation) (rate(fs_op_bytes_total[5m]))`.
- Row dedicated to `sbx_acquire` with panels broken down by `mode` label.

The JSON file SHALL be valid for Grafana 11+ and auto-provisioned via the existing dashboard provisioner configuration. The dashboard SHALL render without errors against an empty Prometheus database (no series yet).

#### Scenario: Dashboard loads
- **WHEN** Grafana starts with the JSON in place
- **THEN** a dashboard titled "FS Ops" appears in the Grafana UI under the existing folder
- **AND** all panels load without "query error" indicators when Prometheus has at least one scrape of data

### Requirement: Supersede prior Redis-ring metric pieces

The four superseded items from the unarchived sibling change `e2b-perf-metrics-and-improvements` SHALL be removed from that change's `tasks.md` and `proposal.md` as part of this change's implementation. Specifically:

- Task 1.7 (Redis ring writer helper), Task 1.8 (modify `flush_fs_metrics` to push ring tuples), Task 1.9 (`SANDBOX_METRICS_RING_TTL_SECONDS`, `SANDBOX_METRICS_RING_MAX_SAMPLES` settings), Task 1.10 (`GET /api/v1/dev/sandbox-metrics` admin endpoint).
- The proposal bullet "Redis-backed rolling histogram (p50/p95/p99) per op, sourced from a Redis-backed ring buffer..." SHALL be replaced with a one-line pointer to this change.

The sibling change's remaining tasks (mode label, lock-wait timer, mount sub-steps, warm pool, fast path, prewarm endpoint, benchmark harness) are independent and SHALL be preserved.

#### Scenario: Sibling change is updated
- **WHEN** this change is applied
- **THEN** `openspec/changes/e2b-perf-metrics-and-improvements/tasks.md` no longer contains lines `1.7`, `1.8`, `1.9`, `1.10`
- **AND** its `proposal.md` references this change for the percentile surface

### Requirement: Wide-event field remains during transition

The wide-event `fs={...}` field emitted by `flush_fs_metrics()` SHALL continue to function unchanged. Removing it requires (a) the Grafana dashboard live in production AND (b) at least 7 calendar days of equivalent data observed in both surfaces. Removal is explicitly out of scope for this change.

#### Scenario: Dual-write preserved
- **WHEN** a chat turn completes after this change is deployed
- **THEN** the canonical wide-event log line still contains the `fs={...}` field with the same op-keyed dict shape as before
- **AND** the same observations are present in `/metrics`

