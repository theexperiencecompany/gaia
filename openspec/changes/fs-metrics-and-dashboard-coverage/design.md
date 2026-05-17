## Context

The smoke test of `fs-metrics-to-prometheus` confirmed end-to-end flow (chat → bash → `/metrics` → Prometheus → Grafana), but ten minutes after the chat the dashboard rolled back to empty: every panel is `rate(...[5m])`, and traffic in this product is bursty. The shape of the problem is "metrics ARE there, the dashboard query window has aged out." The shape of the fix is twofold:

1. Replace rate-only views with cumulative + gauge views that survive idle periods. Counters never decay; gauges hold their last value.
2. Add collectors that answer questions the existing two cannot: how many sandboxes are alive, what's in flight right now, what was the last thing that happened, did the bash command actually exit zero.

Concretely the existing system has two collectors (`fs_op_duration_seconds`, `fs_op_bytes_total`) driven from one funnel (`record_fs_op`) on the default Prometheus registry, re-registered on the worker registry. The pattern works; this change extends it.

## Goals / Non-Goals

**Goals:**
- Dashboard renders useful information at any point in time, including 30+ minutes after the last chat.
- Operator can see live sandbox count, in-flight ops, and recent bash exit codes from a single panel.
- Lifetime/cumulative totals are always visible — "is this op even reachable from my code?" is a one-glance check.
- Each new collector follows the existing idempotent-registration + dual-write pattern. Adding them is a no-cost extension of the funnel.

**Non-Goals:**
- Alerting rules. Dashboard only; alerts come after we've watched the data shape for a while.
- New scrape targets, new exporters, new endpoints. Default registry continues to be the single surface.
- Per-conversation or per-user labels. Cardinality stays bounded.
- Migrating the wide-event `fs={...}` field. Separate deprecation track, same constraint as before.

## Decisions

**1. `fs_op_total` Counter sits next to the existing Histogram, not inside it.**
The Histogram's `_count` series already exists as a side effect of `observe()`. We could query that directly — but it's awkward to filter on `_count` in Grafana and ambiguous to read in `/metrics`. A dedicated `fs_op_total` with identical labels is one extra `inc()` call per `record_fs_op` and gives dashboards a clean named series. Considered: derive everything from `_count`. Rejected — readability matters; one extra line of code is cheap.

**2. `fs_op_last_seen_unix_seconds` is a Gauge set on every `record_fs_op`.**
Each call: `_FS_OP_LAST_SEEN.labels(operation=op).set(time.time())`. Dashboard query `time() - fs_op_last_seen_unix_seconds{operation="sbx_acquire"}` returns "seconds since last fire" — Grafana renders it as "5m ago" via the `dateTimeFromNow` unit. Considered: derive from `fs_op_total` via `last_over_time(... [1h])`. Works but is fragile across scrape gaps; a dedicated timestamp gauge is canonical and cheaper to query.

**3. `fs_op_in_flight` is wired inside `fs_timer`, not `record_fs_op`.**
`record_fs_op` runs at the END of an operation (with the duration measured already). To count in-flight ops we need entry + exit hooks. `fs_timer` is exactly that — `try/yield/finally`. Add `.inc()` before yield and `.dec()` in the `finally`. Crash-safe: any exception path runs the `finally`. Considered: a separate `fs_in_flight(op)` context manager. Rejected — `fs_timer` is already that context manager; doubling them creates inconsistency.

**4. `sandbox_pool_size` is updated from `pool.py`, not from a periodic scrape callback.**
Gauges support set/inc/dec. The pool already mutates its internal `_entries` dict + warm pool deque on every add/remove. Add a `_publish_size()` helper that calls `sandbox_pool_size.labels(kind=...).set(len(...))` right after the mutation, under the existing lock. Considered: a Prometheus client `register_callback` that recomputes on scrape. Rejected — the scrape callback runs in a sync context; mixing it with our `asyncio.Lock` is non-trivial and the alternative is a single `.set()` call right where mutations happen.

**5. Bash exit codes go into bucketed labels, not raw values.**
Raw exit codes are 0–255 plus shell-defined "signal+128" conventions plus our own timeout sentinel. ~260 series per op is wasteful when 95% are 0 and the rest cluster in a few bands. Bucket into `0` (success), `1-126` (generic error), `127` (command not found), `128-254` (signal-killed), `255` (catch-all), `timeout` (our `_run_foreground` deadline). 6 series total. Considered: just `success` / `error`. Too coarse — "command not found" vs "signal-killed" matter for triage.

