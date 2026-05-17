## ADDED Requirements

### Requirement: Acquire-path labeling

The system SHALL record every `SBX_ACQUIRE` measurement with a low-cardinality `mode` label whose value is one of `hit`, `hit_fast`, `resume`, `cold_create`, `prewarm`.

The mode SHALL be derived inside `_acquire_or_create` from the branch actually taken, before `fs_timer` exits, so the wide event field `fs.sbx_acquire.labels.mode` reflects the path executed for that request.

#### Scenario: Cache hit records mode=hit
- **WHEN** an `acquire_sandbox(user_id)` call finds a healthy `PooledSandbox` in the pool and the health probe + canary verify both succeed
- **THEN** the wide event field `fs.sbx_acquire.labels.mode` equals `hit`
- **AND** `fs.sbx_create.count` is 0 for that request

#### Scenario: Cold create records mode=cold_create
- **WHEN** an `acquire_sandbox(user_id)` call has no pooled entry and no resumable Mongo record
- **THEN** the wide event field `fs.sbx_acquire.labels.mode` equals `cold_create`
- **AND** `fs.sbx_create.count` is at least 1 for that request

#### Scenario: Resume records mode=resume
- **WHEN** `acquire_sandbox(user_id)` resumes a paused sandbox via `AsyncSandbox.connect()` or `.resume()`
- **THEN** `fs.sbx_acquire.labels.mode` equals `resume`
- **AND** `fs.sbx_connect_resume.count` is at least 1

### Requirement: Lock-wait timer

The system SHALL record a `SBX_LOCK_WAIT` measurement around acquisition of `PooledSandbox.lock` so that contention between concurrent acquires for the same user is observable as its own bucket.

The timer SHALL start before `async with entry.lock:` and stop the moment the lock is held.

#### Scenario: Uncontended lock acquisition
- **WHEN** no other coroutine holds `entry.lock`
- **THEN** the wide event records `fs.sbx_lock_wait` with `count >= 1` and `total_ms` near zero (sub-millisecond)

#### Scenario: Contended lock acquisition
- **WHEN** a second concurrent `acquire_sandbox` for the same user runs while a long mount is in progress
- **THEN** the second request's wide event records `fs.sbx_lock_wait.total_ms` close to the mount duration

### Requirement: Mount sub-step tracing

The mount script `apps/api/scripts/mount_juicefs.sh` SHALL print one timing marker per discrete heavy step in the format `GAIA_TIMING <step> <ms>` on its own line. The Python wrapper `_run_mount_script` SHALL parse those markers from captured stdout and replay each through `record_fs_op` with the corresponding FS op constant.

Required steps and their op constants:
- `mount_user` → `SBX_MOUNT_JFS_USER`
- `mount_skills` → `SBX_MOUNT_JFS_SKILLS`
- `bind_workspace` → `SBX_MOUNT_BIND_WORKSPACE`
- `bind_skills` → `SBX_MOUNT_BIND_SKILLS`
- `canary_write` → `SBX_MOUNT_CANARY_WRITE`

The script SHALL continue to succeed and return its existing exit codes even if marker parsing fails on the Python side. Parsing errors SHALL emit a single `log.warning(...)` and not block the acquire.

#### Scenario: All markers parsed
- **WHEN** a cold-create runs `mount_juicefs.sh` end-to-end successfully
- **THEN** the wide event's `fs` field contains entries for each of `sbx_mount_jfs_user`, `sbx_mount_jfs_skills`, `sbx_mount_bind_workspace`, `sbx_mount_bind_skills`, `sbx_mount_canary_write`
- **AND** the sum of their `total_ms` is bounded above by `fs.sbx_mount_script.total_ms`

#### Scenario: Optional step skipped
- **WHEN** the skills subdir is absent and `mount_skills` is skipped by the script
- **THEN** the wide event does not contain `sbx_mount_jfs_skills` and the acquire still succeeds

### Requirement: Cache-hit overhead bucket

The system SHALL record a `SBX_ACQUIRE_OVERHEAD` measurement covering exactly the health probe + canary verify pair on cache-hit acquires, so the floor cost of "always paying the safety tax" is visible separately from the rest of the acquire flow.

When the fast-path (Requirement: Cache-hit fast path in `sandbox-fast-path` capability) skips these checks, `SBX_ACQUIRE_OVERHEAD.count` SHALL be 0 for that acquire.

#### Scenario: Slow-path hit records overhead
- **WHEN** an acquire enters the cache-hit branch and runs both health probe and canary verify
- **THEN** `fs.sbx_acquire_overhead.count >= 1`
- **AND** `fs.sbx_acquire_overhead.total_ms ≈ fs.sbx_health_probe.total_ms + fs.sbx_canary_verify.total_ms`

#### Scenario: Fast-path hit skips overhead
- **WHEN** an acquire takes the fast path (`mode=hit_fast`)
- **THEN** `fs.sbx_acquire_overhead.count = 0` for that request

### Requirement: Percentile dashboards delegated to fs-metrics-prometheus

Per-op percentile dashboards (p50/p95/p99/max), error rates, and the per-mode `sbx_acquire` breakdown SHALL be served via the Prometheus + Grafana surface defined by the sibling capability `fs-metrics-prometheus`. This capability does not define its own ring buffer, in-process histogram, or admin endpoint — the labeled `SBX_ACQUIRE` measurement defined above flows through `record_fs_op` into the Prometheus collectors, and Grafana renders the panels.

#### Scenario: Mode label reaches Grafana
- **WHEN** an `sbx_acquire` measurement records `mode="cold_create"` via `record_fs_op`
- **THEN** Prometheus `fs_op_duration_seconds{operation="sbx_acquire",mode="cold_create",status="ok"}` increments
- **AND** the **FS Ops** Grafana dashboard renders that observation in the acquire-mode breakdown row

### Requirement: Repeatable benchmark harness

The repo SHALL provide `apps/api/scripts/bench_sandbox_acquire.py` that drives N×M acquires across all shards exercising the three primary paths (cold-create, resume, cache-hit) and prints a markdown summary table of p50/p95/p99 per mode per shard.

The script SHALL accept `--user-id`, `--iterations`, `--shards`, `--modes` arguments. It SHALL be invokable inside the API container via `python scripts/bench_sandbox_acquire.py ...` and SHALL not require pytest.

#### Scenario: Benchmark prints summary
- **WHEN** the script runs `--iterations 5 --modes cold_create,resume,hit`
- **THEN** stdout contains a markdown table with columns `mode`, `shard`, `p50_ms`, `p95_ms`, `p99_ms`, `samples`
- **AND** exits with code 0 on success
