## ADDED Requirements

### Requirement: Per-shard warm sandbox pool

The system SHALL maintain a per-shard deque of pre-created paused sandboxes (the warm pool), targeting `E2B_WARM_POOL_TARGET` entries per shard. The pool SHALL live at module scope inside `apps/api/app/services/sandbox/warm_pool.py` and SHALL be guarded by an `asyncio.Lock` per shard.

Warm-pool entries SHALL be `AsyncSandbox` instances that have been created, had `mount_juicefs.sh` executed once successfully, and then `pause()`'d. They SHALL not be assigned to any `user_id` until handed out.

The target count SHALL be enforced by a periodic ARQ task `prewarm_sandbox_pool` registered in `apps/api/app/workers/tasks/sandbox_tasks.py` and scheduled via cron in `apps/api/app/worker.py` to run every `WARM_POOL_REFRESH_SECONDS` (default 30s).

#### Scenario: Pool fills to target
- **WHEN** `E2B_WARM_POOL_TARGET = 2` and `prewarm_sandbox_pool` runs against an empty pool
- **THEN** after the task completes, the per-shard deque contains exactly 2 paused sandboxes (one creation cycle per shard slot)

#### Scenario: Pool replenishes after handout
- **WHEN** a cold-acquire consumes a warm sandbox, dropping the count to `target - 1`
- **THEN** the next `prewarm_sandbox_pool` run creates and pauses one replacement

#### Scenario: Quota ceiling honored
- **WHEN** `E2B_WARM_POOL_TARGET` would push the live sandbox count past the configured account ceiling
- **THEN** the task creates only up to the ceiling and emits `log.warning("[warm_pool] quota ceiling reached", shard=..., live=..., target=...)`

### Requirement: Acquire handout from warm pool

The system SHALL consult the warm pool before creating a fresh sandbox in `_acquire_or_create`. When the pool has an available entry for the request's shard, the entry SHALL be popped, resumed, bound to the user via the existing Mongo `e2b_sandboxes` record update, and added to the user's `PooledSandbox` slot.

A successful warm-pool handout SHALL record `SBX_ACQUIRE` with `mode="cold_create"` (the user-facing path is the same as a cold create) AND a label `served_from="warm_pool"` so we can measure how often the pool is hitting.

When the warm pool is empty, `_acquire_or_create` SHALL fall back to the existing fresh-create path with no behavioral change.

#### Scenario: Warm pool hit
- **WHEN** the warm pool has at least one entry for the request shard and a cold acquire is requested
- **THEN** the chosen sandbox is the popped one (verified by sandbox id)
- **AND** the wide event records `fs.sbx_acquire.labels.served_from = "warm_pool"`
- **AND** no `fs.sbx_create` measurement is recorded for that acquire

#### Scenario: Warm pool empty falls back
- **WHEN** the warm pool deque for the shard is empty
- **THEN** `_acquire_or_create` falls back to `_create_fresh_sandbox`
- **AND** records `fs.sbx_create.count >= 1`

### Requirement: Warm pool disabled by zero target

The system SHALL treat `E2B_WARM_POOL_TARGET = 0` as a hard disable. When zero:
- The `prewarm_sandbox_pool` task SHALL exit early after logging `log.info("[warm_pool] disabled")`.
- `_acquire_or_create` SHALL skip the pool lookup and behave exactly as it does today.

This setting SHALL default to `0` on initial rollout so the feature ships dark.

#### Scenario: Zero target keeps behavior unchanged
- **WHEN** `E2B_WARM_POOL_TARGET = 0`
- **THEN** the warm pool deques stay empty across multiple `prewarm_sandbox_pool` runs
- **AND** every cold acquire records `fs.sbx_create.count >= 1`
