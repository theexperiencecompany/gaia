## Context

GAIA runs a LangGraph agent (comms tier + executor tier) whose tools execute inside a per-user E2B remote sandbox. The relevant existing pieces:

- **`bash` tool** (`apps/api/app/agents/tools/coding/bash_tool.py`): runs commands via `sbx.commands.run(cmd, cwd, timeout, on_stdout=..., on_stderr=...)`, already streams output chunk-by-chunk to the UI through `get_stream_writer()`, and has a `background=True` detached mode that returns a PID + log path.
- **`ArtifactWatcher`** (`apps/api/app/services/sandbox/artifact_watcher.py`): runs `tail -n0 -F <path>` with `background=True` and an `on_stdout` callback — the exact line-streaming primitive a monitor needs.
- **`stream_manager`** (`apps/api/app/core/stream_manager.py`): Redis pub/sub on `stream:{id}` channels, plus progress keys — the proven decoupled event bus.
- **`notification_service`** + WebSocket (`app/services/notification_service.py`, `app/core/websocket_manager.py`, `websocket_consumer.py`): server-initiated messages to the UI, with a `BACKGROUND_JOB` source already defined.
- **Executor background pattern** (`app/agents/tools/executor_tool.py`, `app/agents/core/background/`): fire-and-forget `asyncio.create_task`, tracked in `_executor_tasks` with `add_done_callback(discard)`; results posted back into the conversation as new messages.
- **Sandbox lifecycle** (`app/services/sandbox/lifecycle.py`): `acquire_sandbox(user_id)` context manager, one sandbox per user, **auto-pause after idle**, 3600s lifetime.

The one missing capability: nothing can inject a message into the agent's `messages` state from outside a turn. The agent only "thinks" when `call_agent` / `call_agent_silent` consumes a request. This design adds that path and builds an event-driven monitor on top of it.

## Goals / Non-Goals

**Goals:**
- An agent-callable `monitor` tool that registers a long-lived watch over a sandbox command, returning immediately with a `monitor_id`.
- Each stdout line becomes one routed event; a terminal event is always emitted on process exit (silence never masks a crash/hang).
- Two delivery modes: `notify` (UI only, via existing notification infra) and `agent` (wake the agent in the originating conversation).
- A reusable out-of-band **agent-wake** primitive that injects a non-user-origin message and triggers a silent turn, with loop protection.
- Monitors survive the turn that created them; listable and cancellable; respect sandbox/worker limits.

**Non-Goals:**
- A general cron/scheduler (tracked-todos already covers scheduled execution).
- Cross-user or global monitors — strictly per-user, per-conversation.
- Replacing the bash tool's foreground streaming or the executor.
- Guaranteed exactly-once event semantics across sandbox restarts (best-effort + terminal event; re-arm on resume is explicit).

## Decisions

### D1 — Two delivery modes, never conflated
Separate "tell the user" (`notify`) from "tell the agent" (`agent`). `notify` reuses `notification_service.create_notification(source=BACKGROUND_JOB, title=description, body=line)` end-to-end with zero new infra and ships first. `agent` is the new path built on the agent-wake primitive.
**Alternative considered:** always wake the agent and let it decide whether to notify. Rejected — most watches ("ping me when the build breaks") never need agent reasoning, and waking the LLM per log line is expensive and loop-prone.

### D2 — Watcher runtime reuses the `ArtifactWatcher` streaming pattern
Run the command inside `acquire_sandbox(user_id)` with `background=True` and an `on_stdout` callback that publishes each line to Redis pub/sub channel `monitor:{user_id}:{monitor_id}`. A sibling `asyncio` task watches for process exit and publishes a terminal `{type: "exit", code}` event.
**Alternative considered:** ARQ job per monitor. Rejected — ARQ tasks run to completion and don't stream incrementally; the 1800s job timeout is shorter than a `persistent` watch needs, and ARQ has no per-line callback.

### D3 — Redis-backed `MonitorRegistry`
One hash per monitor: `monitor:meta:{user_id}:{monitor_id}` → `{command, description, delivery, conversation_id, status, created_at, wake_count}`, plus a per-user set `monitor:active:{user_id}`. Mirrors `stream_manager`'s progress-key approach.
**Rationale:** monitors outlive the request; the in-process `_executor_tasks` set is not enough for list/cancel across requests or worker/main split.

