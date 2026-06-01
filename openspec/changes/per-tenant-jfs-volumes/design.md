## Context

JuiceFS today runs as a single shared volume across all users. One Postgres metadata DB (`gaia_juicefs_0`) holds every user's inodes; one R2 bucket holds every user's encrypted chunks behind a single shared `R2_ACCESS_KEY`. Tenant isolation is enforced at sandbox mount time only — `mount.sh` runs `juicefs mount --subdir /users/$USER_ID` so the kernel-visible tree inside the sandbox is scoped to that subdirectory. The credentials themselves grant volume-wide access; if anything reads them outside the sandbox (an admin path, a leaked env file, a future bug in `_mount_env`) it sees everyone's data.

Existing scaffolding for sharding exists (`JUICEFS_NUM_SHARDS`, `JUICEFS_META_URL_TEMPLATE`, `shard_router.shard_for`) but is hash-based for load distribution, not for isolation: shards 0..N-1 are still shared by the users hashed to them.

Constraints:
- **Self-host 8GB box** (per memory file `project_8gb_selfhost_memory.md`) — cannot multiply per-tenant mounts at runtime; one tenant per sandbox keeps the cache budget bounded.
- **Sandbox hardening invariants** in `mount.sh` are load-bearing: `META_PASSWORD` env-split (keeps Postgres password out of `/proc/<pid>/cmdline`), `PR_SET_DUMPABLE=0` via `jfs_launcher.py`, sudo-strip on every acquire. None of this can regress.
- **No production users yet** — clean slate, no data migration in scope.

User-confirmed direction (prior conversation):
- Per-tenant Postgres DB isolation is non-negotiable.
- Pair with per-tenant R2 prefix tokens (defense-in-depth).
- Eager async provisioning on signup (sandbox boot gates on `status=ready`).
- Skills stay on a shared "system" volume since they're public content.

## Goals / Non-Goals

**Goals:**
- Per-tenant Postgres metadata DB: a tenant's inodes never sit in the same tables as another tenant's.
- Per-tenant R2 access tokens scoped to `tenants/<user_id>/*`: a leaked token can only read one tenant's encrypted chunks.
- Eager async provisioning on user signup; first sandbox mount is fast.
- Idempotent provision/deprovision flows that survive retries.
- Preserve every existing sandbox-side hardening invariant (sudo strip, `META_PASSWORD` env split, `PR_SET_DUMPABLE=0`).
- Skills mount continues to work read-only, from a shared system volume.

**Non-Goals:**
- Per-tenant encryption keys / per-tenant KMS — shared `JFS_ENCRYPTION_KEY` is sufficient given meta + R2 isolation. Revisit only if compliance triggers it.
- Migration of existing user data — no production users; clean slate.
- Org / workspace / team abstraction above users — tenant = user.
- Multi-region tenant placement, per-tenant R2 bucket (single bucket + prefix scoping is enough).
- Per-tenant cache size tuning in the sandbox.

## Decisions

### 1. Postgres DB-per-tenant, not schema-per-tenant

A new Postgres database `gaia_jfs_<user_id>` per tenant, all on the same Postgres instance.

**Why over schema-per-tenant:** JuiceFS' metadata tables are namespaced by the *volume name* it formats, not by Postgres schema. Schema isolation would still leave one shared "JuiceFS volume" — the boundary would be in JuiceFS' internal naming, not at the database level. DB-per-tenant gives Postgres-native isolation: connection-level credential separation, clean `pg_dump` per tenant, trivial `DROP DATABASE` on deprovision.

**Cost:** N empty databases on one Postgres process is cheap (shared buffers, no per-DB memory floor of consequence). The real cost is connection pooling — each tenant whose user is actively sandboxed needs an open pool.

### 2. Connection pool model — lazy per-tenant `asyncpg` pools, evicted by LRU

When a sandbox is acquired, resolve the tenant's meta URL and open (or reuse) an `asyncpg` pool keyed by `meta_db_name`. Keep an LRU of N (e.g. 64) pools; evict the least-recently-used pool when capacity is reached.

**Why not one big pool:** `asyncpg` pools are bound to a single database — can't reuse across DBs.

