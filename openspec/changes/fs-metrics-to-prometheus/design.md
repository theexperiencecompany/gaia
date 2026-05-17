## Context

The existing Prometheus surface in this repo:

- **API process** — `apps/api/app/core/app_factory.py:55-73` mounts `prometheus_fastapi_instrumentator.Instrumentator().instrument(app).expose(...)`. The instrumentator writes into the default `prometheus_client.REGISTRY`. `/metrics` is token-gated in production (`METRICS_TOKEN` bearer), open in dev. Only framework-level HTTP metrics today; no custom collectors are declared anywhere on the API side.
- **ARQ worker process** — `apps/api/app/workers/metrics.py:22-37` defines a *custom* `CollectorRegistry`, plus `arq_task_duration_seconds` (Histogram, `(task_name, status)`, buckets `0.05–600s`) and `arq_task_total` (Counter). The worker exposes them via `prometheus_client.start_http_server` on `ARQ_METRICS_PORT` (default 9100). The pattern is wrapped in `@instrument_task(name=...)` which times every ARQ task body and labels by `status="success"|"error"`.
- **Scrape config** — `infra/docker/observability/prometheus.yml` scrapes both: `gaia-api:80/metrics` (bearer-authed) and `arq_worker:9100`. Grafana datasource is pre-provisioned with uid `prometheus`.

The `FS_OPS` framework in `apps/api/app/services/storage/metrics.py` already gates every measurement through one funnel function — `record_fs_op(op, *, duration_ms, error=None, bytes=0, **labels)`. Adding Prometheus export to that single function instruments every existing and future timer with no call-site change.

## Goals / Non-Goals

**Goals:**
- Every `FS_OPS` measurement appears in Prometheus as a histogram observation with bounded-cardinality labels, on both API and worker processes.
- Grafana can render p50/p95/p99/error-rate/throughput per op without any LogQL involvement.
- The existing `fs={...}` wide-event log field continues to work unchanged; nothing has to migrate atomically.
- Replace the Redis ring buffer + dev endpoint from the unarchived sibling change so we don't ship two ways to view the same data.

**Non-Goals:**
- Removing the wide-event `fs={...}` field. That's a follow-up tracked as a deprecation gate, not part of this change.
- Migrating the ARQ task metrics off their custom registry. They work, the scrape is established, and changing it adds risk for no win.
- Adding cross-process aggregation, alerting rules, or SLO definitions. Dashboard only; alerts are a separate exercise after the data shape is proven.
- Introducing OpenTelemetry. Prometheus is already in place; adding OTEL is a different decision with its own trade-offs.

## Decisions

**1. One Histogram, one Counter — labeled by operation.**
A single `fs_op_duration_seconds` histogram with `(operation, mode, status)` labels covers the entire `FS_OPS` taxonomy. `mode` defaults to `"none"` for ops that don't use it; `status` is `"ok"` or `"error"`. Considered: one collector per op (e.g., `sbx_acquire_duration_seconds`, `tool_bash_duration_seconds`). Rejected — explodes the dashboard count and forces hard-coding the op list at metric declaration time. With labels, adding a new `FS_OPS.*` constant is automatic.

**2. Use the default registry on both processes.**
Declare collectors as `Histogram(..., registry=None)` — `prometheus_client` resolves `None` to the default `prometheus_client.REGISTRY`, which is what `Instrumentator` and `start_http_server` both serve. Considered: a dedicated `FS_REGISTRY` like the worker's `arq_task_*` setup. Rejected — that would force a second `/metrics` listener on the API process, and the worker already serves the default registry on top of its own; using the default everywhere avoids that fork.

**3. Bucket choice — sub-millisecond through 10s.**
Buckets `(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)` seconds. Covers `SBX_LOCK_WAIT` (sub-ms uncontended), `SBX_CANARY_VERIFY` (~50ms), `SBX_MOUNT_SCRIPT` (~1–5s), `SBX_CREATE` (~1–3s), and worst-case mount timeouts (60s). Considered: reusing the ARQ buckets (`0.05–600s`). Rejected — too coarse; sub-100ms ops (lock wait, ensure-mounted, canary read) all collapse into the smallest bucket and lose all signal.

**4. `record_fs_op` dual-writes; no separate "prometheus mode" flag.**
Inside `record_fs_op`, after the ContextVar bucket update, additionally call `FS_OP_DURATION_SECONDS.labels(operation=op, mode=labels.get("mode", "none"), status="error" if error else "ok").observe(duration_ms / 1000.0)`. Bytes: `FS_OP_BYTES_TOTAL.labels(operation=op).inc(bytes)` only when `bytes > 0`. Wrap the Prometheus emits in `try/except` with a one-line `log.warning` so a registry bug never breaks the wide event. Considered: only emit when `PROMETHEUS_ENABLED=true`. Rejected — there's no useful state where logs are desired but metrics are not; the env var is dead weight.

