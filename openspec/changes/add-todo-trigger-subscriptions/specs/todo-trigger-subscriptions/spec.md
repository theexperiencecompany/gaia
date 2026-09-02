## ADDED Requirements

### Requirement: Tracked todos can subscribe to integration triggers
A tracked todo SHALL support zero or more trigger subscriptions, each referencing a supported GAIA-facing trigger name (from the existing `WorkflowTriggerSchema` catalog), a list of declarative conditions, an action (`execute`, `notify`, `complete`, or `unblock`), and a cooldown. A todo MUST NOT be able to subscribe to a trigger whose integration is not connected.

Registration SHALL record how the subscription is resolved at dispatch time: by Composio trigger instance ID for per-resource triggers, or by user and trigger name for account-level triggers. An account-level registration that returns no Composio trigger IDs is a success, and MUST NOT be treated as a registration failure.

#### Scenario: Agent subscribes a todo to a Gmail trigger
- **WHEN** the agent calls the subscription tool with `trigger_name: gmail_new_message` and conditions on verified payload fields
- **THEN** the subscription is stored on the todo document, marked account-level with no Composio trigger IDs, and is live

#### Scenario: Agent subscribes a todo to a per-resource trigger
- **WHEN** the agent subscribes a todo to a trigger that registers per resource (e.g. `slack_new_message` on a channel)
- **THEN** the subscription is stored with the Composio trigger instance IDs returned by registration and is live

#### Scenario: Subscription to disconnected integration
- **WHEN** a subscription is requested for a trigger whose integration is not connected
- **THEN** registration is rejected with a message naming the required integration

### Requirement: Conditions validate against curated matchable fields
Each trigger SHALL expose a curated matchable-fields catalog: payload fields (name, type, description) verified to arrive reliably. Subscription conditions MUST reference only fields in that catalog, with operators valid for the field's type. Invalid conditions MUST be rejected at subscription time, never silently stored.

A subscription SHALL declare how its conditions combine: `all` (every condition must hold, the default) or `any` (one is enough). There is no nested grouping — an OR of several AND-groups is expressed as several `all` subscriptions on the same todo, which covers every boolean shape these payloads need without an expression language on the per-event hot path.

#### Scenario: Any-match fires on one satisfied condition
- **WHEN** a subscription with `match: any` and two sender conditions receives an event matching only the second
- **THEN** the subscription fires, where the same conditions under `match: all` would not

#### Scenario: Condition references unknown field
- **WHEN** a condition references a field not in the trigger's matchable-fields catalog
- **THEN** validation fails and the repair flow begins instead of storing the condition

#### Scenario: Operator invalid for field type
- **WHEN** a condition uses an operator that does not apply to the field's type (e.g. `contains` on an integer)
- **THEN** validation fails with a type-specific message