**Why not per-request pools:** Pool creation on every request churns connections.

**Why LRU eviction:** Bounds total open connections; idle tenants stop holding sockets.

### 3. Eager async provisioning via ARQ, with `status=ready` gating

User signup enqueues `provision_tenant_volume(user_id)`. The row is inserted with `status=provisioning` synchronously inside the signup transaction so a follow-up sandbox acquire knows the task is in flight.

**Sandbox-acquire behavior:**
- `status=ready` → proceed normally.
- `status=provisioning` → await with bounded timeout (5s); if still not ready, return a friendly "your workspace is still being set up" error.
- `status=failed` → surface error to user; retryable via admin tool.
- `status=deprovisioning|deleted` → reject.

**Why eager-async over lazy:** Fast signup; fast first mount; one place owns the provisioning lifecycle (ARQ retries on failure).

**Why not synchronous in the signup request:** `CREATE DATABASE` + `juicefs format` + R2 token mint is several seconds.

### 4. R2 sub-token mint via Cloudflare R2 API; secrets at-rest via Fernet

Each tenant gets an R2 access token scoped via Cloudflare's R2 admin API to `tenants/<user_id>/*` on the existing bucket. The `(access_key_id, secret_access_key)` pair returned is encrypted with `cryptography.fernet` using a key from `JFS_TENANT_CREDS_KEY` (new setting) and stored in the `tenant_volumes` row.

**Why Fernet:** Symmetric, simple, app-managed key, no external KMS dependency.

**Alternative considered:** Store plaintext, lock Postgres role permissions. Rejected — defense-in-depth on the credentials at rest is cheap and matches the pattern of `META_PASSWORD` env-split (we already treat these as high-value secrets).

**Single bucket + per-tenant prefix vs bucket-per-tenant:** Single bucket. R2 has bucket-creation limits, and prefix-scoped tokens give the same blast-radius reduction without operational pain.

### 5. Drop `--subdir` from the primary mount

The tenant's volume root *is* their workspace. No `--subdir /users/$USER_ID` in `mount.sh`. The credentials themselves are now the isolation boundary.

**Why:** Per-tenant DB+R2-token already isolates at the storage layer. `--subdir` becomes redundant and the `users/{user_id}` path segment becomes meaningless inside a tenant volume.

**Consequence:** `META_PASSWORD` env-split becomes *more* load-bearing. A leak of `/proc/<juicefs_pid>/cmdline` now leaks per-tenant Postgres credentials instead of shared ones. The existing `_split_meta_url` + `jfs_launcher.py` plumbing already handles this; we just have to verify nothing regresses.

### 6. Skills stay on a shared "system" volume

A small JuiceFS volume (`gaia_jfs_system` meta DB + `system/skills/*` R2 prefix) backs the read-only skills mount. Bootstrap once via `scripts/format_system_volume.sh`. The sandbox mount script gets a *second* env block (`SKILLS_JFS_META_URL`, `SKILLS_META_PASSWORD`, `SKILLS_R2_KEY`, `SKILLS_R2_SECRET`) and continues to `--subdir /skills/$USER_ID --read-only` on that volume.

**Why not copy skills into each tenant volume:** Skills can be large; duplicating across N tenants wastes both R2 and metadata. Skills are public content — no tenant data flows into the system volume.

**Why not skip skills mount entirely:** The existing skill install / executor flow depends on `/workspace/skills`. Preserve the contract.

### 7. Delete `shard_router.py` and `JUICEFS_NUM_SHARDS`

Hash-based shard routing was a load-distribution mechanism, not isolation. It is replaced by the per-tenant lookup table. Removing it (rather than keeping it dormant) prevents confused future hands from re-introducing shard semantics on top of tenants.

**Alternative considered:** Keep shard_router for the system volume. Rejected — system volume has one fixed meta URL; a router is overkill.

### 8. Provisioning idempotency via `jfs_setting` probe + ARQ-native retry

