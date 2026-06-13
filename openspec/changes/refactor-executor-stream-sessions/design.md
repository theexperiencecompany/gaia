## Context

Per-stream orchestration state lives in five module-level dicts in `inbox.py` (spawned flags, done events, subagent counters, subagent results, tool-event collectors), each with a register/get/deregister triple. `executor_runner.py` (818 lines) mixes six domains and infers the run kind from `stream_id.startswith("queued_")`. The tool_data ownership rule is duplicated as `if is_queued or workflow_id` across functions. One pinned test (`test_executor_runner_delivery.py`) asserts delivery invariants by patching `executor_runner` module attributes.

Session creation points today: live chat (`stream.py:139` → `register_executor_capture`), silent/workflow runs (`agent.py:270` → same), queued runs (`_process_next_queued_task` → `mark_executor_spawned` + `register_tool_event_collector`).

## Goals / Non-Goals

**Goals:**
- One navigable state object per stream; teardown drops everything at once.
- Explicit `RunKind` and a single source of truth for tool_data ownership.
- Domain-per-file layout matching repo conventions (~200–300 lines/file).
- Exactly two terminal delivery entry points (`deliver_result`, `persist_cancelled_run`).
- Zero behavior change: identical SSE/WS payloads, Mongo writes, Redis keys, cancellation semantics.

**Non-Goals:**
- No changes to LangGraph graphs, tools' LLM-facing schemas, or frontend.
- No new persistence/durability features (that was the previous change).
- No multi-process session sharing (sessions stay in-process by design; the `executor:busy` Redis lock remains the cross-process guard).

## Decisions

### 1. `session.py`: one `StreamSession` dataclass + one registry dict
`StreamSession(stream_id, kind, executor_spawned, done_event, tool_events, pending_subagents, subagent_results)` in a single `_sessions: dict[str, StreamSession]`. Module-level accessor functions (`create_session`, `get_session`, `get_or_create_session`, `teardown_session`, plus thin domain helpers like `mark_executor_spawned`, `signal_executor_done`, `increment_pending_subagents`, `drain_bg_subagent_results`) keep call-site diffs minimal while killing the five-dict sprawl.
- Auto-vivification parity: the old dicts auto-vivified (`setdefault`, `.get(x, 0) + 1`). `get_or_create_session(stream_id, kind=LIVE)` preserves that but logs a warning on implicit creation so ordering bugs surface instead of hiding.
- Alternative (methods on the dataclass called via `get_session(...)!.method()`) rejected: every call site would need None-handling; module functions centralize it once.

### 2. `RunKind = LIVE | QUEUED`; workflow stays a field, not a kind
`RunKind` captures the *spawn mechanism* (which determines collector registration, SSE closing, and queue-lock handling). Workflow-ness is delivery routing and ownership input, carried as `ExecutorRun.workflow_id` — exactly mirroring today's `configurable.get("workflow_id")`. This keeps truth tables identical: `is_queued` ⇔ `kind is QUEUED` (set at the two spawn sites, replacing prefix parsing); `executor_owns_tool_data` ⇔ `kind is QUEUED or workflow_id is not None`.
- The cosmetic `queued_` id prefix is kept for log greppability but is never parsed again.

### 3. `ExecutorRun` frozen dataclass as the run context
Replaces the 8–10 loose params threaded through `run_executor_background → _finalize_executor_run → delivery`. Built once per run via `ExecutorRun.from_configurable(...)` at both spawn sites (executor_tool, queue pop). Owns `is_queued` and `executor_owns_tool_data` properties — the single statement of the ownership rule.
- Lives in `session.py` (run identity + per-stream state are one domain); avoids an `executor_runner ↔ result_delivery` import cycle that placing it in the runner would cause.

### 4. Module split with acyclic imports
```
session.py            ← (stdlib only)
executor_capture.py   ← session            (public API unchanged: register/await/drain/note/teardown)
redis_writer.py       ← session
comms_narrator.py     ← graph manager      (narrate_executor_result, ex _invoke_comms_graph)
result_delivery.py    ← session, capture, comms_narrator   (deliver_result, persist_cancelled_run + routing helpers)
executor_queue.py     ← session, stream_manager, ws_manager (enqueue/pop/lock helpers; POP PREPARES, does not spawn)
executor_runner.py    ← all of the above   (ExecutorRun lifecycle: execute → finalize → spawn-next)
executor_tool.py      ← executor_runner, executor_queue, session
```
The old cycle risk (`queue` spawns runs, finished runs pop the queue) is broken by making `pop_next_queued_run` *prepare* (pop + parse + lock overwrite + session create + start_stream + `executor.stream_started` WS) and return a `PreparedQueuedTask`; the **runner** spawns it. Queue never imports runner.

### 5. Two terminal delivery entry points
`_finalize_executor_run(run, result_text, result_type)` branches once: cancelled+owns → `persist_cancelled_run(run)`; result_text → `deliver_result(run, ...)`. `deliver_result` absorbs `_dispatch_executor_result` + `_deliver_bg_notification` verbatim (narrate → compose → save → route exactly-one-transport), keeping `@traceable(name="bg_notification_delivery")`.
- The pinned test moves its patch targets from `executor_runner` to `result_delivery` with assertions unchanged — the invariants are the spec.

### 6. Queue domain consolidated in `executor_queue.py`
Push (`enqueue_task`, `_CONFIGURABLE_SCALAR_KEYS`), pop/prepare, and busy-lock helpers (`build/parse_lock_value`, `try_acquire_lock`) move out of `executor_tool.py`/`executor_runner.py`. `cancel_executor` keeps its queue-clearing logic but imports the lock parsing from the queue module.

## Risks / Trade-offs

- **[No integration tests on streaming]** → Mitigate with: behavior-preserving mechanical moves verified by mypy strict + ruff; the delivery unit test re-run; post-refactor grep proving zero stale references; manual smoke of live/queued/cancel flows before merge.
- **[Implicit auto-vivify behavior relied upon somewhere unnoticed]** → `get_or_create_session` preserves it 1:1 and logs a warning, so any reliance becomes visible in logs rather than breaking.
- **[Import cycle regression]** → Dependency direction documented above; `executor_queue` deliberately returns prepared work instead of spawning.
- **[Test patch-target drift]** → The delivery test is updated in the same change; CI runs it.

## Migration Plan

Single-release hard cutover: `inbox.py` deleted in the same commit that lands `session.py`; all importers updated together. Rollback = revert the one commit (no data/schema migration; Redis keys and Mongo documents untouched).

## Open Questions

- None blocking. (If a future change needs cross-process sessions, the registry is the seam — out of scope here.)