**6. Dashboard v2 leans on lifetime tables + wider windows.**
Three structural changes:

- A **lifetime totals table** at the top — `sum by (operation) (fs_op_total)` with `last_over_time(fs_op_last_seen_unix_seconds[1d])` as a "last seen" column. Always populated once the system has ever run. Sortable.
- **Percentile time-series widened to `[30m]`** for rate windows. This is enough to keep panels populated through normal idle gaps while still being short enough to highlight recent shifts.
- **In-flight ops + sandbox pool size** become primary panels (gauge-driven, never empty once observed).

Empty panels in v1 (`Error rate per op`, `Byte throughput per op`, `sbx_acquire by mode`) are kept but their queries get `or vector(0)` appended so they render a flat zero line — explicitly "healthy/quiet" rather than "broken/no-data." Considered: hide them when zero. Rejected — visible zero is the point; you want to see at a glance that error rate IS zero, not that the panel is broken.

**7. Default time range widens to `now-1h`.**
Matches the wider rate windows and gives one full hour of context on first open. Considered: `now-24h`. Rejected — Prometheus scrape retention is 30 days but Grafana panel queries get expensive past an hour for high-cardinality histograms.

**8. Rollback via git history, not a sibling `.bak`.**
The dashboard JSON is checked in; reverting is `git checkout <prior-sha> -- fs-ops.json`. A `.bak` file next to it just duplicates what git already tracks and creates a second source of truth that drifts.

## Risks / Trade-offs

- **In-flight gauge drift on async cancellation.** A coroutine cancellation between `inc()` and the `try:` body raises `CancelledError` before `finally` runs — Python re-raises through `finally`, so the `.dec()` still fires. Verified by `fs_timer`'s existing structure: `try/yield/finally` already handles `BaseException`.
- **`sandbox_pool_size` race.** Two coroutines mutating the pool concurrently could call `set()` in interleaved order. Acceptable — gauges are last-writer-wins by design, and we only care about the final count after each mutation, which is exactly what `set(len(...))` gives.
- **Cardinality.** `fs_op_total` mirrors the existing histogram's label set so it can't exceed it. `fs_op_in_flight` and `fs_op_last_seen_unix_seconds` are per-op only (≤25 series). The risk is someone later adding `mode` to `fs_op_in_flight` and quietly 5×s it. Mitigation: docstring + spec lock down the allowed labels.
- **`tool_bash_exit_code_total` bucket choices.** If users see lots of `1-126` and want a finer split, we re-bucket later. The buckets are not a stable wire contract; they're a v1 view.
- **Dashboard rebuild scope creep.** The JSON file is hand-maintained; large rewrites are error-prone. Mitigation: validate with `python3 -m json.tool` and load in a local Grafana before committing.

## Migration Plan

1. Ship the new collectors behind no flag. The wire signature of `record_fs_op` and `fs_timer` is unchanged from caller perspective; new collectors register at module load.
2. Replace `fs-ops.json` in one PR. Grafana picks up the new file on container restart.
3. Validate with a fresh chat turn that:
   - Lifetime totals table populates.
   - "Last seen" column shows recent timestamp for ops that fired during the chat.
   - In-flight gauge briefly spikes during the chat and returns to zero.
   - Bash exit code stat shows `0:1` after a successful `echo`.
Rollback: `git revert` the dashboard commit, or `git checkout <prior-sha> -- infra/docker/observability/grafana/provisioning/dashboards/fs-ops.json`. New collectors stay registered; they just aren't surfaced visually.

## Open Questions

- **Should `fs_op_last_seen_unix_seconds` exist for the worker process too?** The same operation can run in both the API and the worker. With per-process registries, each process maintains its own gauge value. Either we accept that "last seen" is per-process (probably fine — dashboards filter by `job`), or we'd need a centralized timestamp store, which is way out of scope. Decision: per-process, document the behavior in the dashboard panel description.
- **Add an `oldest_in_flight_seconds` gauge?** Useful for spotting stuck ops without a full histogram. Defer until we see actual stuck-op symptoms in practice.
- **Bucket boundary for `1-126` includes the standard `124` (timeout from coreutils).** Our own timeout sentinel is `"timeout"` (string). If a user runs `timeout` inside bash, it'll be in `1-126`, which is correct semantically but slightly confusing. Acceptable; documented in the bash tool's bucketing comment.
