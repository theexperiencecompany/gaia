## Why

Prometheus is already wired into both the API process (`prometheus-fastapi-instrumentator` exposing `/metrics`) and the ARQ worker (standalone metrics server on port 9100 with custom histograms like `arq_task_duration_seconds`). Grafana is provisioned with the Prometheus datasource. The `FS_OPS` metrics framework in `apps/api/app/services/storage/metrics.py` currently emits per-request aggregates only into the `fs={...}` wide-event log field — useful for canonical log analysis but invisible to Grafana, missing percentiles without LogQL gymnastics, and not scrapeable.

The sibling change `e2b-perf-metrics-and-improvements` (still in proposal state, not yet applied) proposed a Redis ring buffer plus a custom `GET /api/v1/dev/sandbox-metrics` endpoint to surface percentiles. That was the right answer before noticing Prometheus is already wired up; with Prometheus present, the ring buffer and dev endpoint are duplicate plumbing.

## What Changes

- Register two custom Prometheus collectors at module scope in `apps/api/app/services/storage/metrics.py`:
  - `fs_op_duration_seconds` — Histogram, labels `(operation, mode, status)`, seconds-scaled buckets tuned for the actual op range (sub-ms lock acquires through multi-second cold creates).
  - `fs_op_bytes_total` — Counter, label `(operation)`, for ops that report byte volume (`WRITE_SESSION_FILE`, tool writes, upload).
- `record_fs_op` (the single funnel for all FS measurements) writes to Prometheus AND keeps mutating the existing ContextVar bucket. Zero changes to call sites.
- Use the default `prometheus_client.REGISTRY` on the API side so the existing `/metrics` endpoint picks them up automatically. On the worker side, also register with the default registry (the worker's standalone metrics server already serves it).
- Add a Grafana dashboard JSON checked in at `infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json` covering: per-op p50/p95/p99, error rate, byte throughput, and the `sbx_acquire` mode breakdown.
- **Supersedes** these items from the unarchived `e2b-perf-metrics-and-improvements` change:
  - 1.7 (Redis ring writer helper)
  - 1.8 (modify `flush_fs_metrics` to push ring tuples)
  - 1.9 (`SANDBOX_METRICS_RING_TTL_SECONDS`, `SANDBOX_METRICS_RING_MAX_SAMPLES` settings)
  - 1.10 (`GET /api/v1/dev/sandbox-metrics` admin endpoint)
- Keep the `fs={...}` wide-event log field for now. Deprecation is gated on the Grafana dashboard being live and verified equivalent for ≥7 days in production.

## Capabilities

### New Capabilities
- `fs-metrics-prometheus`: Server- and worker-process Prometheus exports for every `FS_OPS` measurement, with bounded-cardinality labels and Grafana coverage. Includes the supersede + cleanup contract against the prior unarchived change.

### Modified Capabilities
*(none — `openspec/specs/` is empty; this is the first surface to formalize the metrics contract)*

## Impact

- **Code touched**: `apps/api/app/services/storage/metrics.py` (Prometheus collector declarations + `record_fs_op` dual-write), `apps/api/app/services/storage/__init__.py` (no re-export changes needed — collectors are internal), Grafana dashboard JSON under `infra/docker/observability/grafana/provisioning/dashboards/`.
- **No new dependencies.** `prometheus_client` is already pinned.
- **No new endpoints.** The existing `/metrics` route on the API and the worker's port-9100 server already serve the default registry.
- **Cardinality**: ~25 operations × up to 5 mode values × 2 statuses = ≤ 250 active series per process. Prometheus handles this trivially.
- **Companion-change updates**: `e2b-perf-metrics-and-improvements/tasks.md` and `proposal.md` get a small revision to strike the four superseded items and point at this change instead. (Done in this change's tasks list.)
- **Risk**: A misregistered collector at import time could crash the API on startup (duplicate registration if the module is imported twice under tests). Mitigated by the standard `_check_existing_metric` guard pattern used by `prometheus_client` plus an idempotent `_register_once` helper.
