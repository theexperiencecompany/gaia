## ADDED Requirements

### Requirement: The system SHALL resolve per-tenant JuiceFS credentials by user ID

The system SHALL expose a single resolver entry point that, given a user ID, returns the credentials needed to mount that user's JuiceFS volume: the Postgres metadata URL (without password), the password, the R2 access key, the R2 secret, the R2 bucket, the R2 account, and the R2 prefix. The resolver SHALL read these from the `tenant_volumes` row, decrypting the R2 secret material at call time using the Fernet key from `JFS_TENANT_CREDS_KEY`.

#### Scenario: Resolver returns tenant credentials for a ready user

- **WHEN** the resolver is called with a user ID whose row has `status=ready`
- **THEN** it returns a credentials object containing the tenant's meta URL, decrypted R2 key/secret, R2 bucket, R2 account, and R2 prefix

#### Scenario: Resolver rejects a non-ready user

- **WHEN** the resolver is called with a user ID whose row is `provisioning`, `failed`, `deprovisioning`, or `deleted`
- **THEN** it raises an exception identifying the status

#### Scenario: Resolver rejects an unknown user

- **WHEN** the resolver is called with a user ID that has no `tenant_volumes` row
- **THEN** it raises an exception

### Requirement: The system SHALL resolve shared "system" volume credentials

The system SHALL provide a separate resolver for the shared system volume's credentials, which are read from settings (`JFS_SYSTEM_META_URL` and system R2 access vars) rather than from `tenant_volumes`. These credentials drive the read-only skills mount inside every sandbox.

#### Scenario: System credentials returned for skills mount

- **WHEN** any sandbox is being mounted
- **THEN** the system resolver returns the shared system volume's meta URL, meta password, R2 key, R2 secret, R2 bucket, and R2 account
- **AND** these are passed alongside the tenant credentials to the sandbox mount script

### Requirement: Resolved credentials MUST NOT leak via process memory or argv

The resolver SHALL preserve the existing `META_PASSWORD` env-split contract: the Postgres password is never spliced back into the meta URL argv that the long-running `juicefs` daemon's `/proc/<pid>/cmdline` exposes. Decrypted R2 secrets SHALL be held only for the lifetime of one mount-script invocation and SHALL NOT be cached on the API process beyond that scope.

#### Scenario: Meta URL passed to mount.sh has no password

- **WHEN** the resolver hands credentials to `_mount_env`
- **THEN** `JFS_META_URL` contains no userinfo password
- **AND** `META_PASSWORD` carries the password as a separate env value
- **AND** the existing `_split_meta_url` helper is used to perform the split

#### Scenario: Decrypted R2 secrets are not cached

- **WHEN** a sandbox mount completes
- **THEN** the decrypted R2 key and R2 secret are no longer held in memory by the resolver
- **AND** any subsequent mount triggers a fresh decrypt

### Requirement: The system SHALL encrypt R2 credentials at rest

R2 credentials minted during provisioning SHALL be stored in `tenant_volumes` using Fernet symmetric encryption with the key in `JFS_TENANT_CREDS_KEY`. Plaintext credentials SHALL NOT be written to Postgres at any point.

#### Scenario: Newly minted R2 credentials are encrypted before storage

- **WHEN** the provisioning task mints a new R2 token
- **THEN** it encrypts both the access key and the secret access key with the Fernet key
- **AND** writes only the ciphertext into the `tenant_volumes` row

#### Scenario: Encryption key missing at startup

- **WHEN** the API starts with `JFS_TENANT_CREDS_KEY` unset in a non-development environment
- **THEN** startup fails fast with a configuration error
