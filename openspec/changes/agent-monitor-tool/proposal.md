## Why

GAIA's agent can start background work (the `bash` tool's detached mode, the `executor`) but it has no way to **watch a long-running source and react to each event as it happens**. The bash tool streams output only to the UI for the duration of one foreground call; once a turn ends, nothing can carry an out-of-band event back into the agent's reasoning loop. The agent state's `messages` channel can only be mutated by `call_agent` / `call_agent_silent` consuming a user request — there is no path for a background process to wake the agent with "this just happened." This blocks per-occurrence monitoring (log error lines, file changes, polled job/PR state) and any genuinely proactive, event-driven behavior.

## What Changes

- Add a **`monitor` agent tool** that registers a long-lived watch over a shell command running in the user's E2B sandbox. Each line the command emits on stdout is one event. The tool returns immediately with a `monitor_id`; the watch runs in the background until it exits, hits its timeout, or is cancelled.
- Add a **watcher runtime** that runs the command (sandbox background mode), streams stdout line-by-line over Redis pub/sub, and always publishes a terminal event on process exit (so silence never masks a crash).
- Add a **Redis-backed `MonitorRegistry`** so monitors survive the turn that created them and can be listed and cancelled.
- Add an **event router** with two delivery modes per monitor: `notify` (route each event to the existing `notification_service` → UI/WebSocket) and `agent` (wake the agent in the originating conversation with the event injected as a non-user message).
- Add an **out-of-band agent-wake primitive** that injects a synthetic, non-user-origin message into a conversation and triggers a silent agent turn — the missing "internal messaging" path. Reusable beyond monitors (workflows, executor completions).
- Add **`cancel_monitor` and `list_monitors`** lifecycle tools, registered alongside `bash` in `ToolRegistry`.

## Capabilities

### New Capabilities
- `agent-monitor`: agent-callable tool to register/list/cancel long-lived watches over sandbox commands, the watcher runtime that streams stdout events over Redis with guaranteed terminal events, the Redis-backed registry, and the event router with `notify`/`agent` delivery modes (including chattiness/loop guards and sandbox-lifecycle handling).
- `agent-wake`: an out-of-band primitive that injects a non-user-origin message into a conversation's history and triggers a silent agent turn, so background sources can drive the agent's reasoning loop without impersonating the user or causing wake loops.

### Modified Capabilities
<!-- No existing spec's requirements change. -->

## Impact

- **New code**: `apps/api/app/agents/tools/coding/monitor_tool.py` (tool + lifecycle tools), a watcher runtime + event router under `apps/api/app/services/monitor/`, a `MonitorRegistry` (Redis), and an agent-wake helper near `app/agents/core/background/`.
- **Modified code**: `app/agents/tools/core/registry.py` (register the three new tools), `app/agents/core/graph_builder/build_graph.py` (expose to the executor's `initial_tool_ids`), and the silent-invocation path (`call_agent_silent`) to accept a non-user-origin seed message.
- **Reused infra (no change)**: E2B sandbox lifecycle (`acquire_sandbox`), bash background mode + `artifact_watcher` streaming pattern, `stream_manager` Redis pub/sub, `notification_service` + WebSocket delivery, the `_executor_tasks` background-task tracking pattern.
- **Dependencies**: none new. Redis, E2B, RabbitMQ/WebSocket already present.
- **Operational**: respects existing limits (E2B sandbox 3600s lifetime, sandbox idle-pause, ARQ 1800s job timeout); adds per-user concurrent-monitor caps and an auto-stop for overly chatty monitors.
