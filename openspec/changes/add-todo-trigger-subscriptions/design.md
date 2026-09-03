## Context

Tracked todos (`app/services/tracked_todo_service.py`, `app/workers/tasks/tracked_todo_tasks.py`) are durable Mongo documents executed on ARQ schedules; all reactivity is poll-based (30-min safety net, hourly maintenance sweep). Composio triggers (`app/services/triggers/`) fire integration events through `TriggerHandler.process_event` → workflow queueing; events matching no workflow are dropped at `base.py:373`. The only todo contact today is prompt text: `get_signal_matching_context` injects active todos into triggered runs (`base.py:425`).

The 23 GAIA-facing trigger names in `oauth_config.py` (22 distinct Composio slugs — `GMAIL_NEW_GMAIL_MESSAGE` backs both `gmail_new_message` and `gmail_poll_inbox`) had their payload schemas verified against Composio's live API in PR #1096 — including the discovery that Slack's receive-message payload has no thread identifier (`SlackReceiveMessagePayload`) while Gmail carries `thread_id` (`GmailNewMessagePayload`). That verified field set is the foundation for condition matching.

## Goals / Non-Goals

**Goals:**
- Tracked todos react to external events via declarative, validated conditions on trigger payloads
- Full lifecycle symmetry with workflows: registration, refcounted teardown, reconnect resync, expiry pause
- Common case: a todo that sent an email watches the reply thread, because the model subscribed it
- The LLM constructs subscriptions from known schemas, never guesses

**Non-Goals:**
- Arbitrary code/bash expression matching (no sandbox per event)
- Slack thread-level matching (upstream payload lacks `thread_ts`; channel-level only)
- Migrating existing broken Notion all-events / Asana workflows
- A generic internal event bus

## Decisions

### Dispatch: hand off from inside `TriggerHandler.process_event`, before the no-workflow return
The tap goes in the existing choke point — no handler overrides `process_event`, so the base method is the single point, and the early return at "no matching workflows" (`base.py:373-381`) would drop todo-only events, so the hand-off happens before it.

The fan-out itself runs in an ARQ task rather than inline, for a reason found during implementation and not visible on the page: dispatch needs the todo completion path for its `complete` action, and that lifecycle service imports the trigger stack back to tear subscriptions down. Calling it from `base.py` closes a real import cycle — one mypy passes clean straight through, and only a runtime import probe catches. Enqueuing cuts it, because a task name is a string.

It also keeps the webhook path fast (a Mongo scan across every subscriber cannot delay workflow queueing) and gives the fan-out its own wide-event boundary.

*Alternative*: endpoint-level second `spawn_logged_task` — still rejected. This task is enqueued from inside `process_event`, after handler normalization, carrying the trigger names that handler owns; the rejected shape sat before any of that.

### Subscription resolution mirrors `find_workflows`' two strategies — not trigger IDs alone
Gmail is account-level: `GmailTriggerHandler.register()` returns `[]` (`handlers/gmail.py:59`) and `find_workflows` matches by `data["user_id"]` (`handlers/gmail.py:93-98`); `resync_user_workflow_triggers` documents the same property ("Account-level triggers return no ids — nothing to repoint"). A subscription keyed solely on a Composio trigger instance ID therefore **never fires for Gmail** — which is the entire self-wiring case.

Resolution runs both strategies per event, exactly as the Gmail handler does:
1. **By trigger instance ID** — for per-resource triggers (calendar, slack, linear, notion, github, sheets, docs, todoist, asana, `gmail_poll_inbox`), matching subscriptions whose stored `composio_trigger_ids` contain the webhook's `trigger_id`.
2. **By `(user_id, trigger_name)`** — for account-level triggers, when the payload carries a `user_id`. Every inbound message fires the account-level webhook; the subscription's declarative conditions (`thread_id == …`) do the narrowing.

A subscription records which strategy it uses at registration time — account-level registration returning `[]` is success, not failure, and must not be treated as a registration error.
*Alternative*: register a per-todo Composio trigger for Gmail — rejected; Composio offers no per-thread Gmail trigger, and account-level triggers cannot be duplicated per subscriber.

