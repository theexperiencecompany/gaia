## ADDED Requirements

### Requirement: The sandbox mount script SHALL mount the tenant volume at the user's workspace root

The mount script (`/etc/gaia/mount.sh`) SHALL mount the tenant's JuiceFS volume at `/mnt/jfs` and bind it at `/workspace`. The primary mount SHALL NOT use `--subdir` — the tenant volume's root is the user's workspace root, and the storage-layer credentials are the isolation boundary.

#### Scenario: Primary mount has no --subdir

- **WHEN** the mount script invokes `juicefs mount` for the tenant volume
- **THEN** the command line MUST NOT contain `--subdir`
- **AND** the volume root SHALL be bind-mounted at `/workspace`

#### Scenario: Tenant volume root contains the user's workspace tree

- **WHEN** a sandbox is acquired and the tenant mount succeeds
- **THEN** files written by the agent at `/workspace/<path>` land at `/<path>` inside the tenant volume
- **AND** a different user's sandbox sees an empty volume root because their tenant volume is a different Postgres DB + R2 prefix

### Requirement: The sandbox mount script SHALL mount the shared system volume read-only for skills

The mount script SHALL additionally mount the shared system volume at `/mnt/jfs-skills` with `--subdir /skills/<user_id>` and `--read-only`, then bind-mount it at `/workspace/skills` (also read-only).

#### Scenario: Skills mount uses the system volume credentials

- **WHEN** the mount script runs
- **THEN** the skills `juicefs mount` invocation uses `SKILLS_JFS_META_URL` and `SKILLS_META_PASSWORD` from the per-call env block
- **AND** uses `SKILLS_R2_KEY` / `SKILLS_R2_SECRET` (forwarded as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` for that mount only)
- **AND** the mount is `--subdir /skills/<USER_ID> --read-only`

#### Scenario: Skills mount failure falls back gracefully

- **WHEN** the system volume is unreachable
- **THEN** the skills bind is skipped
- **AND** the primary `/workspace` mount still succeeds
- **AND** the script exits 0 (skills are best-effort)

### Requirement: Mount-time env SHALL carry two distinct credential blocks

The API SHALL build the env passed to `mount.sh` from two sources: the tenant credential resolver (for the primary volume) and the system credential resolver (for skills). The blocks SHALL be passed as separate, prefixed env variables to avoid ambiguity.

#### Scenario: Env block contains both credential sets

- **WHEN** the API calls `_mount_env(user_id)`
- **THEN** the returned env contains `USER_ID`, `JFS_META_URL`, `META_PASSWORD`, `JFS_R2_KEY`, `JFS_R2_SECRET`, `JFS_R2_BUCKET`, `JFS_R2_ACCOUNT` for the tenant volume
- **AND** contains `SKILLS_JFS_META_URL`, `SKILLS_META_PASSWORD`, `SKILLS_R2_KEY`, `SKILLS_R2_SECRET`, `SKILLS_R2_BUCKET`, `SKILLS_R2_ACCOUNT` for the system volume

### Requirement: Existing sandbox hardening invariants SHALL be preserved

The mount script's existing security plumbing — `META_PASSWORD` env-split, `PR_SET_DUMPABLE=0` via `jfs_launcher.py`, removal of the sandbox user from `sudo` / `wheel` groups, purge of `sudoers.d` drop-ins and inline NOPASSWD rules on every acquire — SHALL remain in place unchanged. These invariants apply equally to both the tenant and system mount.

#### Scenario: Tenant juicefs daemon is non-dumpable

- **WHEN** the tenant `juicefs mount` succeeds
- **THEN** the daemon's `/proc/<pid>/environ` and `/proc/<pid>/cmdline` are unreadable to the unprivileged sandbox user
- **AND** `apps/api/scripts/verify_sandbox_hardening.sh` passes after the change

#### Scenario: System juicefs daemon is also non-dumpable

- **WHEN** the system `juicefs mount` succeeds
- **THEN** the same hardening applies to its daemon process

#### Scenario: Meta passwords stay out of cmdline

- **WHEN** either juicefs daemon is running
- **THEN** `cat /proc/<juicefs_pid>/cmdline` from the unprivileged sandbox user does not reveal any Postgres password (tenant or system)
