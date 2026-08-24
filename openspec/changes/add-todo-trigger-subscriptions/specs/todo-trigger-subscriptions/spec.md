## ADDED Requirements

### Requirement: Tracked todos can subscribe to integration triggers
A tracked todo SHALL support zero or more trigger subscriptions, each referencing a supported GAIA-facing trigger name (from the existing `WorkflowTriggerSchema` catalog), a list of declarative conditions, an action (`execute`, `notify`, `complete`, or `unblock`), and a cooldown. A todo MUST NOT be able to subscribe to a trigger whose integration is not connected.

#### Scenario: Agent subscribes a todo to a Gmail trigger
- **WHEN** the agent calls the subscription tool with `trigger_name: gmail_new_message` and conditions on verified payload fields
- **THEN** the subscription is stored on the todo document with its Composio trigger instance IDs and is live

#### Scenario: Subscription to disconnected integration
- **WHEN** a subscription is requested for a trigger whose integration is not connected
- **THEN** registration is rejected with a message naming the required integration

### Requirement: Conditions validate against curated matchable fields
Each trigger SHALL expose a curated matchable-fields catalog: payload fields (name, type, description) verified to arrive reliably. Subscription conditions MUST reference only fields in that catalog, with operators valid for the field's type. Invalid conditions MUST be rejected at subscription time, never silently stored.

#### Scenario: Condition references unknown field
- **WHEN** a condition references a field not in the trigger's matchable-fields catalog
- **THEN** validation fails and the repair flow begins instead of storing the condition

#### Scenario: Operator invalid for field type
- **WHEN** a condition uses an operator that does not apply to the field's type (e.g. `contains` on an integer)
- **THEN** validation fails with a type-specific message

### Requirement: Two-stage repair loop on validation failure
On condition-validation failure, the system SHALL first attempt deterministic repair (fuzzy field-name matching against the catalog, operator correction for the field's type). Only genuinely ambiguous failures SHALL be passed to a single LLM repair pass that rewrites conditions using only catalog fields. The repair loop MUST NOT run when validation passes, MUST NOT exceed one LLM attempt, and MUST NOT weaken the subscription's intent to force a match — if no catalog field can express the intent, registration is rejected and alternative triggers are surfaced.

#### Scenario: Deterministic repair fixes a field-name typo
- **WHEN** a condition references `threadId` and the catalog field is `thread_id`
- **THEN** the condition is repaired mechanically without any LLM call

#### Scenario: Intent not expressible
- **WHEN** the user's intent requires a payload field no supported trigger provides
- **THEN** the subscription is rejected and alternatives are surfaced; no approximating condition is stored

### Requirement: Fired triggers fan out to subscribed todos
When a Composio trigger fires, the dispatch pipeline SHALL evaluate active todo subscriptions for the firing trigger before any no-matching-workflow short-circuit. For each matching todo whose conditions pass and whose cooldown has elapsed, the system SHALL perform the subscription's action, stamped with a distinct `todo_trigger` origin so analytics, budget gating, and rate limiting treat it as trigger-caused work. Actions:
- `execute` — enqueue execution through the existing tracked-todo execution path with the triggering payload in context.
- `notify` — send a notification (reusing the maintenance-sweep deep-link pattern) without executing; no state change.
- `complete` — mark the todo completed (idempotent completion path) and tear down its subscriptions.
- `unblock` — remove the matching blocking label (`waiting-for-reply`, `waiting-for-approval`, or `blocked`); if none of the blocking labels is present, the action degrades to `notify`.

#### Scenario: Reply arrives in watched thread
- **WHEN** a Gmail message arrives whose `thread_id` matches a subscribed waiting-todo's condition under an `execute` action
- **THEN** the todo executes immediately with the triggering payload in its context

#### Scenario: Event matches no workflow but matches a todo
- **WHEN** a fired trigger has no matching workflow but has a matching todo subscription
- **THEN** the subscription's action still runs (the event must not be dropped)

#### Scenario: Cooldown suppresses repeat fires
- **WHEN** a second qualifying event arrives for the same subscription within its cooldown
- **THEN** the action does not run again

#### Scenario: Complete action on matching event
- **WHEN** a qualifying event matches a subscription with action `complete`
- **THEN** the todo is marked completed through the idempotent completion path and its subscriptions are torn down

#### Scenario: Unblock action with no blocking label
- **WHEN** a qualifying event matches a subscription with action `unblock` but the todo carries no blocking label
- **THEN** the user receives a notification instead, and the todo's state is unchanged

### Requirement: Subscriptions share trigger lifecycle with workflows
Subscription teardown SHALL use the same reference-counted Composio trigger deletion as workflows — a Composio trigger instance MUST NOT be deleted while any workflow or todo still references it. Completing, archiving, or failing a todo SHALL tear down its subscriptions. OAuth reconnect resync SHALL re-register active todo subscriptions alongside workflow triggers, and connection-expiry SHALL pause or block affected subscriptions rather than leave them silently dead.

#### Scenario: Workflow deleted but todo shares trigger
- **WHEN** a workflow sharing a Composio trigger instance with a subscribed todo is deleted
- **THEN** the Composio trigger survives because the todo still references it

#### Scenario: Todo completes
- **WHEN** a subscribed tracked todo reaches a terminal state
- **THEN** its subscriptions are unregistered and their refcounts updated

### Requirement: Self-wiring thread subscriptions
When GAIA sends an outbound email or Slack message on behalf of a tracked todo that is still active, it SHALL automatically arm a subscription on that todo: capturing the sent message's thread identifier (Gmail) or channel identifier (Slack) as a subscription condition and adding the appropriate blocking label. Sends not made on behalf of a tracked todo MUST NOT arm subscriptions. Auto-armed subscriptions go through the same validation path as explicit ones.

#### Scenario: Todo sends follow-up email
- **WHEN** a tracked todo's execution sends an email via Gmail
- **THEN** the todo gains a subscription matching replies to that exact thread and a `waiting-for-reply` label, requiring no manual configuration

#### Scenario: Regular chat email send
- **WHEN** GAIA sends an email during ordinary conversation with no originating tracked todo
- **THEN** no subscription is armed

## ADDED Requirements

### Requirement: Matchable-fields catalog per trigger
The system SHALL maintain, per supported trigger, a curated list of matchable payload fields derived from the verified Composio payload schemas (`app/models/composio_schemas/`). Each entry SHALL carry the field name, type, description, and example value. The catalog SHALL cover at minimum gmail, slack, calendar, github, linear, notion, sheets, todoist, and asana triggers.

#### Scenario: Catalog reflects verified payloads
- **WHEN** a trigger's payload schema lists a field absent from the matchable catalog
- **THEN** the catalog documents why it was excluded (unreliable delivery or unsuitable for matching)

### Requirement: Subscription tool returns the schema the model will get
The agent-facing subscription tool SHALL return (and/or embed in its schema) the full matchable-fields catalog for the selected trigger — field names, types, descriptions, examples — so the model constructs conditions from known data rather than guessing. The tool description SHALL remain semantically rich enough for ChromaDB retrieval.

#### Scenario: Model requests available fields
- **WHEN** the agent asks what a trigger will deliver before subscribing
- **THEN** it receives the complete typed matchable-fields catalog for that trigger
