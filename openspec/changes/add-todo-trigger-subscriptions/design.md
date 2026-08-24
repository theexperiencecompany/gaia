## Context

Tracked todos (`app/services/tracked_todo_service.py`, `app/workers/tasks/tracked_todo_tasks.py`) are durable Mongo documents executed on ARQ schedules; all reactivity is poll-based (30-min safety net, hourly maintenance sweep). Composio triggers (`app/services/triggers/`) fire integration events through `TriggerHandler.process_event` → workflow queueing; events matching no workflow are dropped. The only todo contact today is prompt text: `get_signal_matching_context` injects active todos into triggered runs.

All 22 supported trigger payload schemas were verified against Composio's live API (PR #1096) — including the discovery that Slack's receive-message payload has no thread identifier while Gmail carries `thread_id`. That verified field set is the foundation for condition matching.

## Goals / Non-Goals

**Goals:**
- Tracked todos react to external events via declarative, validated conditions on trigger payloads
- Full lifecycle symmetry with workflows: registration, refcounted teardown, reconnect resync, expiry pause
- Self-wiring common case: a todo that sends email auto-watches the reply thread
- The LLM constructs subscriptions from known schemas, never guesses

**Non-Goals:**
- Arbitrary code/bash expression matching (no sandbox per event)
- Slack thread-level matching (upstream payload lacks `thread_ts`; channel-level only)
- Migrating existing broken Notion all-events / Asana workflows
- A generic internal event bus

## Decisions

### Dispatch: tap inside `TriggerHandler.process_event`, before the no-workflow return
Fan out to todo subscribers inside the existing choke point rather than a second webhook task. The current early return at "no matching workflows" would drop todo-only events, so the todo lookup runs before it.
*Alternative*: endpoint-level second `spawn_logged_task` — rejected; duplicates signature/dedupe context and bypasses handler normalization.

### Matching: declarative `{field, op, value}` chains evaluated in-process against typed payload models
Three tiers total: single ops → AND-chains → optional LLM relevance check vs the todo canvas `Key Details` (cooldown-gated) for fuzzy intent. Declarative tiers cost ~nothing and are deterministic; tier 3 replaces any need for expression languages or sandboxes.
*Alternative*: JSONLogic-style evaluator — deferred until a real case outgrows chains.

### Validation at subscription time against curated matchable fields, not raw payloads
Full payload models stay loose (external webhooks omit fields); only the curated subset enters conditions. This gives type safety where it matters without pretending external payloads are strict.
*Alternative*: validating against full payload models — rejected; would block matching on best-effort fields.

### Repair loop: mechanical first, one bounded LLM pass, loud rejection
Field-name fuzzy match + operator-for-type table fixes most failures free; ambiguous cases get exactly one LLM rewrite restricted to catalog fields; unexpressible intent rejects with alternative triggers surfaced. Never water down intent — an approximating subscription executes todos on garbage.
*Alternative*: open-ended agent repair loop — rejected; unbounded cost and silent-intent-drift risk.

### Execution: reuse `execute_tracked_todo`, stamped as a new origin
The Redis lock already prevents double-fire mid-execution; backoff/retry/canvas logging come free. Stamp context with `trigger_type: "todo_trigger"` so budget gating, rate limits, and analytics attribute correctly. `execute_tracked_todo` currently accepts its ARQ `ctx` without forwarding it to `_execute_todo_with_retry`, so implementation MUST add an explicit context handoff into the retry helper and a contract test asserting `trigger_type: "todo_trigger"` reaches gating/analytics.
*Alternative*: run through workflow queueing — rejected; wrong execution record surface and mislabeled analytics.

### Teardown: extend refcounting to count todo references
`get_triggers_safe_to_delete` counts workflows only today; Composio upserts identical configs onto shared trigger IDs across both consumers, so deleting a workflow could kill a live todo subscription. Extend `count_trigger_references` to include the todos collection.
*Alternative*: separate Composio triggers per todo — rejected; wastes quota and breaks the shared-upsert property.

### Schema exposure: catalog returned by the subscription tool itself
Tool description stays semantically rich (ChromaDB retrieval fuel); invoking it returns the selected trigger's matchable-fields with types/examples. Auto-armed self-wiring subscriptions pass through the identical validator.

## Risks / Trade-offs

- [Chatty triggers burn executions] → same daily cost-budget gate as triggered workflows + mandatory cooldowns
- [Refcount bug strands or kills live triggers] → contract tests covering workflow-delete/todo-survives and reverse
- [LLM repair weakens intent silently] → repair constrained to catalog fields; rejection path always available; repair attempts logged to the wide event
- [Self-wiring captures stale thread IDs after user deletes the todo draft] → teardown on terminal states covers it; orphan sweep re-checks armed subscriptions
- [Payload drift upstream repeats this audit] → the verified-schema note lives in each model; periodic re-verification script can be rerun from `openspec` change notes

## Migration Plan

Additive schema change (optional field on todo docs) — no migration needed. Rollback = feature-off: fan-out tap is behind the subscription records existing; empty subscriptions mean zero behavior change. Legacy broken Notion/Asana workflows are surfaced by existing failure paths, not migrated here.

## Open Questions

- Should `unblock` action remove blocking labels only, or also reschedule execution?
- Notification copy and deep-link target for the `notify` action — reuse maintenance-sweep redirect pattern?
- Does the frontend picker ship with phase 1 or follow once API-proven?
