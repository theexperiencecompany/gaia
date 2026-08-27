## ADDED Requirements

### Requirement: Expired connection state

The system SHALL represent a previously-established integration connection that no longer works as `expired`, distinct from both `connected` and the absence of a record. `user_integrations.status` SHALL accept `created`, `connected` and `expired`. `get_all_integrations_status()` SHALL report an `expired` integration as not connected.

#### Scenario: Expired integration reports as not connected

- **WHEN** `user_integrations` holds `{status: "expired"}` for an integration
- **THEN** `get_all_integrations_status()` returns `False` for that integration id
- **AND** `check_integration_status()` returns `False`

#### Scenario: Expiry is distinguishable from never-connected in the catalog

- **WHEN** the client fetches `/integrations/me` for a user whose Gmail record is `expired`
- **THEN** the `MyIntegrationItem` for Gmail carries `status: "expired"`
- **AND** an integration the user has never connected carries `status: "not_connected"`

#### Scenario: Expiry never fabricates a record

- **WHEN** an expiry transition is attempted for a user/integration pair with no `user_integrations` document
- **THEN** no document is created
- **AND** the transition is a no-op

### Requirement: Expiry transition side effects

When an integration is transitioned to `expired`, the system SHALL perform every step needed for the rest of GAIA to stop treating the account as usable: persist the status, invalidate the integration status / user tools / tool-namespace caches, drop the cached `connected_account_id` held in the Composio proxy client's in-process map, and resync the user's workspace integrations file.

#### Scenario: Caches are invalidated on expiry

- **WHEN** an integration is transitioned to `expired`
- **THEN** the `USER_INTEGRATION_CACHE_PATTERNS` keys for that user are deleted
- **AND** a subsequent `get_all_integrations_status()` call recomputes from Mongo rather than serving the cached `connected` result

#### Scenario: Proxy connected-account cache is dropped

- **WHEN** an integration backed by toolkit `GMAIL` is transitioned to `expired`
- **THEN** `invalidate_connected_account_cache(user_id, toolkit="GMAIL")` is called
- **AND** the next proxy call re-resolves the connected account against Composio instead of reusing the revoked id

#### Scenario: Transition is idempotent

- **WHEN** the same expiry transition runs twice for one user/integration pair
- **THEN** the second run leaves the status at `expired` and performs no further user-visible effects

### Requirement: Expiry is surfaced to the user

The system SHALL tell the user that a connection died rather than failing silently. On transition to `expired` it SHALL broadcast an integration status update over the user's WebSocket channel and raise exactly one in-app notification carrying a Reconnect action that deep-links to the integration.

#### Scenario: Open integrations page updates live

- **WHEN** an integration expires while the user has the integrations page open
- **THEN** a WebSocket message identifying the integration and its new `expired` status is broadcast to that user
- **AND** the page shows the integration as needing reconnection without a manual refresh

#### Scenario: Notification is raised once per expiry

- **WHEN** an integration transitions from `connected` to `expired`
- **THEN** one in-app notification is created with a Reconnect action pointing at the integration
- **AND** a repeat expiry signal for an already-`expired` integration creates no additional notification

#### Scenario: Reconnect clears the expired state

- **WHEN** the user completes OAuth again for an `expired` integration
- **THEN** `user_integrations.status` becomes `connected`
- **AND** the integration's workflow triggers are re-registered against the new connected account

### Requirement: Dead-account tool failures reconcile instead of being swallowed

When a Composio tool execution fails because the connected account is missing, expired or revoked, the system SHALL identify that specific failure, run the expiry transition, and hand the agent a connect instruction instead of an opaque error. All other execution failures SHALL propagate unchanged.

#### Scenario: Dead-account error triggers the expiry path

- **WHEN** `execute_tool` raises Composio error `1810` / `ActionExecute_ConnectedAccountNotFound`
- **THEN** the integration is transitioned to `expired`
- **AND** an `integration_connection_required` event carrying the integration id and message is streamed to the client
- **AND** the tool returns the text produced by `build_integration_connection_message()` for that integration

#### Scenario: Unrelated failures are not masked

- **WHEN** `execute_tool` raises a timeout, a 5xx, a rate-limit error, or any exception that is not the dead-account error
- **THEN** no expiry transition occurs
- **AND** the exception propagates rather than being converted into `{"successful": false, ...}`

#### Scenario: Chat renders the existing connect card

- **WHEN** a dead-account failure occurs during a UI-sourced chat turn
- **THEN** the streamed `integration_connection_required` event renders the existing connect prompt component
- **AND** the agent's reply asks the user to press connect and contains no URL

#### Scenario: Text-only surfaces receive a link

- **WHEN** a dead-account failure occurs on a bot or background surface
- **THEN** the returned message carries the single-use connect link, or points at the integrations page when no link could be minted