### Matching: declarative `{field, op, value}` chains evaluated in-process against typed payload models
Three tiers total: single ops → AND-chains → optional LLM relevance check vs the todo canvas `Key Details` (cooldown-gated) for fuzzy intent. Declarative tiers cost ~nothing and are deterministic; tier 3 replaces any need for expression languages or sandboxes.
*Alternative*: JSONLogic-style evaluator — deferred until a real case outgrows chains.

### Validation at subscription time against curated matchable fields, not raw payloads
Full payload models stay loose (external webhooks omit fields); only the curated subset enters conditions. This gives type safety where it matters without pretending external payloads are strict.
*Alternative*: validating against full payload models — rejected; would block matching on best-effort fields.

### Repair loop: mechanical first, then hand the catalog back — no second LLM inside the tool
Field-name fuzzy match + operator-for-type table fixes most failures free. Anything ambiguous is rejected with the trigger's real fields attached to the error, and the *calling* agent corrects it and calls again.

The plan was a second, in-tool LLM pass for ambiguous cases. Building it turned out to be wrong on the design's own terms. The tool is already being called by a model inside a loop: returning a good error is a repair pass, it costs nothing extra, it uses the full conversation context rather than a narrow rewrite prompt, and — the deciding point — it happens **in the transcript**. An in-tool pass that silently rewrites what the model asked to watch is precisely the silent-intent-drift this section exists to prevent; it would just be drift we performed ourselves, one layer down, where no one can see it.

So the requirement it satisfies is unchanged (ambiguous failures get exactly one bounded, catalog-restricted correction attempt) and the mechanism is the agent loop rather than a nested call.
*Alternative*: open-ended agent repair loop — still rejected; the executor's own loop guard bounds retries, and a rejection that names the real fields converges in one.

### The triggering payload goes in the prompt, not only in the context dict
`trigger_context` reaches the model only through `format_workflow_execution_message`, which requires a selected workflow (`agents/core/messages.py:141`). The todo agent path has none, so a payload left in that dict is metadata the model never sees — the todo would wake knowing it was woken but not by what. The payload is rendered into the execution prompt instead.

### Execution: reuse `execute_tracked_todo`, carrying origin as a task parameter
The Redis lock, backoff/retry, and canvas logging come free. What does not come free is the origin stamp.

`execute_tracked_todo(_ctx, todo_id)` (`tracked_todo_tasks.py:69`) takes ARQ's **worker** context — a dict the worker builds (redis pool, job id), not a channel from the enqueuer. Trigger data cannot travel through it. The origin and payload therefore travel as a **new optional task parameter** threaded through four signatures, all of which currently hardcode the origin:

1. `execute_tracked_todo(_ctx, todo_id, trigger_origin=None)`
2. `_execute_todo_with_retry(todo_id, pool, trigger_origin)` (`:94`)
3. `_run_execution(...)` — stamps `"scheduled_todo"` literally for the workflow path
4. `_execute_via_agent(...)` — builds `trigger_context` as a local literal (`:326-332`)

Two consequences follow and are requirements, not details:
- **Retry must carry the origin.** The backoff re-enqueues at `:155` and `:192` pass only `todo_id`; without threading the parameter a failed trigger run silently retries as an ordinary scheduled run, losing both attribution and payload.
- **`todo_trigger` is an enum member, not a string.** `TriggerType` (`workflow_models.py:29`) holds `manual|schedule|integration`. Add `TODO_TRIGGER` and `SCHEDULED_TODO`, and replace the existing literals — a value written at one site and read at another is exactly what the Type Safety Ratchet requires be closed.

*Alternative*: run through workflow queueing — rejected; wrong execution record surface and mislabeled analytics.

### A locked todo defers its event, it does not drop it
`execute_tracked_todo` returns `skipped:{id} (lock held)` when the Redis lock is taken (`:85-87`) and nothing re-queues. For scheduled runs that is correct — the next scan picks it up. For a trigger it is data loss in the exact window self-wiring creates: GAIA sends the email, the run is still finishing, the reply lands, the event vanishes.

