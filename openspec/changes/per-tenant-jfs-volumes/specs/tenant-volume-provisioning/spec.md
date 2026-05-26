## ADDED Requirements

### Requirement: Each user SHALL own exactly one JuiceFS volume

The system SHALL provision one dedicated JuiceFS volume per user, comprising a private Postgres metadata database (`gaia_jfs_<user_id>`) and a Cloudflare R2 access token scoped to the prefix `tenants/<user_id>/*` on the shared bucket. A `tenant_volumes` row SHALL track the user's volume state, holding the meta DB name, encrypted R2 credentials, R2 prefix, R2 token identifier, and lifecycle status.

#### Scenario: User signup provisions a tenant volume

- **WHEN** a user account is created
- **THEN** the system inserts a `tenant_volumes` row with `status=provisioning` synchronously during the signup transaction
- **AND** enqueues an asynchronous `provision_tenant_volume(user_id)` task

#### Scenario: Provisioning task creates all per-tenant resources

- **WHEN** `provision_tenant_volume(user_id)` runs
- **THEN** it creates Postgres database `gaia_jfs_<user_id>` if it does not already exist
- **AND** mints a Cloudflare R2 access token scoped to `tenants/<user_id>/*` if no token has already been minted for this row
- **AND** runs `juicefs format` against the new database and R2 prefix if the database does not already contain a JuiceFS volume
- **AND** persists the R2 credentials encrypted at rest using a Fernet key from `JFS_TENANT_CREDS_KEY`
- **AND** flips the row to `status=ready` only after every step succeeds

### Requirement: Provisioning SHALL be idempotent on retry

The provisioning task SHALL safely retry any partial failure without creating duplicate resources or corrupting an in-progress volume. Each step SHALL probe for existing state before acting.

#### Scenario: Retry after Postgres CREATE DATABASE succeeded but R2 token mint failed

- **WHEN** the provisioning task runs a second time for the same user
- **THEN** it detects that `gaia_jfs_<user_id>` already exists in `pg_database` and skips creation
- **AND** detects that no R2 token has been recorded for the row and proceeds to mint
- **AND** continues to `juicefs format` and status flip

#### Scenario: Retry after juicefs format completed

- **WHEN** the provisioning task runs a second time
- **AND** the tenant database already contains a populated `jfs_setting` table
- **THEN** the task skips the `juicefs format` step
- **AND** proceeds directly to the status flip

### Requirement: Sandbox acquisition SHALL gate on provisioning state

The sandbox lifecycle SHALL consult the tenant's `status` before proceeding. A user whose volume is not yet `ready` SHALL not be granted an active sandbox mount.

#### Scenario: Sandbox acquired while provisioning still in flight

- **WHEN** a user attempts to acquire a sandbox
- **AND** their `tenant_volumes` row has `status=provisioning`
- **THEN** the lifecycle awaits the provisioning task with a bounded timeout of at most 5 seconds
- **AND** if the row reaches `status=ready` within the timeout, the sandbox is acquired normally
- **AND** if it does not, the lifecycle returns a user-visible error indicating the workspace is still being set up

#### Scenario: Sandbox acquired after provisioning failed

- **WHEN** a user attempts to acquire a sandbox
- **AND** their `tenant_volumes` row has `status=failed`
- **THEN** the lifecycle raises an error
- **AND** the system MUST NOT attempt to mount

#### Scenario: Sandbox acquired during deprovisioning

- **WHEN** a user attempts to acquire a sandbox
- **AND** their `tenant_volumes` row has `status=deprovisioning` or `deleted`
- **THEN** the lifecycle rejects the acquisition

### Requirement: User deletion SHALL deprovision the tenant volume

The system SHALL provide a deprovisioning flow that revokes the tenant's R2 token, deletes all objects under the tenant's R2 prefix, and drops the tenant's Postgres metadata database. The flow SHALL be sequenced so that R2 access is removed before metadata is destroyed.

#### Scenario: User account is deleted

- **WHEN** a user account is deleted
- **THEN** the system flips the `tenant_volumes` row to `status=deprovisioning`
- **AND** enqueues `deprovision_tenant_volume(user_id)`
- **AND** the task deletes all R2 objects under `tenants/<user_id>/*`
- **AND** revokes the R2 token
- **AND** drops the Postgres database `gaia_jfs_<user_id>`
- **AND** flips the row to `status=deleted`

#### Scenario: Deprovision retried after partial failure

- **WHEN** the deprovision task runs a second time after a partial failure
- **THEN** each step is safe to repeat (deleting an already-empty prefix, revoking an already-revoked token, dropping a non-existent database) without raising

### Requirement: A separate shared "system" JuiceFS volume SHALL host skills

The system SHALL maintain one shared JuiceFS volume — Postgres database `gaia_jfs_system` plus R2 prefix `system/skills/*` — that is read-only for sandboxes and holds installed skills under `/skills/<user_id>/` subtrees. No tenant data SHALL be written to the system volume.

#### Scenario: One-time system volume bootstrap

- **WHEN** the operator runs `scripts/format_system_volume.sh` on a fresh deployment
- **THEN** the script creates `gaia_jfs_system` if missing
- **AND** runs `juicefs format` against the system R2 prefix if the volume is not already formatted
- **AND** exits 0 if invoked again (idempotent)
