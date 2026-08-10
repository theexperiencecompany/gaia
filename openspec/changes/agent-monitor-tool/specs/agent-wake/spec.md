## ADDED Requirements

### Requirement: Inject a non-user-origin message
The system SHALL provide a primitive that injects a message into a conversation's history and triggers a silent agent turn, where the injected message is tagged with a background origin and MUST NOT be recorded or treated as a user-authored message.

#### Scenario: Background event seeds a silent turn
- **WHEN** the agent-wake primitive is invoked for conversation C with content `[monitor:errors in app.log] ERROR: db timeout`
- **THEN** a silent agent turn runs in conversation C seeded with that content, and the seed message is persisted with origin metadata distinguishing it from a user message

#### Scenario: Wake message is never stored as a user message
- **WHEN** an agent-wake message is persisted to the conversation
- **THEN** its stored type/role is not `user`, so UI and history rendering do not attribute it to the user

### Requirement: Agent treats background-origin messages as events
The agent's prompt contract SHALL instruct the agent to treat background-origin messages as events to react to, not as the user speaking, so the agent does not address the user as if they had sent the message.

#### Scenario: Agent reacts without misattributing intent
- **WHEN** the agent processes a background-origin wake message
- **THEN** the agent responds by acting on the event (e.g. investigating or notifying) rather than replying as though the user asked a question

### Requirement: Wake loop protection
The agent-wake primitive SHALL enforce a per-source sliding-window wake limit. A source that exceeds the configured maximum wakes within the window MUST be auto-paused and the user notified, preventing runaway reaction loops.

#### Scenario: Runaway source is auto-paused
- **WHEN** a wake source triggers more than the configured maximum wakes within the window
- **THEN** further wakes from that source are suppressed, the source is marked paused, and a single notification informs the user

### Requirement: Conversation targeting
A wake SHALL be delivered to the exact conversation captured by the source at registration time, never to an arbitrary or default conversation.

#### Scenario: Wake lands in the originating conversation
- **WHEN** a wake source registered in conversation C fires
- **THEN** the resulting silent turn runs in conversation C and nowhere else

### Requirement: Reusable beyond monitors
The agent-wake primitive SHALL be usable by any background source (monitors, workflow completions, executor results) and MUST NOT be coupled to the monitor implementation.

#### Scenario: A non-monitor source uses the same primitive
- **WHEN** a workflow-completion source invokes the agent-wake primitive
- **THEN** it produces a silent turn in the target conversation using the same origin-tagging and loop-protection behavior as a monitor source
