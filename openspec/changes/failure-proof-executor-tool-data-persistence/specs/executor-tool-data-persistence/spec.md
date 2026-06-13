## ADDED Requirements

### Requirement: Single-owner drain of executor tool_data

The system SHALL persist an executor stream's accumulated tool_data through exactly one owner per `stream_id`, using the single `drain_executor_tool_data` read of the in-process tool-event collector. For a live delegated stream the comms path SHALL be the sole owner; for a queued or workflow stream the executor's own finalize step SHALL be the sole owner. Because the drain is a non-destructive read, the system MUST NOT persist the same stream's executor tool_data from more than one owner.

> Out of scope (Option A): durable cross-process checkpointing and mid-run process-crash recovery. Cancellation handlers run in the same process as the collector, so an in-process drain covers every reported failure.

#### Scenario: Live stream is drained only by the comms path
- **WHEN** a live delegated executor stream completes or is cancelled
- **THEN** its executor tool_data is persisted only by the comms-side attach step
- **AND** the executor's own finalize step does not also persist it, so no card is duplicated

#### Scenario: Queued stream is drained only by the executor finalize step
- **WHEN** a queued or workflow executor stream completes or is cancelled
- **THEN** its executor tool_data is persisted only by the executor's finalize step
- **AND** the result message contains each tool card exactly once

### Requirement: Persist executor tool_data when a live stream is cancelled

When a live comms+executor turn is cancelled (composer Stop button or `POST /cancel-stream/{stream_id}`), the system SHALL drain the executor tool-event collector (or its durable checkpoint) and attach the resulting cards onto the saved bot message in MongoDB. The cancellation path MUST NOT skip executor tool_data persistence.

#### Scenario: Stop button preserves executor cards already produced
- **WHEN** a live turn has rendered executor tool cards and the user clicks Stop
- **THEN** the saved bot message in MongoDB includes the executor tool_data produced before cancellation
- **AND** after a page refresh the message still renders those cards

#### Scenario: No duplicate cards when both attach paths could fire
- **WHEN** executor tool_data is attached on the happy path and also drained on a terminal path for the same `stream_id`
- **THEN** the persisted message contains each tool card exactly once
- **AND** no card is dropped

### Requirement: Persist executor tool_data when cancelled via command

When an executor is cancelled through the `cancel_executor` agent command, the system SHALL persist the executor tool_data produced before cancellation onto a saved message, applying the same drain-and-attach behavior as the Stop button path.

#### Scenario: cancel_executor preserves produced cards
- **WHEN** the agent invokes `cancel_executor` for a running executor that has already produced tool cards
- **THEN** the produced executor tool_data is drained and persisted to MongoDB
- **AND** the message reflecting that turn renders the cards after refresh

### Requirement: Persist queued background executor results, including on cancellation

A queued background executor run SHALL persist its tool_data to MongoDB on every terminal outcome — success, error, and cancellation — keyed on `message_id == task_id` so it reconciles with the live placeholder by id. On cancellation the system SHALL save a cards-only message (the tool_data already streamed, with empty result text and no comms re-narration) and SHALL NOT re-broadcast the already-streamed cards over the WebSocket; the existing conversation sync surfaces the saved copy. The system SHALL skip the write only when no cards were produced.

#### Scenario: Successful queued run persists cards keyed by task_id
- **WHEN** a queued executor run completes successfully
- **THEN** the bot message with its tool_data is saved to MongoDB with `message_id` equal to the run's `task_id`
- **AND** the live placeholder (keyed by `task_id`) reconciles with it by id rather than duplicating

#### Scenario: Cancelled queued run persists cards without re-broadcasting
- **WHEN** a queued executor run is cancelled after producing tool cards
- **THEN** a cards-only message carrying the produced tool_data is saved to MongoDB keyed by `task_id`
- **AND** the cards are not re-pushed over the WebSocket (they were already streamed live)
- **AND** the saved copy reaches other devices / survives a cache clear via the normal conversation sync

#### Scenario: Cancelled run with no cards writes nothing
- **WHEN** a queued executor run is cancelled before producing any tool cards
- **THEN** no message is written for that run

#### Scenario: Missed delivery does not duplicate or lose the message
- **WHEN** any immediacy signal (e.g. the happy-path WebSocket push) is missed after the message was saved
- **THEN** the message remains available in MongoDB
- **AND** a subsequent conversation sync reconciles it with the placeholder by `message_id == task_id` without creating a duplicate

### Requirement: Client sync must not delete locally-retained tool_data

The client conversation sync SHALL NOT overwrite a non-empty local message `tool_data` with an empty or missing `tool_data` from the synced backend copy. When merging a remote message over an existing local message, a present local `tool_data` MUST be preserved if the remote copy lacks it.

#### Scenario: Sync preserves locally-saved cards when remote lacks them
- **WHEN** the client has a locally-saved message with tool_data and a sync returns the same message without tool_data
- **THEN** the merged message retains the local tool_data
- **AND** the cards remain rendered

#### Scenario: Sync still adopts remote tool_data when present
- **WHEN** a sync returns a message whose tool_data is present and non-empty
- **THEN** the merged message uses the remote tool_data
- **AND** local and remote stay consistent

### Requirement: Live queued placeholder survives refresh

The live placeholder created for a queued executor stream SHALL persist its accumulated tool_data to the client's durable local store (IndexedDB) as events arrive, so live progress survives a page refresh that occurs before the final `conversation.new_message` WebSocket event is received.

#### Scenario: Refresh before final message keeps live cards
- **WHEN** a queued executor stream is rendering live tool cards in the active conversation
- **AND** the user refreshes before the final WebSocket message arrives
- **THEN** the previously-rendered cards are restored from the local store

#### Scenario: Final message replaces placeholder without losing cards
- **WHEN** the final `conversation.new_message` event arrives for a queued task that had a live placeholder
- **THEN** the placeholder is replaced by the persisted final message
- **AND** the final message renders at least the tool_data that was shown live