### Requirement: Two-stage repair loop on validation failure
On condition-validation failure, the system SHALL first attempt deterministic repair (fuzzy field-name matching against the catalog, operator correction for the field's type). Repairs SHALL be reported back to the caller rather than applied silently.

Genuinely ambiguous failures SHALL be rejected with the trigger's matchable fields attached, so the calling agent can correct them and retry — the correction happens in the agent loop, visibly in the transcript, not in a nested LLM call inside the tool. The repair path MUST NOT run when validation passes, and MUST NOT weaken the subscription's intent to force a match — if no catalog field can express the intent, registration is rejected and alternative triggers are surfaced.

#### Scenario: Deterministic repair fixes a field-name typo
- **WHEN** a condition references `threadId` and the catalog field is `thread_id`
- **THEN** the condition is repaired mechanically without any LLM call, and the repair is reported back rather than applied silently

#### Scenario: Ambiguous failure is handed back with the catalog
- **WHEN** a condition names a field no mechanical repair can resolve
- **THEN** registration is refused and the response carries the trigger's matchable fields, so the retry is written against real data rather than a second guess

#### Scenario: Intent not expressible
- **WHEN** the user's intent requires a payload field no supported trigger provides
- **THEN** the subscription is rejected and alternatives are surfaced; no approximating condition is stored

### Requirement: Fired triggers resolve subscriptions by both matching strategies
When a Composio trigger fires, the dispatch pipeline SHALL resolve candidate subscriptions using the same two strategies the workflow lookup uses: by Composio trigger instance ID for per-resource triggers, and by user and trigger name for account-level triggers that carry no instance IDs. Resolution MUST NOT depend on trigger instance IDs alone. Both lookups SHALL be served by an index on the todos collection.

#### Scenario: Account-level Gmail event resolves its subscribers
- **WHEN** a `GMAIL_NEW_GMAIL_MESSAGE` webhook arrives carrying a user id and no per-todo trigger instance id
- **THEN** the user's active `gmail_new_message` subscriptions are resolved and their conditions evaluated against the payload

#### Scenario: Per-resource event resolves its subscribers
- **WHEN** a webhook arrives carrying a Composio trigger instance id
- **THEN** subscriptions storing that instance id are resolved, regardless of whether the payload carries a user id

### Requirement: Fired triggers fan out to subscribed todos
For each matching todo whose conditions pass and whose cooldown has elapsed, the system SHALL perform the subscription's action, stamped with a distinct `todo_trigger` origin so analytics, budget gating, and rate limiting treat it as trigger-caused work. Evaluation SHALL run before any no-matching-workflow short-circuit. Actions:
- `execute` — enqueue execution through the existing tracked-todo execution path, with the triggering payload rendered into the run's prompt so the model can act on what actually happened.
- `notify` — send a notification (reusing the shared todo deep-link redirect helper) without executing; no state change.
- `complete` — mark the todo completed (idempotent completion path) and tear down its subscriptions.
- `unblock` — remove the matching blocking label (`waiting-for-reply`, `waiting-for-approval`, or `blocked`); if none of the blocking labels is present, the action degrades to `notify`.

The `todo_trigger` origin SHALL be carried as an explicit execution parameter, not inferred, and SHALL survive the execution path's retry re-enqueue.

#### Scenario: Reply arrives in watched thread
- **WHEN** a Gmail message arrives whose `thread_id` matches a subscribed waiting-todo's condition under an `execute` action
- **THEN** the todo executes immediately with the triggering payload in its context, stamped `todo_trigger`

#### Scenario: Event matches no workflow but matches a todo
- **WHEN** a fired trigger has no matching workflow but has a matching todo subscription
- **THEN** the subscription's action still runs (the event must not be dropped)

#### Scenario: Triggered execution is retried after failure
- **WHEN** a `todo_trigger` execution fails and is re-enqueued by the retry backoff
- **THEN** the retry still carries the `todo_trigger` origin and its triggering payload, not a scheduled-run origin

#### Scenario: Cooldown suppresses repeat fires
- **WHEN** a second qualifying event arrives for the same subscription within its cooldown
- **THEN** the action does not run again

#### Scenario: Complete action on matching event
- **WHEN** a qualifying event matches a subscription with action `complete`
- **THEN** the todo is marked completed through the idempotent completion path and its subscriptions are torn down

#### Scenario: Unblock action with no blocking label
- **WHEN** a qualifying event matches a subscription with action `unblock` but the todo carries no blocking label
- **THEN** the user receives a notification instead, and the todo's state is unchanged

#### Scenario: Daily cost budget exhausted
- **WHEN** a qualifying event would enqueue an `execute` action for a user whose daily cost budget is spent
- **THEN** the execution is skipped cleanly by the budget gate before any execution record or LLM work

### Requirement: A busy todo defers its triggered execution rather than dropping it
The tracked-todo execution path takes a per-todo lock and abandons the run when it is already held. For a `todo_trigger` execution the event MUST NOT be discarded on a held lock: the system SHALL re-enqueue the action on a bounded backoff, and SHALL give up with an error-level log once that bound is reached rather than retrying forever or failing silently. The subscription's cooldown SHALL be recorded only when the action actually runs, so a deferred event is not suppressed as a repeat fire.

#### Scenario: Event arrives while the todo is mid-execution
- **WHEN** a qualifying event matches a todo whose execution lock is currently held
- **THEN** the action is re-enqueued after a delay and eventually runs, rather than being dropped

#### Scenario: The lock is still held after every deferral
- **WHEN** a deferred action exhausts its backoff and the lock is still held
- **THEN** it is dropped with an error-level log naming the todo and subscription, not silently

#### Scenario: A scheduled run finds the lock held
- **WHEN** an ordinary scheduled execution finds the lock held
- **THEN** it is skipped without deferral, because the next scan picks it up

### Requirement: Subscriptions share trigger lifecycle with workflows
Subscription teardown SHALL use reference-counted Composio trigger deletion covering both consumers — a Composio trigger instance MUST NOT be deleted while any workflow or todo still references it. The count SHALL be summed across the workflow and todo repositories without either repository reading the other's collection.

Every path that ends a todo's life SHALL tear down its subscriptions: completion, archival, failure, and deletion (single and bulk). OAuth reconnect resync SHALL re-register active todo subscriptions alongside workflow triggers.

#### Scenario: Workflow deleted but todo shares trigger
- **WHEN** a workflow sharing a Composio trigger instance with a subscribed todo is deleted
- **THEN** the Composio trigger survives because the todo still references it

#### Scenario: Todo deleted but workflow shares trigger
- **WHEN** a subscribed todo sharing a Composio trigger instance with an active workflow is deleted
- **THEN** the Composio trigger survives because the workflow still references it

#### Scenario: Todo completes
- **WHEN** a subscribed tracked todo reaches a terminal state
- **THEN** its subscriptions are unregistered and their refcounts updated

#### Scenario: Todo is deleted outright
- **WHEN** a subscribed tracked todo is deleted rather than completed
- **THEN** its subscriptions are unregistered before the document is removed, so no Composio trigger is orphaned

### Requirement: Expired integrations pause subscriptions visibly
When a connection an active subscription depends on expires, the system SHALL mark that subscription paused and add the `blocked` label to its todo, rather than leaving the subscription silently dead. Reconnecting the integration SHALL resume the paused subscriptions and clear the label.

#### Scenario: Integration expires under an active subscription
- **WHEN** the Gmail connection behind an active todo subscription expires
- **THEN** the subscription is marked paused and its todo carries the `blocked` label

#### Scenario: Integration reconnected
- **WHEN** the user reconnects that integration
- **THEN** the paused subscriptions are re-registered and the `blocked` label is cleared

### Requirement: Calendar reminder subscriptions
A tracked todo SHALL be able to subscribe to `calendar_event_starting_soon` with a reminder window and a condition narrowing to a specific event. Because the window is registration config rather than a payload field, each distinct window SHALL be its own registration, and a todo wanting several reminders for one event SHALL hold one subscription per window.

#### Scenario: Remind an hour before a specific event
- **WHEN** a todo subscribes to `calendar_event_starting_soon` with a 60-minute window and a condition on the event's `event_id`
- **THEN** the subscription registers a trigger carrying that window, and fires its action once the event is an hour away

#### Scenario: Two windows for the same event
- **WHEN** a todo wants both a one-hour and a ten-minute reminder for one event
- **THEN** two subscriptions are stored, each registering its own window

#### Scenario: Two todos share a reminder window
- **WHEN** a second todo subscribes with the same window on the same calendar
- **THEN** both reference the same Composio trigger instance, and completing one todo leaves the trigger alive for the other
