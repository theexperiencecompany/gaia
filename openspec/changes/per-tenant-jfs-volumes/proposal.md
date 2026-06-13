## Why

JuiceFS currently runs as a single shared volume: one Postgres metadata DB and one R2 bucket+key shared across every user, with tenant isolation enforced only at sandbox mount time via `--subdir /users/$USER_ID`. Every user's inodes sit in the same Postgres tables and every user's encrypted chunks sit behind the same R2 credentials — a single app-level bug, leaked admin connection string, or compromised R2 key cross-reads all tenants. Postgres-level isolation per tenant is now required, and we'll pair it with per-tenant R2 prefix tokens for defense-in-depth. No production users exist yet, so this is a clean-slate change with no data migration.

## What Changes

- **BREAKING**: Each user gets their own JuiceFS volume — own Postgres DB (`gaia_jfs_<user_id>`) + own R2 prefix token. The shared single-volume model is removed.
- **BREAKING**: Sandbox primary mount drops `--subdir` — the user's volume root *is* their workspace. Isolation guarantee shifts from a kernel-visible scoped view to the credentials themselves.
- **BREAKING**: `JUICEFS_NUM_SHARDS` and `JUICEFS_META_URL_TEMPLATE` settings + the hash-based shard router are removed. Tenant → volume routing becomes a database lookup against a new `tenant_volumes` table.
- New ARQ task `provision_tenant_volume(user_id)` enqueued on user signup: creates the Postgres DB, mints an R2 sub-token scoped to `tenants/<user_id>/*`, runs `juicefs format`, stores credentials encrypted-at-rest, flips status to `ready`.
- New deprovision flow on user deletion: drop DB, revoke R2 token, delete the R2 prefix.
- New small shared "system" JuiceFS volume backs the read-only `/workspace/skills` mount (skills are public content, not tenant data). One-time bootstrap script formats it.
- Sandbox mount script consumes two distinct credential sets per invocation: tenant volume creds + system volume creds.
- New admin-level secrets: `POSTGRES_ADMIN_URL` (for `CREATE DATABASE`), `R2_ADMIN_TOKEN` (for sub-token mint), `JFS_TENANT_CREDS_KEY` (Fernet key for at-rest encryption of stored per-tenant R2 secrets).

## Capabilities

### New Capabilities
- `tenant-volume-provisioning`: Lifecycle (provision, deprovision, idempotent re-runs) of per-tenant JuiceFS volumes including the Postgres metadata DB, the scoped R2 sub-token, and the `juicefs format` step.
- `tenant-credential-resolver`: Lookup + encrypt/decrypt of per-tenant JuiceFS credentials at sandbox mount time, with the `META_PASSWORD` env-split security model intact.
- `tenant-sandbox-mount`: Sandbox-side mount flow that consumes tenant + system credential blocks and mounts the tenant volume at `/workspace` (no `--subdir`) plus the system volume's `/skills/<user_id>` subtree at `/workspace/skills` (read-only).

### Modified Capabilities
<!-- None — fs-metrics-prometheus is unrelated; this change creates new capabilities rather than altering existing spec'd requirements. -->

## Impact

- **Code**: `apps/api/app/services/sandbox/lifecycle.py` (`_mount_env` rewrite), `apps/api/app/services/sandbox/shard_router.py` (deleted), `apps/api/scripts/mount_juicefs.sh` (drop `--subdir`, accept second credential block), `apps/api/app/services/storage/juicefs.py` (path helpers drop `users/{user_id}` segment). New modules: `app/services/storage/tenant_provisioning.py`, `tenant_credentials.py`, `r2_admin.py`, `app/db/postgresql/admin.py`, `app/models/tenant_volume.py`. New ARQ task registration.
- **Infrastructure**: `infra/docker/postgres-init/10-juicefs.sql` switches from static `gaia_juicefs_0` to a `gaia_jfs_system` create + a Postgres role with `CREATEDB`. Compose files updated to expose `POSTGRES_ADMIN_URL`, `JFS_SYSTEM_META_URL`, and R2 admin/system env vars instead of the shared `JFS_META_URL` + `R2_ACCESS_KEY`/`R2_SECRET_KEY`. New `apps/api/scripts/format_system_volume.sh` one-time bootstrap.
- **Dependencies**: `cryptography` (Fernet, may already be present) for at-rest secret encryption; Cloudflare R2 admin SDK (or thin `httpx` wrapper) for token mint/revoke.
- **External systems**: Cloudflare R2 API rate limits during user-creation bursts. Postgres connection pool grows with active tenants (lazy-open, per-DB pools).
- **Sandbox / E2B template**: No template rebuild required — `jfs_launcher.py`, sudo-strip, and `PR_SET_DUMPABLE=0` plumbing stay unchanged. Only `mount.sh` content changes.
- **Self-host (8GB constraint)**: No memory cost increase — still one mount per active sandbox; Postgres holds N empty tenant DBs cheaply.
- **Out of scope**: per-tenant encryption keys / KMS, migration of existing data (no prod users), org/workspace abstraction above users, multi-region tenant placement.
