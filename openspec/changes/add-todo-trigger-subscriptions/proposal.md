## Why

Tracked todos are entirely time-driven: ARQ schedules and cron sweeps poll for overdue/dormant states, but a todo waiting on an external event ("did Acme reply to my invoice email?") has no reactive capability. Meanwhile Composio triggers fire rich integration events (Gmail, Slack, Linear, ...) into workflows only — the two systems are isolated. Letting a tracked todo subscribe to a trigger with declarative conditions turns todos from passive reminders into self-executing agents of their own completion.

## What Changes

- Add optional `trigger_subscriptions` to the tracked-todo document: each subscription references a supported integration trigger (from the existing `WorkflowTriggerSchema` catalog), carries declarative conditions on the (now verified) trigger payload fields, an action (`execute` | `notify` | `complete` | `unblock`), and a cooldown.
- Fan out fired Composio triggers to subscribed todos inside the existing dispatch pipeline (`TriggerHandler.process_event`) — including events that match no workflow (today they short-circuit and drop).
- Curated **matchable-fields** layer per trigger: the subset of payload fields verified to arrive reliably, which is what conditions validate against and what the LLM is shown at subscription time ("it knows, not guesses").
- Condition validation with a two-stage repair loop on failure: deterministic fixes first (field-name fuzzy match, operator-for-type), then a single LLM repair pass; if the trigger genuinely cannot express the intent, reject loudly with alternative triggers surfaced. The repair loop never runs when validation already passes, and never waters down intent to force a match.
- Registration lifecycle tied to todo lifecycle: subscriptions register via existing handler `register()` paths with reference-counted teardown shared with workflows; completing/archiving/failing a todo tears down its subscriptions; OAuth reconnect resync and connection-expiry pause include todo subscriptions.
- Self-wiring flow: when GAIA sends an email/Slack message on behalf of a tracked todo, it captures the sent `thread_id`/channel onto the todo as a subscription condition and adds the appropriate blocking label — the todo watches its own aftermath without user configuration.
- Execution path reuses `execute_tracked_todo` (lock, backoff, retry, canvas logging) with a stamped `todo_trigger` trigger context, gated by the same daily cost budget as triggered workflows.

## Capabilities

### New Capabilities
- `todo-trigger-subscriptions`: tracked todos subscribing to integration triggers with declarative payload conditions, validated registration, fan-out dispatch, and lifecycle-tied teardown
- `trigger-matchable-fields`: curated per-trigger field catalog derived from the verified Composio payload schemas — the source for condition validation, LLM-facing schema exposure, and the repair loop

### Modified Capabilities

## Impact

- `apps/api/app/models/todo_models.py` (+ shared TS type in `libs/shared/ts/src/types/todo.ts`)
- `apps/api/app/services/triggers/base.py` (`process_event` fan-out before the no-workflow early return), `registry.py`
- New service module under `apps/api/app/services/triggers/` for subscription matching/validation; new repository finders in `app/db/repositories/todos.py`
- Trigger teardown refcounting (`workflow_repository.count_trigger_references`, `get_triggers_safe_to_delete`) must count todo references too
- `resync_user_workflow_triggers` / connection-expiry pause paths in `oauth_service.py` / `integration_pause.py`
- Agent tool surface (`subscribe_todo_to_trigger`), web frontend picker reusing the trigger config schema catalog
- Analytics: new server-side `todo:trigger_fired` event (explicit `capture_event(user_id)`); possible `NotificationSourceEnum` addition
