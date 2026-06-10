## 1. Settings & Data Model

- [ ] 1.1 Add new settings to `apps/api/app/config/settings.py`: `POSTGRES_ADMIN_URL`, `R2_ADMIN_TOKEN`, `JFS_TENANT_CREDS_KEY`, `JFS_SYSTEM_META_URL`, `JFS_SYSTEM_R2_PREFIX`, `JFS_SYSTEM_R2_KEY`, `JFS_SYSTEM_R2_SECRET`. Production requires all; development makes them optional.
- [ ] 1.2 Remove `JUICEFS_NUM_SHARDS` and `JUICEFS_META_URL_TEMPLATE` from settings. Surface any callers via lint.
- [ ] 1.3 Create `apps/api/app/models/tenant_volume.py` defining the `tenant_volumes` table: columns `user_id (pk)`, `meta_db_name`, `r2_token_id`, `r2_key_encrypted`, `r2_secret_encrypted`, `r2_prefix`, `status` (enum: provisioning/ready/failed/deprovisioning/deleted), `created_at`, `ready_at`, `updated_at`.
- [ ] 1.4 Add the Alembic / migration file that creates `tenant_volumes` and the supporting Postgres role with `CREATEDB`.

## 2. Admin Postgres Access

- [ ] 2.1 Create `apps/api/app/db/postgresql/admin.py`: a privileged `asyncpg` connection helper that uses `POSTGRES_ADMIN_URL` for `CREATE DATABASE` / `DROP DATABASE`. Register as `@lazy_provider("postgres_admin")`.
- [ ] 2.2 Implement `database_exists(db_name)`, `create_database(db_name)`, `drop_database(db_name)` helpers. Use `pg_database` probe for the existence check (no `IF NOT EXISTS` in `CREATE DATABASE`).
- [ ] 2.3 Add a lazy per-tenant `asyncpg` pool cache with LRU eviction (default cap 64) keyed by `meta_db_name`. Expose `get_tenant_pool(db_name)`.

## 3. R2 Admin Wrapper

- [ ] 3.1 Create `apps/api/app/services/storage/r2_admin.py`. Implement `mint_prefix_token(prefix)` and `revoke_token(token_id)` against the Cloudflare R2 admin API using `R2_ADMIN_TOKEN`. Use `httpx` if no first-class SDK is available.
- [ ] 3.2 Implement `delete_prefix_objects(prefix)` (list + bulk delete) for the deprovision path.
- [ ] 3.3 Register `@lazy_provider("r2_admin")`. Wrap retries with exponential backoff.

## 4. Tenant Credential Encryption + Resolver

- [ ] 4.1 Create `apps/api/app/services/storage/tenant_credentials.py`. Implement `encrypt_secret(plaintext)` and `decrypt_secret(ciphertext)` using `cryptography.fernet` with `JFS_TENANT_CREDS_KEY`.
- [ ] 4.2 Implement `async def resolve_tenant_credentials(user_id) -> TenantCreds` returning a typed object containing meta URL (no password), meta password, R2 key, R2 secret, R2 bucket, R2 account, R2 prefix. Use `_split_meta_url` from `lifecycle.py` to split the meta URL.
- [ ] 4.3 Implement `async def resolve_system_credentials() -> SystemCreds` reading from settings (`JFS_SYSTEM_META_URL`, `JFS_SYSTEM_R2_KEY`, `JFS_SYSTEM_R2_SECRET`, bucket, account).
- [ ] 4.4 Raise typed exceptions for `status in {provisioning, failed, deprovisioning, deleted}` and for unknown user.

## 5. Provisioning ARQ Task

