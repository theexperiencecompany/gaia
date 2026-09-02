## Why

Tracked todos are entirely time-driven: ARQ schedules and cron sweeps poll for overdue/dormant states, but a todo waiting on an external event ("did Acme reply to my invoice email?") has no reactive capability. Meanwhile Composio triggers fire rich integration events (Gmail, Slack, Linear, ...) into workflows only — the two systems are isolated. Letting a tracked todo subscribe to a trigger with declarative conditions turns todos from passive reminders into self-executing agents of their own completion.

## What Changes

- Add optional `trigger_subscriptions` to the tracked-todo document: each subscription references a supported integration trigger (from the existing `WorkflowTriggerSchema` catalog), carries declarative conditions on the (now verified) trigger payload fields, an action (`execute` | `notify` | `complete` | `unblock`), and a cooldown.
- Fan out fired Composio triggers to subscribed todos inside the existing dispatch pipeline (`TriggerHandler.process_event`) — including events that match no workflow (today they short-circuit and drop). Subscriptions resolve by Composio trigger instance ID *and* by user + trigger name, because account-level triggers like Gmail register no per-subscriber instance IDs at all.
- Curated **matchable-fields** layer per trigger: the subset of payload fields verified to arrive reliably, which is what conditions validate against and what the LLM is shown at subscription time ("it knows, not guesses").
- Condition validation with a two-stage repair loop on failure: deterministic fixes first (field-name fuzzy match, operator-for-type), then a single LLM repair pass; if the trigger genuinely cannot express the intent, reject loudly with alternative triggers surfaced. The repair loop never runs when validation already passes, and never waters down intent to force a match.
- Registration lifecycle tied to todo lifecycle: subscriptions register via existing handler `register()` paths with reference-counted teardown shared with workflows; completing, archiving, failing **or deleting** a todo tears down its subscriptions; OAuth reconnect resync and connection-expiry pause include todo subscriptions.
- Calendar reminders fall out of the same machinery: `calendar_event_starting_soon` already takes a `minutes_before_start` window, so "remind me an hour before the Acme call" is a subscription narrowed to that event's `event_id`.
- Execution path reuses `execute_tracked_todo` (lock, backoff, retry, canvas logging), carrying a `todo_trigger` origin as an explicit task parameter that survives retries, and adding the daily cost-budget gate this path does not have today. An event arriving while the todo's lock is held is deferred, not dropped.

## Capabilities

### New Capabilities
- `todo-trigger-subscriptions`: tracked todos subscribing to integration triggers with declarative payload conditions, validated registration, fan-out dispatch, and lifecycle-tied teardown
- `trigger-matchable-fields`: curated per-trigger field catalog derived from the verified Composio payload schemas — the source for condition validation, LLM-facing schema exposure, and the repair loop

### Modified Capabilities

## Impact

- `apps/api/app/models/todo_models.py` — `TodoDocument` and `TodoUpdate` (`extra="forbid"`) — plus the shared TS type in `libs/shared/ts/src/types/todo.ts`
- `apps/api/app/services/triggers/base.py` (`process_event` fan-out before the no-workflow early return), `registry.py`
- New service module under `apps/api/app/services/triggers/` for subscription matching/validation; new repository finders in `app/db/repositories/todos.py`, plus new sparse indexes in `app/db/mongodb/indexes.py` (both dispatch lookups are cross-user and run per webhook event)
- Trigger teardown refcounting: a new `todo_repository.count_trigger_references` summed with the workflow count inside `TriggerService.get_triggers_safe_to_delete`
- Todo deletion paths (`TodoService.delete_todo`, `bulk_delete_todos`, `delete_all_for_user`) must unregister before removing the document
- `resync_user_workflow_triggers` in `app/services/workflow/trigger_service.py`; connection-expiry pause in `app/services/workflow/integration_pause.py`
- `apps/api/app/workers/tasks/tracked_todo_tasks.py` — origin parameter threaded through four signatures and both retry re-enqueue sites; `TriggerType` gains `TODO_TRIGGER` / `SCHEDULED_TODO` in `workflow_models.py`; new budget `feature_key` in `app/config/rate_limits.py`
- `BLOCKING_LABELS` and `_todo_redirect_action` move out of `app/workers/tasks/maintenance_sweep_tasks.py` into `app/constants/todos.py` and a shared notification helper
- `TriggerHandler.register` / `TriggerService.register_triggers` — the `workflow_id` parameter is renamed to a neutral owner ref across handlers and call sites
- Agent tool surface (`subscribe_todo_to_trigger`) added to `initial_tool_ids` and the prompts that enumerate tracked-todo tools; web frontend picker reusing the trigger config schema catalog
- Analytics: new server-side `todos:trigger_fired` event (explicit `capture_event(user_id)` — the webhook path has no request context); possible `NotificationSourceEnum` addition
