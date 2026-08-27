## ADDED Requirements

### Requirement: Connection-lifecycle events are accepted

`POST /webhook/composio` SHALL accept Composio connection-lifecycle events in addition to trigger messages. Envelope parsing SHALL NOT require trigger identifiers to be present, because connection events carry none.

#### Scenario: Connection expired event is accepted

- **WHEN** a signed request arrives with `type: "composio.connected_account.expired"` and a `data` object holding `id`, `user_id`, `status`, `toolkit.slug` and `auth_config.id`
- **THEN** the endpoint returns 200
- **AND** the event is routed to the connection-lifecycle handler

#### Scenario: Trigger events keep working

- **WHEN** a signed request arrives with a trigger event carrying `data.trigger_nano_id`
- **THEN** it is routed to the trigger handler resolved from its event type, exactly as before

#### Scenario: Unknown event types are acknowledged

- **WHEN** a signed request arrives with an event type no handler is registered for
- **THEN** the endpoint returns 200 without raising

### Requirement: Webhook processing safety properties are preserved

Connection-lifecycle events SHALL be subject to the same protections as trigger events: HMAC signature verification before any parsing of the body, replay dedupe keyed on the `webhook-id` header, and a bounded background task so the endpoint answers immediately.

#### Scenario: Unsigned request is rejected

- **WHEN** a connection event arrives with a missing or invalid `webhook-signature` header
- **THEN** the endpoint returns 401
- **AND** no connection state is changed

#### Scenario: Redelivery is ignored

- **WHEN** Composio redelivers an event whose `webhook-id` was already processed
- **THEN** the endpoint returns 200 and the event is not processed a second time

#### Scenario: Endpoint responds before processing completes

- **WHEN** a valid connection event is accepted
- **THEN** the endpoint returns 200 immediately
- **AND** the state transition runs in a background task subject to the existing timeout

### Requirement: Connection events resolve to a GAIA user and integration

The handler SHALL map an incoming connection event onto a GAIA user and platform integration before acting, and SHALL act only when the reported status is one Composio treats as unusable.

#### Scenario: Integration resolved from auth config

- **WHEN** a connection event carries `data.auth_config.id` matching a configured integration
- **THEN** that integration is selected via the existing auth-config lookup

#### Scenario: Unrecognized integration is ignored

- **WHEN** a connection event's auth config and toolkit slug match no configured integration
- **THEN** the event is logged and dropped without changing any state

#### Scenario: Only dead statuses cause expiry

- **WHEN** a connection event reports `data.status` of `EXPIRED`, `REVOKED`, `FAILED` or `INACTIVE`
- **THEN** the expiry transition runs for the resolved user and integration
- **AND** an event reporting `ACTIVE`, `INITIALIZING` or `INITIATED` causes no expiry transition