An `execute` action that finds the lock held re-enqueues itself on a bounded backoff (1m, 3m, 10m) instead of returning, then gives up with an error-level log. A single retry was the original plan and is not enough: the lock TTL is 30 minutes, so one short defer would routinely land on the same held lock and drop the event anyway — the exact failure the rule exists to stop. Three attempts covers a normal agent run without ever looping.

The cooldown key is written only when the action actually runs, so a deferred event is not suppressed as a repeat.

### Fan-out is not batched, so cooldown is mandatory
Workflows coalesce burst events from poll-based triggers via `coalesce_window_seconds` / `buffer_trigger_event` (`base.py:441-445`), keyed on `workflow.trigger_config`. The todo tap sits before that loop and has no equivalent config, so one poll returning 50 items reaches 50 subscription evaluations. Per-subscription cooldown is the only bound, which is why it is required rather than optional. Extending the coalesce buffer to subscriptions is deferred until a real poll-trigger subscription exists.

### Teardown: refcount summed in `TriggerService`, across every terminal path
`get_triggers_safe_to_delete` counts workflows only today; Composio upserts identical configs onto shared trigger IDs across both consumers, so deleting a workflow could kill a live todo subscription.

The count is summed **in `TriggerService`** from two repositories — `workflow_repository.count_trigger_references` plus a new `todo_repository.count_trigger_references` — rather than teaching the workflow repository to query the todos collection. Each repository owns its own collection.

Teardown covers every path that ends a todo's life, not only the graceful ones: completion, archival, failure, **and deletion** (`TodoService.delete_todo`, `bulk_delete_todos`, `delete_all_for_user`). Deletion is a separate code path from completion; leaving it out orphans the Composio trigger permanently with no record left to find it by. Account-level subscriptions hold no trigger IDs, so their teardown is a document update only.
*Alternative*: separate Composio triggers per todo — rejected; wastes quota and breaks the shared-upsert property.

### Dispatch reads must be indexed
The by-trigger-ID lookup is cross-user and runs on every webhook event; the account-level lookup runs on every inbound Gmail message for every connected user. Both need indexes on `todos`, mirroring `workflows_collection.create_index("trigger_config.composio_trigger_ids", sparse=True)` (`db/mongodb/indexes.py:511`). Without them each event scans the collection.

### Budget: the gate does not exist on this path yet and must be added
`enforce_daily_cost_budget` is called from `workflow_tasks.py:619`, `chat.py:147` and `bot.py:340` — never from `tracked_todo_tasks.py`. Scheduled todos are covered only by the middleware wall (`get_budget_stop_reason`), which stops the model mid-run rather than skipping the run cleanly. A trigger-caused execution takes the explicit gate before any execution record or LLM work, with its own `feature_key` in `app/config/rate_limits.py` (workflows use `trigger_workflow_executions`) so chatty triggers are bounded separately from a user's chat budget.

### Subscribing is the model's own judgement, with no post-send nudge
A tracked todo watches something because the model decided it should, using
`subscribe_todo_to_trigger` like any other tool. Nothing appends an instruction to
outbound tool results.

A middleware that appended "you just sent this, consider watching it" after every
Gmail/Calendar send was built and then removed. It bought one prompt at the cost of a
whole seam: a tool-call wrapper in the middleware stack, a tier flag threaded through
`create_middleware_stack`, and a two-hop handoff — because Gmail sends run in a provider
subagent that does not hold the subscription tool, so the identifier had to be reported
up through `finish_task` for the executor to act on. That handoff was the most fragile
part of the design and the least verifiable. The system prompt already tells the model
to watch what a todo is waiting on, and the tool is bound at the executor tier where the
decision belongs.

*Alternative*: a dedicated `watch_this_thread` tool — rejected. It would be a second,
narrower way to create the same record, diverging from the general subscription path the
moment either side changes.

### Calendar reminders reuse the same machinery, with the window set at registration
`calendar_event_starting_soon` already carries `minutes_before_start` (1–1440, default 10) which the handler writes as `countdown_window_minutes` on the Composio trigger config (`handlers/calendar.py:118-119`), and its payload carries `event_id`, `attendees`, `organizer_email`, `location` and `minutes_until_start`. So "remind me an hour before the Acme call" is a subscription with `notify` (or `execute`) whose condition narrows on `event_id` — the calendar analog of Gmail's `thread_id`.

