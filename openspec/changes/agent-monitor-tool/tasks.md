## 1. Constants and registry foundation

- [ ] 1.1 Add monitor constants to `apps/api/app/constants/` (Redis key prefixes `monitor:meta:{user_id}:{monitor_id}` and `monitor:active:{user_id}`, default `timeout_seconds`, max timeout clamp = sandbox lifetime, per-user concurrency cap, chattiness window + max events, wake window + max wakes)
- [ ] 1.2 Implement `MonitorRegistry` (Redis-backed) under `apps/api/app/services/monitor/registry.py`: `register`, `get`, `list_for_user`, `update_status`, `delete`, `incr_event_count`, `incr_wake_count`, with the per-user active set
- [ ] 1.3 Add `monitor_id` generation and the registry record shape (command, description, delivery, conversation_id, status, created_at, counters)

## 2. Watcher runtime (Phase 1 — notify only)

- [ ] 2.1 Implement the watcher runtime under `apps/api/app/services/monitor/watcher.py`: acquire the user's sandbox via `acquire_sandbox(user_id)` and run the command with `background=True` and an `on_stdout` callback that publishes each line to `monitor:{user_id}:{monitor_id}` (model on `artifact_watcher.py`)
- [ ] 2.2 Add a sibling asyncio task that detects process exit and publishes the guaranteed terminal event (exit code / timeout), then marks the monitor `stopped`
- [ ] 2.3 Enforce `timeout_seconds` (skip when `persistent`); on timeout kill the process and publish a terminal timeout event
- [ ] 2.4 Spawn the runtime as a tracked background task using the `_executor_tasks` pattern (`asyncio.create_task` + add-to-set + `add_done_callback(discard)`)

## 3. Event router (Phase 1 — notify only)

- [ ] 3.1 Implement the event router under `apps/api/app/services/monitor/router.py`: subscribe to the monitor's Redis channel and dispatch by delivery mode
- [ ] 3.2 Implement `notify` delivery: call `notification_service.create_notification(source=BACKGROUND_JOB, title=description, body=line)` per event
- [ ] 3.3 Implement chattiness guard: increment the event counter; auto-stop and emit a single explanatory notification when the window max is exceeded

## 4. Monitor tools (Phase 1)

- [ ] 4.1 Implement `monitor_tool.py` under `apps/api/app/agents/tools/coding/`: `@tool`-decorated `monitor(command, description, delivery, timeout_seconds=300, persistent=False)` that validates input, enforces the per-user cap, registers the monitor, starts the runtime, and returns immediately with the `monitor_id`
- [ ] 4.2 Implement `cancel_monitor(monitor_id)`: terminate the watched process, delete registry entries, release sandbox resources
- [ ] 4.3 Implement `list_monitors()`: return active monitors (id, description, status) for the user
- [ ] 4.4 Write the tool description teaching `--line-buffered`, matching all terminal states, and `notify` vs `agent` selection (mirror the harness Monitor doc, adapted to GAIA)
- [ ] 4.5 Register the three tools in `app/agents/tools/core/registry.py` and add them to the executor's `initial_tool_ids` in `app/agents/core/graph_builder/build_graph.py`

## 5. Phase 1 verification

- [ ] 5.1 Manually verify: agent calls `monitor("tail -n0 -F /workspace/x.log | grep --line-buffered ERROR", "errors in x.log", delivery="notify")`, write ERROR lines into the file, confirm one notification per line reaches the UI
- [ ] 5.2 Verify the terminal event fires and the monitor is marked `stopped` when the command exits (including non-zero with no matching output)
- [ ] 5.3 Verify `list_monitors` and `cancel_monitor` behave per spec
- [ ] 5.4 Run `nx type-check api` and `nx lint api`

## 6. Agent-wake primitive (Phase 2)

- [ ] 6.1 Decide and implement the non-user origin representation on `MessageModel` (dedicated type/role vs `metadata.origin = "monitor"`) — choose the smallest-blast-radius option and ensure persistence never stores it as `type:"user"`
- [ ] 6.2 Implement the agent-wake helper near `app/agents/core/background/`: inject the origin-tagged seed message and trigger a silent turn via `call_agent_silent` for the captured `conversation_id`
- [ ] 6.3 Update `call_agent_silent` (and the comms prompt) to accept and correctly frame a background-origin seed message as an event to react to, not a user turn
- [ ] 6.4 Implement the wake-loop guard: per-source sliding-window `wake_count`; auto-pause the source and notify the user when the max is exceeded
- [ ] 6.5 Keep the primitive decoupled from monitors so other sources (workflow completion, executor results) can reuse it

## 7. Wire agent delivery (Phase 2)

- [ ] 7.1 Implement `agent` delivery in the router: on each event, invoke the agent-wake helper for the monitor's `conversation_id` with content `[monitor:{description}] {line}`
- [ ] 7.2 Verify a `delivery="agent"` monitor wakes the agent only in the originating conversation and that the agent reacts without misattributing the message to the user
- [ ] 7.3 Verify the wake-loop guard auto-pauses a self-triggering monitor

## 8. Hardening (Phase 3)

- [ ] 8.1 Implement sandbox keep-warm while a monitor is active (register the monitor as an activity source so idle-pause does not fire)
- [ ] 8.2 Implement re-arm on sandbox expiry for `persistent` monitors; mark non-persistent monitors `stopped` and notify on expiry
- [ ] 8.3 Reconcile `timeout_seconds`/`persistent` against the 3600s sandbox lifetime and 1800s ARQ limits; clamp and document
- [ ] 8.4 Confirm the router works across the worker/main split via the existing RabbitMQ→WebSocket notification bridge
- [ ] 8.5 Final `nx type-check api` and `nx lint api`; clean up any dead code introduced