- [ ] 5.1 Create `apps/api/app/services/storage/tenant_provisioning.py`. Implement `async def provision_tenant_volume(ctx, user_id)` wrapping the body in `wide_task("provision_tenant_volume", user_id=user_id)`.
- [ ] 5.2 Step 1: insert `tenant_volumes` row with `ON CONFLICT DO NOTHING`. If row already has `status=ready`, return early.
- [ ] 5.3 Step 2: create `gaia_jfs_<user_id>` via `db.postgresql.admin` (probe `pg_database` first).
- [ ] 5.4 Step 3: mint R2 sub-token scoped to `tenants/<user_id>/*` if `r2_token_id` is null; encrypt and persist the returned key/secret.
- [ ] 5.5 Step 4: run `juicefs format` against the new DB + R2 prefix using a subprocess call. Probe `jfs_setting` first; skip format if already populated.
- [ ] 5.6 Step 5: flip `status=ready` and set `ready_at`.
- [ ] 5.7 On unrecoverable failure after max retries, flip `status=failed` and surface the error via wide event.
- [ ] 5.8 Register the task in `apps/api/app/workers/tasks.py`.

## 6. Deprovisioning ARQ Task

- [ ] 6.1 Implement `async def deprovision_tenant_volume(ctx, user_id)`. Wrap in `wide_task`.
- [ ] 6.2 Flip `status=deprovisioning` if not already there. Reject if `status in {provisioning}` (cannot deprovision while provisioning is in flight; wait for it to terminate).
- [ ] 6.3 Step 1: delete all R2 objects under `tenants/<user_id>/*` via `r2_admin.delete_prefix_objects`.
- [ ] 6.4 Step 2: revoke the R2 token via `r2_admin.revoke_token`.
- [ ] 6.5 Step 3: drop `gaia_jfs_<user_id>` via `db.postgresql.admin.drop_database`.
- [ ] 6.6 Step 4: flip `status=deleted`.
- [ ] 6.7 Wire into user-deletion code path.
- [ ] 6.8 Register the task in `apps/api/app/workers/tasks.py`.

## 7. Signup Hook

- [ ] 7.1 Find the user-create service path. Insert the `tenant_volumes` row synchronously inside the signup transaction with `status=provisioning`.
- [ ] 7.2 Enqueue `provision_tenant_volume(user_id)` after the transaction commits.
- [ ] 7.3 Cover failure cases: if enqueue fails, the row remains in `provisioning` and a sweeper/admin tool can retry it.

## 8. Sandbox Lifecycle Rewrite

- [ ] 8.1 Rewrite `apps/api/app/services/sandbox/lifecycle.py::_mount_env` to call `resolve_tenant_credentials(user_id)` + `resolve_system_credentials()` and return a single env dict containing both blocks (tenant under `JFS_*`, system under `SKILLS_*`).
- [ ] 8.2 Update `_create_fresh_sandbox` and any other caller of `_mount_env` to drop the `shard_id` argument (no shard concept anymore).
- [ ] 8.3 Add status gating at the top of the sandbox acquisition path: read `tenant_volumes.status`; if `provisioning`, await with a 5s bounded timeout; if still not ready or in any rejected status, raise `SandboxAcquisitionError` with a user-friendly message.
- [ ] 8.4 Delete `apps/api/app/services/sandbox/shard_router.py` and remove every import of it.
- [ ] 8.5 Update the `e2b_sandboxes` Mongo doc to stop recording `shard_id` (or keep the field nullable for backward read compatibility, then drop in a follow-up).

## 9. Mount Script Update