The one asymmetry worth stating: the reminder window is **registration** config, not a payload condition. Distinct windows are therefore distinct Composio trigger instances, and two todos wanting the same window on the same calendar share one instance by Composio's upsert — which is exactly the sharing the todo refcount is there to protect. A todo that wants two reminders (an hour before *and* ten minutes before) holds two subscriptions, not one with two windows.

Creating an event from a todo-bound run is watched the same way as anything else: the model calls the subscription tool with the returned `event_id`.

### Expiry pause: subscription state, plus the existing `blocked` label
Workflows pause by flipping `activated=False` (`services/workflow/integration_pause.py:22`). Todos have no such field, and adding a second activation concept to `TodoDocument` for this alone would be a new state machine nobody else reads. Instead the subscription itself carries a status, and the todo gets the `blocked` label that the maintenance sweep already understands. Reconnect clears both.

The blocking labels (`waiting-for-reply`, `waiting-for-approval`, `blocked`) and the `_todo_redirect_action` notification builder that `notify` reuses currently live inside `app/workers/tasks/maintenance_sweep_tasks.py` (`:54`, `:427`). Both move to `app/constants/todos.py` and a shared notification helper before the dispatch path imports them — a service importing a worker task module is an import cycle waiting to happen, and `constants/todos.py` is already the home for `FAILED_LABEL` and friends for exactly this reason.

### Schema exposure: catalog returned by the subscription tool itself
Invoking the tool returns the selected trigger's matchable-fields with types/examples, so the model constructs conditions from known data.

The six existing tracked-todo tools are **always loaded** via `initial_tool_ids` (`build_graph.py:106-111`), not retrieved from ChromaDB. The subscription tools join them there — a tool the model cannot see when a reply-watching todo is being created is a tool that never gets used. The cost is a fixed prompt-budget increase on every executor turn, which is why the surface is kept to the smallest useful set and the field catalog is returned by the call rather than embedded in the description. The comms and todo prompts that enumerate the tracked-todo tools (`comms_prompts.py:377`, `todo_prompts.py`) are updated in the same change.

### Registration takes an owner ref, not a `workflow_id`
`TriggerService.register_triggers(user_id, workflow_id, trigger_name, trigger_config)` and `TriggerHandler.register` name their second parameter `workflow_id`. Passing a todo id into it would make every handler's logging and error text lie. The parameter is renamed to a neutral owner ref across the handlers and their callers in this change rather than wrapped in an adapter — a second name for the same thing is what the no-pass-through-wrappers rule forbids.

## Risks / Trade-offs

- [Chatty triggers burn executions] → explicit daily cost-budget gate on the todo execution path + mandatory per-subscription cooldowns (no batching upstream)
- [Refcount bug strands or kills live triggers] → contract tests covering workflow-delete/todo-survives, the reverse, and todo-delete
- [Account-level fan-out evaluates every user's inbound mail] → indexed `(user_id, trigger_name)` lookup on active subscriptions only; conditions evaluated in-process against a typed model
- [LLM repair weakens intent silently] → repair constrained to catalog fields; rejection path always available; repair attempts logged to the wide event
- [A subscription outlives the thing it was watching, e.g. the user deletes the draft] → teardown on terminal states *and deletion* covers it; orphan sweep re-checks armed subscriptions
- [Payload drift upstream repeats this audit] → the verified-schema note lives in each model; periodic re-verification script can be rerun from `openspec` change notes

## Migration Plan

Additive schema change (optional field on todo docs) — no data migration needed. The new Mongo indexes are created by the existing `indexes.py` startup path. `TriggerType` gains members; no existing value changes meaning, so stored workflow documents are unaffected. Renaming the handler `register` parameter is source-only — no stored shape depends on it.

Rollback = feature-off: the fan-out tap is behind the subscription records existing; empty subscriptions mean zero behavior change. Legacy broken Notion/Asana workflows are surfaced by existing failure paths, not migrated here.

## Open Questions

- Should `unblock` also reschedule execution, or only clear the blocking label and leave the next run to the existing schedule?
- Does the frontend picker ship with phase 1 or follow once the API is proven?