`provision_tenant_volume` is idempotent across all steps:
1. Insert `tenant_volumes` row with `ON CONFLICT DO NOTHING`.
2. `CREATE DATABASE IF NOT EXISTS` (Postgres doesn't support `IF NOT EXISTS` directly — use a `DO` block that checks `pg_database`).
3. R2 token mint — check `r2_token_id` column; skip if already minted.
4. `juicefs format` — probe `jfs_setting` table; skip if volume already formatted with the right name.
5. Flip `status=ready` only on the last step's success.

Failures at any step leave the row in `status=provisioning` and ARQ retries with backoff. After max retries, status flips to `failed`.

## Risks / Trade-offs

- **Cloudflare R2 API rate limits during signup bursts** → Use exponential backoff in the ARQ task; cap concurrent provisioning workers via ARQ's `max_jobs` setting.
- **Postgres connection-pool growth on bursty traffic** → LRU-bounded pool cache (decision #2). Monitor `pg_stat_activity` count and alert on connection exhaustion.
- **`juicefs format` is destructive if mis-pointed** → Always probe `jfs_setting` first; never format a database that already has a JuiceFS schema with a different volume name.
- **`META_PASSWORD` env-split must not regress** → Now leaks *per-tenant* creds if broken (worse blast radius than before). Keep the existing `_split_meta_url` invariant under test; ensure no code path concatenates the meta password back into the URL argv.
- **R2 admin token is high-value** (can mint tokens for any prefix) → Treat it like `R2_ACCESS_KEY` was historically: load via Infisical in prod, store only in admin-context env. Never copy into per-request scope.
- **At-rest encryption key (`JFS_TENANT_CREDS_KEY`) rotation** → Out-of-scope for v1. Document that rotation requires a one-time re-encrypt pass over `tenant_volumes`.
- **Deprovision races** (user deleted while a sandbox is active) → Mark `status=deprovisioning` before any destructive step. Sandbox acquire rejects this status. ARQ task deletes R2 prefix → revokes token → drops DB only after status flip succeeds.
- **System volume single point of failure** → If the system volume is unhealthy, skills don't mount; tenants still get a working `/workspace` (skills bind is best-effort already). Keep that fallback behavior.
- **Self-host operators provisioning their first user** → The bootstrap script `format_system_volume.sh` must run before any user signs up. Wire it into the selfhost compose startup explicitly.
- **R2 admin SDK availability** → If no usable Python SDK exists for the R2 admin API, write a thin `httpx`-based wrapper (mint, revoke). Keep it isolated in `app/services/storage/r2_admin.py`.

## Migration Plan

Clean-slate change — no user data to migrate. Deployment sequence:

1. **Pre-deploy in dev:**
   - Land the migration that adds `tenant_volumes` table.
   - Add new settings (`POSTGRES_ADMIN_URL`, `R2_ADMIN_TOKEN`, `JFS_TENANT_CREDS_KEY`, `JFS_SYSTEM_META_URL`, `JFS_SYSTEM_R2_PREFIX`).
   - Run `scripts/format_system_volume.sh` once to bootstrap the system volume.
2. **Deploy:** Ship the code change. From here on, every new signup provisions its own tenant volume.
3. **Verify:** Sign up two test users, confirm `\l` shows two new `gaia_jfs_*` databases, confirm cross-tenant reads fail, confirm sandbox hardening script still passes.
4. **Remove dead code** in the same release: delete `shard_router.py`, remove `JUICEFS_NUM_SHARDS` references, drop the old `gaia_juicefs_0` Postgres DB from selfhost init.

Rollback: revert the deploy. The new `tenant_volumes` table is harmless if unused; new tenant DBs created during the brief deploy window can be manually dropped by an admin script.

## Open Questions

- **Cloudflare R2 sub-token API surface** — confirm the exact endpoint + scope language for prefix-restricted tokens against the current R2 API version before writing `r2_admin.py`.
- **Should `tenant_volumes` live in Postgres or Mongo?** Postgres makes sense (it's relational config-like data adjacent to the meta DBs themselves and avoids reaching into Mongo from infrastructure-level code). Default to Postgres unless the codebase has a strong convention otherwise.
- **Tests:** scope of unit coverage vs integration. Default per project rule: add tests only for the new modules (encrypt/decrypt, provisioning idempotency, resolver-on-provisioning state). Don't expand into a broader pass unless asked.
