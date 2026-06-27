## ADDED Requirements

### Requirement: Register a monitor
The agent SHALL be able to register a long-lived watch over a shell command running in the user's sandbox. The `monitor` tool MUST return immediately with a unique `monitor_id` without blocking on the watched command, and MUST accept `command`, `description`, `delivery` (`notify` | `agent`), `timeout_seconds` (default 300), and `persistent` (default false).

#### Scenario: Monitor starts and returns immediately
- **WHEN** the agent calls `monitor(command="tail -n0 -F /workspace/app.log | grep --line-buffered ERROR", description="errors in app.log", delivery="notify")`
- **THEN** the tool returns a `monitor_id` and a confirmation referencing the description within one tool call, while the watched command continues running in the background

#### Scenario: Invalid command is rejected
- **WHEN** the agent calls `monitor` with an empty command or one exceeding the size limit
- **THEN** the tool returns a validation error and registers no monitor

### Requirement: Per-line event streaming
The watcher runtime SHALL treat each stdout line from the watched command as a single event and publish it to the monitor's Redis pub/sub channel. Lines emitted close together MAY be batched into one routed notification.

#### Scenario: Each matching line becomes one event
- **WHEN** the watched command writes three matching lines to stdout
- **THEN** the runtime publishes three events to `monitor:{user_id}:{monitor_id}`

### Requirement: Guaranteed terminal event
The watcher runtime SHALL always publish a terminal event when the watched process exits, including its exit code, regardless of whether any matching lines were produced. Silence MUST NOT be the only signal of completion or failure.

#### Scenario: Process crashes with no matching output
- **WHEN** the watched command exits non-zero without emitting any matching stdout line
- **THEN** the runtime publishes a terminal event carrying the exit code and marks the monitor `stopped`

#### Scenario: Timeout reached
- **WHEN** a non-persistent monitor reaches `timeout_seconds` while still running
- **THEN** the runtime kills the process, publishes a terminal timeout event, and marks the monitor `stopped`

### Requirement: Notify delivery mode
When `delivery="notify"`, the event router SHALL route each event to the existing notification service so it reaches the user via the established WebSocket path, using the monitor `description` as the source label.

#### Scenario: Error line reaches the user as a notification
- **WHEN** a monitor with `delivery="notify"` produces an event
- **THEN** a notification with source `BACKGROUND_JOB`, the monitor description as title, and the event line as body is delivered to the user

### Requirement: Agent delivery mode
When `delivery="agent"`, the event router SHALL invoke the agent-wake primitive for the originating conversation so the agent can react to the event. See the `agent-wake` capability for the wake contract.

#### Scenario: Event wakes the agent in the originating conversation
- **WHEN** a monitor with `delivery="agent"` registered in conversation C produces an event
- **THEN** the router triggers a silent agent turn in conversation C seeded with the event

### Requirement: Monitor persistence and registry
Registered monitors SHALL persist beyond the turn that created them in a Redis-backed registry recording command, description, delivery, conversation_id, status, and counters. Monitors MUST be scoped per user and per originating conversation.

#### Scenario: Monitor survives the originating turn
- **WHEN** the agent turn that called `monitor` completes
- **THEN** the monitor remains active and continues producing events until it exits, times out, or is cancelled

### Requirement: List and cancel monitors
The agent SHALL be able to list its active monitors and cancel a specific monitor by id. Cancelling MUST stop the watched process, remove the monitor from the registry, and release its sandbox resources.

#### Scenario: List active monitors
- **WHEN** the agent calls `list_monitors` while two monitors are active
- **THEN** the tool returns both monitor ids with their descriptions and statuses

#### Scenario: Cancel a monitor
- **WHEN** the agent calls `cancel_monitor(monitor_id)` for an active monitor
- **THEN** the watched process is terminated, the monitor's registry entries are deleted, and no further events are produced

### Requirement: Chattiness protection
The runtime SHALL auto-stop any monitor that exceeds a configured event rate within a sliding window, and notify the user that it was stopped for excessive output.

#### Scenario: Overly chatty monitor is stopped
- **WHEN** a monitor produces more than the configured maximum events per window
- **THEN** the runtime stops the monitor and emits a single notification explaining it was auto-stopped

### Requirement: Sandbox lifecycle handling
An active monitor SHALL prevent the sandbox idle-pause from terminating its watched process while running. On sandbox expiry, a `persistent` monitor SHALL re-arm on the next sandbox lifetime and a non-persistent monitor SHALL be marked `stopped` with the user notified.

#### Scenario: Active monitor keeps the sandbox warm
- **WHEN** a monitor is active and the user is otherwise idle past the idle-pause threshold
- **THEN** the sandbox is not paused while the monitor is running

#### Scenario: Persistent monitor re-arms after sandbox expiry
- **WHEN** the sandbox reaches its lifetime limit while a `persistent` monitor is active
- **THEN** the runtime re-arms the watched command on a fresh sandbox and the monitor continues

### Requirement: Per-user concurrency cap
The system SHALL enforce a maximum number of concurrently active monitors per user, rejecting new registrations beyond the cap.

#### Scenario: Registration beyond the cap is rejected
- **WHEN** a user already has the maximum allowed monitors active and the agent calls `monitor` again
- **THEN** the tool returns an error indicating the cap was reached and registers no new monitor