### D4 — Agent-wake = synthetic non-user message + `call_agent_silent`
On an `agent`-delivery event, the router calls `call_agent_silent()` for the stored `conversation_id`, seeding `messages` with a message tagged as background origin (e.g. a dedicated role or a `metadata.origin = "monitor"` flag), content `f"[monitor:{description}] {line}"`. The comms agent's prompt is told to treat background-origin messages as events to react to, not as the user speaking.
**Alternative considered:** inject directly into LangGraph checkpoint state. Rejected — bypasses the agent's normal entry path, risks checkpoint corruption, and duplicates logic that `call_agent_silent` already owns.

### D5 — Loop and chattiness guards are runtime-enforced, not prompt-enforced
- **Loop guard:** per-monitor `wake_count` within a sliding window in Redis; `agent`-delivery monitors that exceed `MAX_WAKES_PER_WINDOW` are auto-paused and the user is notified.
- **Chattiness guard:** per-monitor event counter; monitors exceeding `MAX_EVENTS_PER_WINDOW` are auto-stopped (mirrors the harness behavior where noisy monitors are killed).
- **Terminal-event guarantee:** the runtime emits the exit event itself, so correctness doesn't depend on the agent writing a good grep filter — though the tool description still teaches `--line-buffered` and matching all terminal states.

### D6 — Sandbox-lifecycle handling
The sandbox auto-pauses on idle, which would kill a naive `tail -f`. Decision: a monitor keeps the sandbox warm while active (registered as an activity source so the idle-pause debounce does not fire), and on sandbox expiry/resume the runtime either re-arms the command (if `persistent`) or marks the monitor `stopped` and notifies. Bounded by the 3600s sandbox lifetime; `persistent` monitors re-arm across lifetimes.

### D7 — Tool surface mirrors the harness Monitor, adapted to GAIA
`monitor(command, description, delivery, timeout_seconds=300, persistent=False)` returns immediately; `cancel_monitor(monitor_id)`, `list_monitors()`. Registered in `ToolRegistry` next to `bash`; added to the executor's `initial_tool_ids`. `timeout_seconds` max clamped to the sandbox lifetime; `persistent` ignores timeout.

## Risks / Trade-offs

- **Wake loops** (agent reacts → produces log lines → re-wakes) → D5 sliding-window `wake_count` auto-pause + user notification.
- **Event storms** flooding the conversation/notifications → D5 chattiness auto-stop; encourage selective filters in the tool description.
- **Sandbox idle-pause silently killing a watch** → D6 keep-warm + explicit re-arm/notify on resume; never let a dead watch look "still running."
- **Buffering hides events** (`grep` without `--line-buffered`, `| head -N`) → can't fully prevent from outside; tool description teaches it and the runtime's terminal event still fires on exit.
- **Resource exhaustion** from many monitors per user → per-user concurrent-monitor cap enforced at registration.
- **Non-user message leaking into history as if user-authored** → D4 explicit origin tag; persistence and prompt both respect it; never store a monitor wake as a `type:"user"` message.
- **Worker/main split** (notification path differs in worker vs main app) → reuse `notification_service`'s existing RabbitMQ→WebSocket bridge; the router does not assume which app it runs in.

## Migration Plan

Phased, each phase independently shippable and reversible (the tool is purely additive — rollback = unregister it):
1. **Phase 1 — `notify` only:** registry + tool + watcher runtime + `notify` routing. No agent-wake. Verifiable end-to-end on existing infra.
2. **Phase 2 — agent-wake:** add the agent-wake primitive + `delivery="agent"` + loop guard.
3. **Phase 3 — hardening:** chattiness auto-stop, per-user caps, sandbox keep-warm/re-arm, limit reconciliation.

Rollback: remove the three tools from `ToolRegistry` / `initial_tool_ids`; active monitors are cancellable via Redis keys. No schema migrations.

## Open Questions

- Origin representation for wake messages: dedicated message `type` vs. `metadata.origin` flag — pick whichever the existing `MessageModel` + comms prompt accommodate with the smallest blast radius.
- Default per-user concurrent-monitor cap and the chattiness/wake window sizes — set conservative defaults, expose as constants in `app/constants/`.
- Whether `agent`-delivery wakes should land as a visible chat message or a silent context injection by default.
