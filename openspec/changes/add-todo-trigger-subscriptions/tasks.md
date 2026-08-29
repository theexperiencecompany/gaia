## 1. Matchable-fields catalog

- [x] 1.1 Create `app/services/triggers/matchable_fields.py`: per-trigger curated field catalog (name, type, description, example) derived from verified `composio_schemas` payload models; exclusion reasons documented for omitted fields
- [x] 1.2 Unit test: catalog covers every trigger name published by the `WorkflowTriggerSchema` catalog (23 today — gmail ×2, calendar ×2, google_docs ×3, google_sheets ×2, github ×4, linear ×3, notion ×3, slack ×2, todoist, asana), asserting against the live catalog rather than a hardcoded list so a new trigger fails the test; every catalog field exists on the corresponding payload model with matching type

## 2. Subscription data model + validation

- [x] 2.1 Add `TriggerSubscription` model and `trigger_subscriptions` field to `TodoDocument` **and `TodoUpdate`** (which is `extra="forbid"`, so writes fail without it), and read-only on `TodoResponse` so the mirrored TS type is not a field the API never sends; mirror the type in `libs/shared/ts/src/types/todo.ts`
- [x] 2.2 Add condition model (`field`, `op`, `value`) with operator enum per field type; record on the subscription whether it resolves by trigger instance ID or by user + trigger name
- [x] 2.3 Repository finders on `todo_repository`: `find_active_by_composio_trigger(trigger_id)` and `find_active_by_user_and_trigger(user_id, trigger_name)` — both cross-user, following the existing `*_all_users` convention for unscoped reads
- [x] 2.4 Add todos indexes in `app/db/mongodb/indexes.py` mirroring `workflows_collection.create_index("trigger_config.composio_trigger_ids", sparse=True)`: one on the subscription trigger-id array, one on `(user_id, subscription trigger_name)`, both sparse
- [x] 2.5 Implement validator: fields must be in matchable catalog, operators valid for type; mechanical repair (fuzzy field-name match, operator correction); rejection errors name alternatives
- [x] 2.6 Unit tests: valid conditions pass; unknown field / bad operator fail; `threadId→thread_id` repairs mechanically with no LLM call; both index-backed finders return only active subscriptions

## 3. Registration lifecycle

- [x] 3.1 Rename the `workflow_id` parameter to a neutral owner ref across `TriggerHandler.register`, `TriggerService.register_triggers` / `unregister_triggers`, and every implementation and call site — no adapter layer
- [x] 3.2 Register subscriptions through the existing handler `register()` path; store returned Composio trigger instance IDs. An empty return from an account-level trigger (Gmail) is success — assert it is not treated as a registration failure
- [x] 3.3 Add `todo_repository.count_trigger_references(composio_trigger_id, *, excluding_todo_id=None)`; sum workflow + todo counts inside `TriggerService.get_triggers_safe_to_delete` so neither repository reads the other's collection
- [x] 3.4 Teardown on every terminal path: completion, archival, failure, **and deletion** — `TodoService.delete_todo`, `bulk_delete_todos`, `delete_all_for_user`. Unregister before the document is removed so nothing is orphaned
- [x] 3.5 Include active todo subscriptions in OAuth reconnect resync (`resync_user_workflow_triggers`)
- [x] 3.6 Connection-expiry pause: mark affected subscriptions paused and add the `blocked` label to their todos; resume and clear the label on reconnect (`services/workflow/integration_pause.py`)
- [x] 3.7 Tests: the refcount cases live in `tests/unit/services/workflow/test_trigger_service_refcount.py` (service-level sum) backed by real-Mongo counting in `tests/contracts/test_todos_repository.py`; delete-orders-teardown-first in `test_todo_service.py`; expiry/reconnect in `test_integration_pause.py`

## 4. Dispatch fan-out