**5. Label discipline: `operation`, `mode`, `status` only.**
No `user_id`, `conv_id`, `shard_id`, or path. Those are high-cardinality and belong in the wide event, not the metric. The `labels` kwarg on `record_fs_op` continues to attach arbitrary keys to the ContextVar bucket — but only `mode` is forwarded into Prometheus. Considered: `served_from` label for warm-pool hits. Rejected for v1 — it's measurable via the wide event field; if the warm-pool dashboard needs it, add it under a controlled allowlist later.

**6. Idempotent registration helper.**
Wrap collector declarations in `_register_once(name, factory)` that catches `ValueError("Duplicated timeseries...")` and returns the already-registered collector via `REGISTRY._names_to_collectors`. Solves the test-fixture re-import case where the module is loaded twice in the same process. Considered: top-level `try/except` per declaration. Equivalent but noisier; helper keeps the module readable.

**7. Grafana dashboard checked into the repo.**
Provisioned via `infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json`, picked up by Grafana's filesystem provisioner on container restart. Panels: per-op p50/p95/p99 time-series, error-rate gauge, byte-throughput time-series, plus a dedicated row for `sbx_acquire` filtered by `mode={hit, hit_fast, resume, cold_create, prewarm}`. PromQL queries use `histogram_quantile(0.99, sum by (le, operation) (rate(fs_op_duration_seconds_bucket[5m])))`.

**8. Companion change cleanup is part of this change, not a follow-up.**
The four superseded items in `e2b-perf-metrics-and-improvements/tasks.md` are physically struck through in this change's tasks list — Task 4.x. Keeps the workspace consistent so the next person reading the prior change doesn't implement work this change has obsoleted.

## Risks / Trade-offs

- **Histogram cardinality drift.** A future contributor adds `(operation, mode, status, shard)` and quietly 5×s the series count. → Add a unit test (when tests are allowed) and a docstring comment at the collector declaration enumerating allowed labels.
- **Registry collisions under reload.** `uvicorn --reload` re-imports the module on file save, raising `Duplicated timeseries` on the second import. → `_register_once` swallows the duplicate and returns the existing collector. Verified to work in `prometheus_client` ≥ 0.20.
- **`/metrics` scrape interval ≠ wide-event aggregation window.** The wide-event `fs={...}` is per-request; Prometheus scrapes every 15s. Dashboards aggregate over 5m by default. → Documented in dashboard panel descriptions; the wide event remains the per-request truth.
- **Production `/metrics` is bearer-gated.** Prometheus scraper already has the token (Vault secret `gaia_metrics_token`). No action needed; flag it in the rollout notes so anyone curl'ing locally remembers `-H "Authorization: Bearer ${METRICS_TOKEN}"`.
- **Worker process emits the same metric name.** That's intentional — Prometheus distinguishes by `job` label (`gaia-api` vs `arq_worker`). PromQL queries that ignore `job` get unified rates; queries that filter on `job` get per-process views.
- **Dual-write masks the eventual log removal.** If we never build the Grafana dashboard, the `fs={...}` log field stays forever as a "just in case" fallback. → The deprecation gate is explicit in the spec: log field removal requires the dashboard live + 7 days of confirmed equivalence. Not removing both is fine; never removing either is the failure mode.

## Migration Plan

1. **Land the collector declarations + dual-write.** Ship to staging. Verify `/metrics` returns `fs_op_duration_seconds_*` lines and `fs_op_bytes_total` lines.
2. **Push Grafana dashboard JSON.** Provisioned at container restart; verify panels populate within one scrape cycle (15s).
3. **Production deploy.** No flag gate; the dual-write is non-behavioral. Monitor `/metrics` payload size for one day (we expect <100 KB additional per scrape on the API process).
4. **Deprecation watch.** After 7 days of green dashboards, file a follow-up to remove `fs={...}` from `flush_fs_metrics` and re-route the canonical wide-event field to `log.set(fs_summary=...)` with op count + total only (for log-readability). Out of scope here.

Rollback: revert the metrics.py edit. No data migration. The Grafana JSON can stay; it just renders empty panels.

## Open Questions

- **Should the dashboard live under the existing `infra/docker/observability/grafana/provisioning/dashboards/` directory or a `fs/` subdirectory?** Either works; subdirectory if the dashboard list grows. Decide at PR time.
- **Native histograms (Prometheus 3.x) vs classic histograms.** The scraper is `prom/prometheus:v3.1.0` which supports native histograms. We use classic for now (smaller blast radius, same PromQL). Migration is a one-line change later if cardinality becomes a concern.
