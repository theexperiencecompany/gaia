## ADDED Requirements

### Requirement: Single session object per executor stream

The system SHALL hold all per-stream executor orchestration state (executor-spawned flag, done-event, tool-event collector, pending-subagent counter, background-subagent results) in exactly one `StreamSession` object per `stream_id`, managed by a single registry with create/get/teardown operations. Tearing down a session MUST drop all of its state at once.

#### Scenario: Session teardown leaves no residue
- **WHEN** a stream's session is torn down after its run completes or is cancelled
- **THEN** no per-stream orchestration state for that `stream_id` remains registered
- **AND** subsequent lookups for that `stream_id` return no session

#### Scenario: Implicit state access is preserved but surfaced
- **WHEN** a component touches per-stream state for a `stream_id` that has no session (matching the old dicts' auto-vivify behavior)
- **THEN** a session is created so the operation succeeds as before
- **AND** a warning is logged so the ordering gap is visible

### Requirement: Explicit run kind and ownership rule

The system SHALL represent how an executor run was spawned as an explicit `RunKind` (`LIVE` or `QUEUED`) set at the spawn site, and SHALL NOT infer it by parsing the `stream_id` string. The tool_data ownership rule (live → comms path persists; queued or workflow → executor self-persists) SHALL be defined in exactly one place, as a property of the run context, and all terminal handlers SHALL consult it rather than re-deriving it.

#### Scenario: Queued run identified without string parsing
- **WHEN** a task is popped from the executor queue and spawned
- **THEN** its run context carries `RunKind.QUEUED` assigned at the pop site
- **AND** no code path decides behavior by checking the stream id's text prefix

#### Scenario: Ownership consulted from one source
- **WHEN** any terminal handler decides whether the executor persists its own tool_data
- **THEN** the decision comes from the run context's ownership property
- **AND** the live/queued/workflow truth table matches the pre-refactor behavior exactly

### Requirement: Domain-split delivery with two terminal entry points

The executor result layer SHALL expose exactly two terminal entry points — one for delivering a completed/errored result (narrate via comms, compose, persist, route over exactly one transport) and one for persisting a cancelled run's already-streamed tool cards — and every executor terminal path SHALL go through one of them. Delivery behavior MUST be preserved: a result is persisted to MongoDB before any push, routed to exactly one transport chosen by the conversation's source, and falls back to the raw executor text when comms narration is unavailable.

#### Scenario: Completed run routes over exactly one transport
- **WHEN** a queued or workflow executor run completes with result text
- **THEN** the message is saved to MongoDB and then delivered over exactly one transport (platform API for bot conversations, WebSocket otherwise, workflow notification for workflow runs)

#### Scenario: Cancelled run uses the cards-only persist path
- **WHEN** a cancelled queued/workflow run reaches its terminal handler with produced tool cards
- **THEN** the cards-only persist entry point saves them keyed by `task_id`
- **AND** no narration, follow-ups, or re-broadcast occur

#### Scenario: Behavior parity under the pinned delivery test
- **WHEN** the delivery unit test exercises bot-platform and web/mobile conversations
- **THEN** the exactly-one-transport, always-persisted, and comms-fallback assertions pass unchanged against the new module layout
