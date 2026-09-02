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
- [ ] 4.9 **Not built, deliberately.** The deterministic tiers cover every case the spec asks for; this adds a per-event LLM call, a feature flag and a cost path for fuzzy matching nobody has needed yet. Speculative flexibility is the debt the engineering rules call out by name. Build it when a real subscription cannot be expressed as a condition chain
- [x] 4.10 Unit tests (integration deferred to the live drive in 7.4): thread-match executes todo; account-level Gmail event with no trigger id still resolves subscribers; no-workflow event still fires todo; cooldown suppresses repeat; held lock defers rather than drops; retry preserves the `todo_trigger` origin; each of the four actions behaves per spec; budget gate blocks

## 5. Agent tool surface

- [x] 5.1 Add `subscribe_todo_to_trigger` (and unsubscribe/list variants) in `tracked_todo_tools.py`; the call returns the trigger's matchable-fields catalog
- [x] 5.2 Register the new tools in `initial_tool_ids` (`build_graph.py:106`) alongside the other tracked-todo tools, and update the tool lists in `comms_prompts.py:377` and `todo_prompts.py`
- [x] 5.3 Rejections carry the trigger's catalog so the calling agent corrects and retries — no nested LLM pass inside the tool. A second in-tool model call would repair with less context than the agent loop already has, cost extra, and hide the rewrite from the transcript, which is the silent-intent-drift this section exists to prevent
- [x] 5.4 E2E test through the compiled graph: agent creates a tracked todo, subscribes with a typo'd field, the repair path resolves it, subscription registers
- [x] 5.5 **Built, then removed at the user's request for simplicity.** A `list_available_triggers` tool listed the matchable catalog intersected with the user's *connected* integrations. It worked and was tested, but discovery already exists: `list_trigger_fields` called with a wrong name returns every subscribable trigger, and its description now says so. The disconnected-integration guard it also gave is not lost — `register_subscription` still rejects a subscription to an unconnected integration loudly, with the catalog attached, so the only cost is one wasted turn versus a pre-filtered list. Reverted the tool, its `build_graph.py`/prompt registration, and its tests; kept the wrong-name hint in the `list_trigger_fields` description
- [x] 5.6 Add a `match` mode (`all` default / `any`) to the subscription, threaded model → tool → `register_subscription` → `conditions_match`, so one subscription can express a flat OR ("from acme.com OR northwind.com") without splitting into several. Deliberately flat: nested boolean is an OR-of-ANDs, which is several `all` subscriptions on one todo — an expression language on the per-event hot path is the speculative-flexibility debt the rules name. Unit-tested that `any` diverges from `all`, ignores a retired field the same way, and that empty conditions still fire on every event

## 6. Post-send subscription prompt — REMOVED

- [x] 6.1-6.5 **Built, then removed at the user's request for simplicity.** The
  `awrap_tool_call` middleware appended a "consider watching this" instruction to
  successful Gmail/Calendar sends in todo-bound runs. It worked and was tested, but it
  cost a middleware seam, a tier flag threaded through `create_middleware_stack`, and a
  two-hop handoff via `finish_task` (Gmail sends run in a provider subagent that does not
  hold `subscribe_todo_to_trigger`) — the most fragile and least verifiable part of the
  design. Deleted: `app/agents/middleware/subscription_prompt.py`, its stack registration,
  the `can_subscribe_todos` flag, and `tests/unit/agents/middleware/test_subscription_prompt.py`.
  The model now subscribes on its own judgement, prompted only by `todo_prompts.py`.

## 6a. Calendar reminders

- [x] 6a.1 Add `calendar_event_starting_soon` matchable fields (`event_id`, `attendees`, `organizer_email`, `location`, `start_time`, `minutes_until_start`) to the catalog from `GoogleCalendarEventStartingSoonPayload`
- [x] 6a.2 Expose the reminder window as registration config on the subscription, passed through to `CalendarEventStartingSoonConfig.minutes_before_start` (1–1440); one subscription per window. Out-of-range values come back as a readable `SubscriptionError`, not a raw pydantic traceback the agent cannot correct from
- [x] 6a.3 Tests: an hour-before subscription registers a trigger carrying that window and fires on the matching `event_id`; two windows for one event store two subscriptions; two todos sharing a window share one Composio trigger instance and survive one of them completing

## 7. Observability + frontend

- [x] 7.1 Analytics: server-side `todos:trigger_fired` (+ registration/failure events) with explicit `capture_event(user_id)` — the `todos:` prefix matches the existing todo events in `AnalyticsEvents`, which the webhook path must pass explicitly since it has no request context
- [x] 7.2 Notification source for the `notify` action; deep-link redirect via the shared helper extracted in 4.7
- [ ] 7.3 **Not built — needs your call.** design.md left this as an open question ("ship with phase 1 or follow once API-proven?") and it is still open. The data already reaches the client (`trigger_subscriptions` is on `TodoResponse` and the shared `Todo` type), so a read-only "Watching..." surface is small; an interactive picker needs new subscription endpoints, client methods, and a component I cannot visually verify without a browser drive. Say which and I will build it
- [x] 7.4 Gates run. Live drive done against real Mongo/Redis + a booted API and worker: real signed Composio webhook -> handler -> dispatch handed off before the no-workflow return -> worker resolved the subscriber by (user, trigger_name) -> conditions matched -> `fired:1` -> `execute_tracked_todo` received the `TriggerOrigin` intact. It found a bug no test had: `_apply_update`'s `exclude_unset=True` recursed into the nested subscription and dropped `status`, so every subscription written by registration was unfindable. Agent execution then failed with `ValueError: No human message or selected tool` — traced to a real product bug (the todo request filled `message` but left `messages` empty, and content is read from `messages[-1]`), so EVERY agent-path tracked todo had been failing. Fixed with a red-first integration test. Re-driven to completion. Routing the LLM through GAIA's supported dev override (`DEV_DEFAULT_MODEL=custom` + `DEV_LLM_BASE_URL=https://opencode.ai/zen/v1`, env only, no code change) onto a free tool-capable model, the full chain ran green: `success` in 571s over 61 `llm_call`s, the todo `completed: True`, its subscription torn down to 0, and the completion summary quoting the webhook payload -- proving the triggering event reached the model's prompt, which is the gap the review found
- [x] 7.5 **Model-driven drive — the half the scripted drive could not prove.** 7.4 created the subscription with a direct service call, so it verified dispatch, not the model's judgement. Re-driven with a real free model (`nemotron-3.5-lightning-free` via the same dev override) and a natural request ("I emailed Northwind chasing invoice 7788 on thread ..., keep on top of it and follow up when they reply") that never names a tool. Unprompted — the post-send middleware is gone — the model searched context, called `list_trigger_fields`, created the tracked todo, then called `subscribe_todo_to_trigger` on its own with a correct three-condition watch (`thread_id equals ... AND sender contains northwind AND subject contains "invoice 7788"`). It persisted whole (id/status/created_at present, `resolution: account`). A signed webhook matching all three then drove `dispatch_todo_subscriptions -> fired:1 -> execute_tracked_todo(<todo>, TriggerOrigin(subscription_id=...))`. This is the end-to-end proof that the tool is one the model actually reaches for, not just one that works when called.