- [x] 4.1 Tap `TriggerHandler.process_event` before the no-workflow early return (`base.py:373`), enqueueing `dispatch_todo_subscriptions` rather than calling it — dispatch needs the todo completion path, which imports the trigger stack back (a real cycle mypy passes clean). Resolve subscribed todos by **both** strategies — trigger instance ID, and `(user_id, trigger_name)` for account-level triggers
- [x] 4.2 Condition evaluation in the spawned task against typed payload models; AND-chain semantics; cooldown check via Redis key, written only when the action actually runs
- [x] 4.3 Add `TriggerType.TODO_TRIGGER` and `TriggerType.SCHEDULED_TODO`; replace the hardcoded `"scheduled_todo"` literals in `_run_execution` and `_execute_via_agent`
- [x] 4.4 Thread the origin + triggering payload as a new optional parameter through `execute_tracked_todo` → `_execute_todo_with_retry` → `_run_execution` → `_execute_via_agent`, **including the retry re-enqueue sites** (`tracked_todo_tasks.py:155`, `:192`) so a retried trigger run keeps its origin
- [x] 4.5 On a held execution lock, re-enqueue the `execute` action on a bounded backoff (1m/3m/10m) instead of returning `skipped`, then give up loudly. One short defer was the plan and is not enough — the lock TTL is 30 minutes, so it would routinely land on the same held lock
- [x] 4.6 Add `enforce_daily_cost_budget` to the triggered todo execution path with its own `feature_key` in `app/config/rate_limits.py` (the gate does not exist on this path today)
- [x] 4.7 Move `BLOCKING_LABELS` from `maintenance_sweep_tasks.py:54` to `app/constants/todos.py`, and `_todo_redirect_action` (`:427`) to a shared notification helper, before the dispatch path imports either
- [x] 4.8 Implement the remaining actions per spec: `notify` (deep-link notification, no state change), `complete` (idempotent completion + teardown), `unblock` (remove blocking label; degrade to notify when none present)
- [ ] 4.9 Optional LLM relevance tier: small silent call comparing payload vs canvas Key Details, cooldown-gated, behind a feature flag
- [x] 4.10 Unit tests (integration deferred to the live drive in 7.4): thread-match executes todo; account-level Gmail event with no trigger id still resolves subscribers; no-workflow event still fires todo; cooldown suppresses repeat; held lock defers rather than drops; retry preserves the `todo_trigger` origin; each of the four actions behaves per spec; budget gate blocks

## 5. Agent tool surface

- [ ] 5.1 Add `subscribe_todo_to_trigger` (and unsubscribe/list variants) in `tracked_todo_tools.py`; the call returns the trigger's matchable-fields catalog
- [ ] 5.2 Register the new tools in `initial_tool_ids` (`build_graph.py:106`) alongside the other tracked-todo tools, and update the tool lists in `comms_prompts.py:377` and `todo_prompts.py`
- [ ] 5.3 Single LLM repair pass wired into the tool failure path: ambiguous validation failures rewritten once against catalog fields, then accepted or rejected loudly
- [ ] 5.4 E2E test: agent creates tracked todo, subscribes to `gmail_new_message` with a typo'd field, repair loop fixes it, subscription registers

## 6. Post-send subscription prompt

- [ ] 6.1 Add an `AgentMiddleware.awrap_tool_call` middleware to `create_middleware_stack` (the seam `MediaDescriptionMiddleware` uses) that reads `active_todo_id` from `request.runtime.config["configurable"]` and, on success, appends a subscribe instruction to the `ToolMessage`. It performs no writes and calls no services. Composio's `after_execute` hooks are synchronous and context-free and cannot be used
- [ ] 6.2 **Verify first**: whether Gmail sends run in a provider subagent whose tool set excludes the subscription tool. If so, decide between granting subagents the tool or carrying the identifier back to the executor on the subagent result — the instruction must reach an agent that can act on it
- [ ] 6.3 Wire the watched tool set: `GMAIL_SEND_EMAIL`, draft-send and reply tools, and `GOOGLECALENDAR_CREATE_EVENT`; extract the returned `thread_id` / `event_id` for the instruction text. Keep the list as a named constant, not inline strings
- [ ] 6.4 Same for Slack outbound: instruct a channel-level subscription (documented limitation: no `thread_ts` upstream)
- [ ] 6.5 Tests: instruction appended only when `active_todo_id` is set and the call succeeded; absent on failure and on unbound runs; a subscription created from the instruction passes the ordinary validator; teardown when the todo completes

## 6a. Calendar reminders

- [ ] 6a.1 Add `calendar_event_starting_soon` matchable fields (`event_id`, `attendees`, `organizer_email`, `location`, `start_time`, `minutes_until_start`) to the catalog from `GoogleCalendarEventStartingSoonPayload`
- [ ] 6a.2 Expose the reminder window as registration config on the subscription, passed through to `CalendarEventStartingSoonConfig.minutes_before_start` (1–1440); one subscription per window
- [ ] 6a.3 Tests: an hour-before subscription registers a trigger carrying that window and fires on the matching `event_id`; two windows for one event store two subscriptions; two todos sharing a window share one Composio trigger instance and survive one of them completing

## 7. Observability + frontend

- [ ] 7.1 Analytics: server-side `todos:trigger_fired` (+ registration/failure events) with explicit `capture_event(user_id)` — the `todos:` prefix matches the existing todo events in `AnalyticsEvents`, which the webhook path must pass explicitly since it has no request context
- [ ] 7.2 Notification source for the `notify` action; deep-link redirect via the shared helper extracted in 4.7
- [ ] 7.3 Web picker for trigger + conditions in the todo UI reusing the trigger config schema catalog; shared TS API client updates
- [ ] 7.4 Run `nx type-check api`, `nx lint api`, web/desktop type-check + lint; drive the full loop manually against the live stack (driving-gaia): create todo → send email → verify execution + Mongo state