- [ ] 9.1 Edit `apps/api/scripts/mount_juicefs.sh`. Drop `--subdir "/users/$USER_ID"` from `mount_user_subdir`. The mount is now volume-root.
- [ ] 9.2 Rewrite `mount_skills_subdir` to consume `SKILLS_JFS_META_URL`, `SKILLS_META_PASSWORD`, `SKILLS_R2_KEY`, `SKILLS_R2_SECRET` from env. Keep `--subdir "/skills/$USER_ID" --read-only`.
- [ ] 9.3 Export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` for the tenant mount, then re-export them with the system values immediately before launching the skills mount (juicefs reads them at mount-time only).
- [ ] 9.4 Update header comments to reflect the new isolation model (credentials are the boundary, not `--subdir`).
- [ ] 9.5 Verify hardening invariants survive: re-run `apps/api/scripts/verify_sandbox_hardening.sh` against a freshly mounted sandbox.

## 10. Storage Path Helpers

- [ ] 10.1 Edit `apps/api/app/services/storage/juicefs.py`: `user_workspace_path(user_id)` now resolves to `_mount_root() / "<volume-root>"` — but the host-side mount is per-API-process for the system volume only; tenant volumes are not host-mounted. Document this clearly: per-tenant API-side filesystem helpers are no longer applicable for tenant data.
- [ ] 10.2 Move skills-side helpers (`ensure_user_skills_dir`, `user_skills_path`, `write_skill_file`, `delete_user_skill`) to use the host-mounted system volume root (separate constant from the now-removed tenant `_mount_root`).
- [ ] 10.3 Identify and refactor callers of `ensure_user_workspace`, `write_session_file`, `session_root`, `sandbox_session_path` to write through the sandbox (since the host no longer has the tenant volume mounted). Alternatively: add a host-side per-tenant on-demand mount facility — explicitly decided against in design; route file seeding through the sandbox instead.
- [ ] 10.4 Update `app/services/sandbox/artifact_watcher.py` accordingly — the host-side `.accesslog` watcher applied to the shared tenant volume; replace with a per-sandbox in-sandbox watcher, or scope artifact watching to the system volume only (decision required during implementation).

## 11. System Volume Bootstrap

- [ ] 11.1 Write `apps/api/scripts/format_system_volume.sh`. Idempotent: probe `jfs_setting` in `gaia_jfs_system`, skip format if populated.
- [ ] 11.2 Update `infra/docker/postgres-init/10-juicefs.sql` to create `gaia_jfs_system` instead of `gaia_juicefs_0`, plus a role with `CREATEDB`.
- [ ] 11.3 Wire `format_system_volume.sh` into the dockered startup sequence (compose health-gated init container or one-shot service).
- [ ] 11.4 Update `infra/docker/docker-compose.yml` and `infra/docker/docker-compose.selfhost.yml` to expose the new env vars (`POSTGRES_ADMIN_URL`, `R2_ADMIN_TOKEN`, `JFS_TENANT_CREDS_KEY`, `JFS_SYSTEM_*`) and remove the old shared `JFS_META_URL` + `R2_ACCESS_KEY` / `R2_SECRET_KEY` envs that pointed at the shared user volume.

## 12. Tests

- [ ] 12.1 Unit: `tenant_credentials.encrypt_secret` / `decrypt_secret` round-trip; rejects on wrong key.
- [ ] 12.2 Unit: `resolve_tenant_credentials` returns expected fields for `status=ready`; raises typed exceptions for each non-ready status; raises for unknown user.
- [ ] 12.3 Unit: `provision_tenant_volume` idempotency — call twice in a row, assert each step probes and skips correctly (mock admin DB + R2 admin).
- [ ] 12.4 Unit: `deprovision_tenant_volume` idempotency on partial failure.
- [ ] 12.5 Integration: signup flow inserts a `tenant_volumes` row and enqueues the provision task.
- [ ] 12.6 Integration: sandbox-acquire path with `status=provisioning` awaits the bounded timeout; with `status=failed` raises.
- [ ] 12.7 Skip wholesale test sweeps — per project rule, only add tests for the new modules and integration points.

## 13. Verification & Cleanup

- [ ] 13.1 Run `nx type-check api`.
- [ ] 13.2 Run `nx lint api`.
- [ ] 13.3 Manual end-to-end in `mise dev:vm`: sign up two users, confirm two new `gaia_jfs_*` DBs exist, confirm cross-tenant isolation (user B's `/workspace` shows no user A files), confirm skills mount works for both.
- [ ] 13.4 Run `apps/api/scripts/verify_sandbox_hardening.sh` after rebuild — must pass.
- [ ] 13.5 Delete a user; confirm `gaia_jfs_<user>` is dropped, R2 prefix empty, R2 token revoked.
- [ ] 13.6 Grep for dead references to `shard_router`, `JUICEFS_NUM_SHARDS`, `JUICEFS_META_URL_TEMPLATE`, the old `R2_ACCESS_KEY` shared-key usage, and remove.
- [ ] 13.7 Update `apps/api/CLAUDE.md` "Native vs Dockered API (JuiceFS trade-off)" section if any behavior changed in native mode (most likely unchanged — JFS host mount semantics are the same).
