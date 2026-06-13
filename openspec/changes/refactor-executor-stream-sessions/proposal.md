## Why

The background-executor/streaming layer is hard to navigate and unsafe to extend. Per-stream orchestration state is scattered across five module-level dicts in `inbox.py` (each with its own register/get/deregister triple — 16 free functions); the run kind is inferred from a magic string prefix (`stream_id.startswith("queued_")`); the tool_data ownership rule ("live → comms attaches, queued/workflow → executor self-persists") is re-derived ad hoc in multiple functions; and `executor_runner.py` is 818 lines spanning six domains (comms invocation, follow-ups, routing lookup, WS broadcast, workflow notifications, delivery, drain, cancel persist, execution, queue + lock handoff) with five overlapping save/deliver helpers. Recent bug fixes (failure-proof tool_data persistence) had to be bolted on precisely because there was no single place these rules live.

## What Changes

- **One session object per stream.** Replace `inbox.py`'s five dicts with a single `StreamSession` dataclass (done-event, tool-event collector, subagent counter/results, spawned flag) in a new `session.py`, with one registry: `create / get / teardown`. Teardown drops the whole session — no per-dict cleanup to forget.
- **Explicit run identity.** `RunKind` (`LIVE | QUEUED`) replaces the `"queued_"` prefix parsing; an immutable `ExecutorRun` context (stream/conversation/user/task ids + workflow fields) replaces the 8–10 loose parameters threaded through the runner, and owns the single ownership rule as `ExecutorRun.executor_owns_tool_data`.
- **Split `executor_runner.py` by domain** (~818 → 4 focused modules): `executor_runner.py` (lifecycle: execute → finalize), `result_delivery.py` (narrate, compose, persist, route — including the cancelled-run persist), `comms_narrator.py` (silent comms invocation), `executor_queue.py` (queue push/pop + busy-lock helpers, shared with `call_executor`/`cancel_executor`).
- **One delivery entry point.** `deliver_result(run, …)` + `persist_cancelled_run(run)` subsume `_dispatch_executor_result`/`_deliver_bg_notification` branching; every terminal path goes through `_finalize_executor_run` → one of these two.
- **BREAKING (internal only):** `inbox.py` is deleted (hard cutover); all 7 importers move to `session.py`. No HTTP/WS/DB contract changes; behavior is preserved exactly.

## Capabilities

### New Capabilities
- `executor-orchestration-state`: Single-session orchestration model for executor streams — one state object per stream_id, explicit run kind, explicit tool_data ownership, domain-split delivery — with behavior identical to the pre-refactor flow.

### Modified Capabilities
<!-- None — executor-tool-data-persistence requirements are unchanged; this change restructures their implementation. -->

## Impact

- **Rewritten/new**: `app/agents/core/background/{session.py (new), executor_capture.py, redis_writer.py, executor_runner.py, executor_queue.py (new), result_delivery.py (new), comms_narrator.py (new), subagent_runner.py}`; `inbox.py` deleted.
- **Import/usage updates**: `app/agents/tools/{executor_tool.py, wait_for_subagents_tool.py}`, `app/agents/core/subagents/handoff_tools.py`, `app/agents/core/agent.py`, `app/services/chat/stream.py` (import paths only — `executor_capture` public API preserved).
- **Tests**: `tests/unit/agents/test_executor_runner_delivery.py` re-targets the delivery module; its invariants (exactly-one-transport, always-persisted, comms fallback, scoped source lookup) are unchanged.
- **No behavior change**: SSE/WS event shapes, Mongo writes, Redis keys (busy lock, queue, stream progress), cancellation semantics, and the failure-proof persistence fix all behave identically.
