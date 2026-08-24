## 1. Matchable-fields catalog

- [ ] 1.1 Create `app/services/triggers/matchable_fields.py`: per-trigger curated field catalog (name, type, description, example) derived from verified `composio_schemas` payload models; exclusion reasons documented for omitted fields
- [ ] 1.2 Unit test: catalog covers gmail, slack, calendar, github, linear, notion, sheets, todoist, asana; every catalog field exists on the corresponding payload model with matching type

## 2. Subscription data model + validation

- [ ] 2.1 Add `TriggerSubscription` model and `trigger_subscriptions` field to `TodoDocument`; mirror type in `libs/shared/ts/src/types/todo.ts`
- [ ] 2.2 Add condition model (`field`, `op`, `value`) with operator enum per field type; repository finders `find_active_by_trigger(trigger_id)` / `find_active_by_user_and_trigger`
- [ ] 2.3 Implement validator: fields must be in matchable catalog, operators valid for type; mechanical repair (fuzzy field-name match, operator correction); rejection errors name alternatives
- [ ] 2.4 Unit tests: valid conditions pass; unknown field / bad operator fail; `threadId→thread_id` repairs mechanically with no LLM call

## 3. Registration lifecycle

- [ ] 3.1 Register subscriptions via existing handler `register()` path; store returned Composio trigger instance IDs on the subscription
- [ ] 3.2 Extend trigger refcounting: `count_trigger_references` / `get_triggers_safe_to_delete` count todo references alongside workflows, with an `excluding_todo_id` exclusion (mirroring `excluding_workflow_id`) so a todo being deleted does not count its own subscription — or teardown MUST delete the todo's subscriptions before counting
- [ ] 3.3 Teardown on terminal states: completing/archiving/failing a todo unregisters its subscriptions
- [ ] 3.4 Include active todo subscriptions in OAuth reconnect resync and connection-expiry pause (paused → `blocked` label decision documented)
- [ ] 3.5 Contract/integration tests: workflow-delete-while-todo-subscribed keeps Composio trigger; todo-delete releases it

## 4. Dispatch fan-out

- [ ] 4.1 Tap `TriggerHandler.process_event` before the no-workflow early return; resolve subscribed todos by trigger instance ID
- [ ] 4.2 Condition evaluation in spawned task against typed payload models; AND-chain semantics; cooldown check via Redis key
- [ ] 4.3 Enqueue execution through `execute_tracked_todo` stamped `todo_trigger` origin; route through daily cost-budget gate
- [ ] 4.4 Implement the remaining actions per spec: `notify` (deep-link notification, no state change), `complete` (idempotent completion + teardown), `unblock` (remove blocking label; degrade to notify when none present)
- [ ] 4.5 Optional LLM relevance tier: small silent call comparing payload vs canvas Key Details, cooldown-gated, behind a feature flag
- [ ] 4.6 Unit + integration tests: thread-match executes todo; no-workflow event still fires todo; cooldown suppresses repeat; each of the four actions behaves per spec; budget gate blocks

## 5. Agent tool surface

- [ ] 5.1 Add `subscribe_todo_to_trigger` tool (and unsubscribe/list variants) in `tracked_todo_tools.py`; result returns the trigger's matchable-fields catalog; description rich for ChromaDB retrieval
- [ ] 5.2 Single LLM repair pass wired into tool failure path: ambiguous validation failures rewritten once against catalog fields, then accepted or rejected loudly
- [ ] 5.3 E2E test: agent creates tracked todo, subscribes to gmail_new_message with a typo'd field, repair loop fixes it, subscription registers

## 6. Self-wiring flow

- [ ] 6.1 On outbound Gmail send from a todo execution: capture sent `thread_id`, auto-arm reply-matching subscription, add `waiting-for-reply`
- [ ] 6.2 Same for Slack outbound: arm channel-level subscription (documented limitation: no `thread_ts` upstream)
- [ ] 6.3 Tests: auto-armed subscription passes the same validator; teardown when the todo completes

## 7. Observability + frontend

- [ ] 7.1 Analytics: server-side `todo:trigger_fired` (+ registration/failure events) with explicit `capture_event(user_id)`; add names to `AnalyticsEvents`
- [ ] 7.2 Notification source for `notify` action; deep-link redirect reusing maintenance-sweep pattern
- [ ] 7.3 Web picker for trigger + conditions in todo UI reusing trigger config schema catalog; shared TS API client updates
- [ ] 7.4 Run `nx type-check api`, `nx lint api`, web/desktop type-check + lint; drive the full loop manually against the live stack (driving-gaia): create todo → send email → verify execution + Mongo state
