## ADDED Requirements

### Requirement: Cache-hit fast path

The system SHALL skip the health probe and canary verify on cache-hit acquires when ALL of the following hold:

1. The `PooledSandbox.last_canary_ts` is non-null and within the last `E2B_CANARY_CACHE_SECONDS` seconds (default 10).
2. The entry's artifact watcher is attached and `watcher.is_alive()` returns true.
3. `last_canary_ts` has not been invalidated by a tool error since the previous acquire (see "Fast-path invalidation").

When all three hold, `_acquire_or_create` SHALL return the cached sandbox immediately and record `SBX_ACQUIRE` with `mode="hit_fast"`.

When any condition fails, the slow path runs (health probe + canary verify + watcher restart), recording `mode="hit"` on success.

#### Scenario: Back-to-back tool calls take fast path
- **WHEN** two `acquire_sandbox(user_id)` calls run within `E2B_CANARY_CACHE_SECONDS` of each other with no tool errors in between
- **THEN** the second acquire records `fs.sbx_acquire.labels.mode = "hit_fast"`
- **AND** `fs.sbx_health_probe.count = 0` for that request
- **AND** `fs.sbx_canary_verify.count = 0` for that request

#### Scenario: Window expired forces slow path
- **WHEN** the second acquire runs after `last_canary_ts + E2B_CANARY_CACHE_SECONDS`
- **THEN** the acquire records `mode = "hit"` (not `hit_fast`)
- **AND** the health probe and canary verify both run

#### Scenario: Watcher dead forces slow path
- **WHEN** the artifact watcher detached or died before the second acquire
- **THEN** the acquire records `mode = "hit"`
- **AND** both health probe and canary verify run

### Requirement: Fast-path invalidation on tool error

The system SHALL reset `PooledSandbox.last_canary_ts = None` whenever a tool invocation against the sandbox raises an exception, returns a non-zero exit code from `sbx.commands.run`, or fails the existing `_run_in_sandbox` error path. The reset SHALL happen inside the existing tool-error capture path in `_acquire_or_create` / `acquire_sandbox`'s exit handler.

The next acquire after a reset SHALL therefore take the slow path and re-verify canary, catching FUSE staleness that the fast path would otherwise mask.

#### Scenario: Bash error resets fast path
- **WHEN** a bash tool call returns exit code 137 (OOM / kill)
- **THEN** `last_canary_ts` is set to None
- **AND** the next acquire records `mode = "hit"`, not `hit_fast`

#### Scenario: Sandbox kill resets fast path
- **WHEN** `_hard_evict` runs for any reason
- **THEN** `last_canary_ts` is None on the next pooled entry (or the entry is gone entirely)

### Requirement: Fast path disabled by zero seconds

The system SHALL treat `E2B_CANARY_CACHE_SECONDS = 0` as a hard disable. With zero, every cache hit takes the slow path and records `mode="hit"`. This setting SHALL default to `0` on initial rollout; promotion to `10` is a separate flag flip after Phase A metrics confirm hit/hit_fast separation is clean.

#### Scenario: Zero seconds keeps slow path
- **WHEN** `E2B_CANARY_CACHE_SECONDS = 0`
- **THEN** every cache-hit acquire records `mode = "hit"`
- **AND** `fs.sbx_health_probe.count >= 1` for each

### Requirement: Frontend-triggered prewarm endpoint

The system SHALL expose `POST /api/v1/sandbox/prewarm` (authenticated, rate-limited via the existing `tiered_rate_limit` decorator at one call per user per 30s) that schedules `acquire_sandbox(user_id)` on a background task and returns `202 Accepted` immediately.

The background task SHALL acquire then release the sandbox on its own (via the context-manager exit) so the warm `PooledSandbox` survives and pause-scheduling reverts to the normal idle timer.

When the user already has a hot `PooledSandbox`, the call SHALL be a no-op that still returns 202.

#### Scenario: Prewarm creates pooled entry
- **WHEN** a user with no pooled sandbox calls `POST /api/v1/sandbox/prewarm`
- **THEN** the response is 202 within 100ms
- **AND** within 5 seconds, `SandboxPool` has a `PooledSandbox` for the user
- **AND** the next chat turn for that user takes the cache-hit (or hit_fast) path

#### Scenario: Prewarm is rate-limited
- **WHEN** the same user calls the endpoint twice within 30 seconds
- **THEN** the second call returns 429

#### Scenario: Prewarm is idempotent
- **WHEN** the user already has a healthy pooled sandbox and calls prewarm
- **THEN** the response is still 202
- **AND** no fresh sandbox is created (warm-pool / hit path)
