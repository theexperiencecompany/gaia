## 1. Prometheus collector registration

- [x] 1.1 In `apps/api/app/services/storage/metrics.py`, add imports: `from prometheus_client import Counter, Histogram, REGISTRY`. Add a module-private `_register_once(name, factory)` helper that catches `ValueError` from duplicate registration and returns the existing collector via `REGISTRY._names_to_collectors[name]`.
- [x] 1.2 Declare `_FS_OP_DURATION_SECONDS` via `_register_once("fs_op_duration_seconds", lambda: Histogram(name="fs_op_duration_seconds", documentation="FS_OPS measurement duration in seconds", labelnames=("operation", "mode", "status"), buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)))`.
- [x] 1.3 Declare `_FS_OP_BYTES_TOTAL` via `_register_once("fs_op_bytes_total", lambda: Counter(name="fs_op_bytes_total", documentation="FS_OPS measurement byte volume", labelnames=("operation",)))`.
- [x] 1.4 Add a docstring comment above the declarations enumerating the allowed labels (`operation`, `mode`, `status` for the histogram; `operation` for the counter) and stating that adding a label requires a spec update.

## 2. Dual-write in record_fs_op + add_fs_bytes

- [x] 2.1 In `record_fs_op`, after the existing ContextVar bucket mutation, append a `try/except Exception` block that calls `_FS_OP_DURATION_SECONDS.labels(operation=op, mode=labels.get("mode", "none") or "none", status="error" if error is not None else "ok").observe(duration_ms / 1000.0)`. On exception, `log.warning("[metrics] prometheus observe failed", op=op, error_type=type(e).__name__)`. Import the contextual logger if not already imported.
- [x] 2.2 In `record_fs_op`, when `bytes > 0`, also call `_FS_OP_BYTES_TOTAL.labels(operation=op).inc(bytes)` inside the same try/except.
- [x] 2.3 In `add_fs_bytes`, after the existing bucket mutation, mirror the counter increment with the same try/except guard.
- [ ] 2.4 Smoke-test in dev: start the API, drive 3-4 chat turns, then `curl -H "Authorization: Bearer $METRICS_TOKEN" localhost:8000/metrics | grep fs_op_` and confirm both metric families appear with non-zero values. **(Deferred — requires live API; run after merge.)**

## 3. Worker process verification

- [x] 3.1 Confirmed: `apps/api/app/workers/metrics.py` uses a **custom** `CollectorRegistry`, not the default. Patched the module to cross-register `_FS_OP_DURATION_SECONDS` and `_FS_OP_BYTES_TOTAL` onto its `REGISTRY` so the worker's port-9100 server serves them alongside `arq_task_*`. The same collector instance is shared by both registries.
- [ ] 3.2 Run an ARQ task (`prune_inactive_sessions` if landed, else any task that touches host-side JuiceFS), then `curl localhost:9100/metrics | grep fs_op_` and confirm the worker process exports the same families. **(Deferred — requires live worker; run after merge.)**
- [x] 3.3 Note for PR description: worker uses a custom `CollectorRegistry`. This change cross-registers the new fs_op collectors onto it so they appear on both `/metrics` endpoints without touching the existing `arq_task_*` collectors.

## 4. Sibling change cleanup

- [x] 4.1 Edited `openspec/changes/e2b-perf-metrics-and-improvements/tasks.md`: deleted tasks 1.7, 1.8, 1.9, 1.10. Renumbered 1.11–1.13 to 1.7–1.9 and added a one-line note under section 1 header pointing at `fs-metrics-to-prometheus`.
- [x] 4.2 Edited `openspec/changes/e2b-perf-metrics-and-improvements/proposal.md`: replaced the `GET /api/v1/dev/sandbox-metrics` bullet with a Prometheus + Grafana pointer; trimmed the `sandbox-metrics` capability description accordingly.
- [x] 4.3 Edited `openspec/changes/e2b-perf-metrics-and-improvements/specs/sandbox-metrics/spec.md`: deleted the "Rolling percentile ring buffer" and "Sandbox metrics admin endpoint" requirements, replaced with one requirement delegating percentile dashboards to `fs-metrics-prometheus`.
- [x] 4.4 `openspec validate e2b-perf-metrics-and-improvements` reports the change is valid.

## 5. Grafana dashboard

- [x] 5.1 Created `infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json`. Matches the JSON shape used by `arq-worker.json` in the same directory (annotations, links, panels, schemaVersion 39).
- [x] 5.2 Required panels present:
  - **Per-op duration percentiles**: three side-by-side panels (p50/p95/p99) querying `histogram_quantile(...)` over `fs_op_duration_seconds_bucket`, legend `{{operation}}`.
  - **Per-op error rate**: `sum by (operation) (rate(fs_op_duration_seconds_count{status="error"}[5m])) / clamp_min(sum by (operation) (rate(fs_op_duration_seconds_count[5m])), 1e-9)` (clamp guards against division-by-zero on idle ops), unit `percentunit`.
  - **Byte throughput**: `sum by (operation) (rate(fs_op_bytes_total[5m]))`, unit `Bps`.
  - **`sbx_acquire` mode breakdown row**: p99 by mode + acquire rate by mode (stacked).
- [x] 5.3 JSON validated locally via `python3 -m json.tool` — well-formed.
- [ ] 5.4 Cross-check panel rendering after one chat turn: at least the `tool_bash` and `sbx_acquire` operations should populate within ~30s. **(Deferred — requires Grafana + live API; run after merge.)**

## 6. Documentation + sign-off

- [x] 6.1 Added a "Prometheus export" section to the module docstring at the top of `apps/api/app/services/storage/metrics.py` describing both collectors, label discipline, and dashboard location.
- [x] 6.2 Added an "Observability" section to `apps/api/CLAUDE.md` between Testing and Environment, covering the three surfaces (wide events, Prometheus, Grafana), the scrape commands, and the deprecation note for the `fs={...}` log field.
- [x] 6.3 `nx lint api` → all checks passed. `nx type-check api` → no issues found in 601 source files. `openspec validate fs-metrics-to-prometheus` → valid.
