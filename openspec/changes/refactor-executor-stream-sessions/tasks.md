## 1. Session model

- [x] 1.1 Create `app/agents/core/background/session.py`: `RunKind`, `StreamSession`, `ExecutorRun` (with `from_configurable`, `is_queued`, `executor_owns_tool_data`), single `_sessions` registry, accessors (`create_session`, `get_session`, `get_or_create_session` with implicit-create warning, `teardown_session`), and domain helpers (`mark_executor_spawned`, `was_executor_spawned`, `signal_executor_done`, subagent counter/result functions).
- [x] 1.2 Rewrite `executor_capture.py` on top of `session.py`, public API unchanged (`register_executor_capture`, `await_executor_done`, `drain_executor_tool_data`, `build_returned_to_frontend_note`, `teardown_executor_capture`).
- [x] 1.3 Update `redis_writer.py` to append tool events to the session's collector.
- [x] 1.4 Update consumers to the session API: `subagent_runner.py` (background), `wait_for_subagents_tool.py`, `handoff_tools.py`, `executor_tool.py` (`mark_executor_spawned` import).
- [x] 1.5 Delete `inbox.py`; grep proves zero remaining references.

## 2. Domain split

- [x] 2.1 Create `comms_narrator.py` with `narrate_executor_result` (moved `_invoke_comms_graph`, unchanged body).
- [x] 2.2 Create `result_delivery.py`: `deliver_result(run, …)` (absorbs `_dispatch_executor_result` + `_deliver_bg_notification`, keeps `@traceable`), `persist_cancelled_run(run)`, and the moved helpers (`_broadcast_message`, `_broadcast_bot_message`, `_build_follow_up_actions`, `_lookup_user_message_content`, `_get_conversation_source`, `_dispatch_workflow_notification`).
- [x] 2.3 Create `executor_queue.py`: enqueue (+`_CONFIGURABLE_SCALAR_KEYS`), `pop_next_queued_run` returning `PreparedQueuedTask` (pop, parse, lock overwrite, QUEUED session, `start_stream`, `executor.stream_started` WS — no spawning), lock helpers (`build_lock_value`, `parse_lock_value`, `try_acquire_lock`).
- [x] 2.4 Rewrite `executor_runner.py` to the lifecycle only: `run_executor_background(run, task, configurable, user_time)`, `_execute_executor`, `_finalize_executor_run(run, …)` (cancel → `persist_cancelled_run` when run owns tool_data; result → `deliver_result`; queued teardown/DONE; spawn-next via `pop_next_queued_run` + create_task; lock release).
- [x] 2.5 Update `executor_tool.py`: build `ExecutorRun` at dispatch, use `executor_queue` lock/enqueue/parse helpers, spawn with the new runner signature.

## 3. Verification (behavior parity)

- [x] 3.1 Re-target `tests/unit/agents/test_executor_runner_delivery.py` to `result_delivery` with assertions unchanged; test passes.
- [x] 3.2 `nx type-check api` and `nx lint api` clean; grep shows no stale `inbox`/prefix-parsing references.
- [ ] 3.3 Manual smoke (live turn with executor cards; queued task; cancel mid-run) — flows behave as before.

## 4. Queue-lock lifecycle hardening (bugs found by adversarial tests)

- [x] 4.1 BUG B (deterministic): Stop/cancel stranded all queued tasks — cancelled finalize never popped the queue and deleted the lock. Fixed: the handoff now runs on every terminal path; a Stop targets only the running task (cancel-all still clears the queue itself).
- [x] 4.2 BUG C (deterministic): finalize deleted the busy lock unconditionally — a stale cancelled run's finalize could delete a NEWER run's lock, enabling concurrent executors. Fixed: `get_lock_state` (OURS/FREE/FOREIGN) + `release_lock_if_owned`; FOREIGN locks are never touched.
- [x] 4.3 BUG A (race): a task enqueued between finalize's empty pop and its lock release stranded until the next executor call (or queue-TTL expiry). Fixed: `reclaim_stranded_task` — post-release NX-claim recheck; a concurrent acquirer always wins cleanly.
- [x] 4.4 Red-first verification: the strand and foreign-lock tests failed against the pre-fix code; 89 tests green after; mypy + ruff clean.
