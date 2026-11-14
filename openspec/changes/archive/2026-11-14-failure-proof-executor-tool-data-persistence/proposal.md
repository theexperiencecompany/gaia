## Why

When a user stops a streaming response — from the composer Stop button, the `cancel_executor` agent command, or by cancelling a queued background task — all of the executor's tool cards (search results, calendar, email, file ops, etc.) disappear from the message. The data exists in memory during the stream but is only ever written to MongoDB on the *happy completion path*; every cancellation, crash, or timeout discards it. The frontend then compounds the loss: its sync merge replaces the locally-saved message with the card-less backend copy, and the queued-task placeholder is never persisted at all. The result is a turn that visibly did work but renders empty after stopping or refreshing.

## What Changes

- **Durably checkpoint executor tool_data as it streams.** The background executor's tool events currently live only in an in-memory collector (no Redis progress, unlike comms text). Mirror the comms checkpoint so cancel/crash/timeout can always recover whatever was produced.
- **Drain + persist executor tool_data on every terminal path, not just success.** The three exit points that currently skip persistence when cancelled — `_attach_executor_tool_data` (live), `_finalize_executor_run` (queued/command), and the executor's own cancellation branch — must drain the collector and save the cards (and, for queued runs, save a partial/cancelled message so it survives).
- **Make the frontend sync merge field-preserving.** `mergeMessageLists` must never overwrite a non-empty local `tool_data` with an empty/missing remote one. Today it does wholesale "remote always wins" replacement, deleting cards the client already saved on abort.
- **Persist the queued-executor live placeholder to IndexedDB.** `useExecutorStream` keeps the placeholder (and its live cards) only in the Zustand store; on cancel/refresh before the final WebSocket message it vanishes. Persist it so live progress survives.
- **Keep Mongo-save-before-WebSocket ordering** (already correct) so WebSocket delivery stays best-effort while MongoDB remains the source of truth.

## Capabilities

### New Capabilities
- `executor-tool-data-persistence`: Guarantees that an executor turn's tool_data (live, command-cancelled, and queued/background paths) is durably persisted and rendered after stopping, cancelling, crashing, or refreshing — and that client-side sync never deletes locally-retained tool_data.

### Modified Capabilities
<!-- None — no existing capability spec covers streaming/tool_data persistence. -->

## Impact

- **Backend** (`apps/api`):
  - `app/services/chat/stream.py` — `_attach_executor_tool_data` (drain-on-cancel), `_persist_turn` / `_finalize_stream`.
  - `app/agents/core/background/executor_runner.py` — `_finalize_executor_run`, `_dispatch_executor_result` (persist cancelled/partial queued runs).
  - `app/agents/core/background/redis_writer.py` / `executor_capture.py` — durable Redis checkpoint of the tool-event collector.
  - `app/core/stream_manager.py` — progress checkpoint/recovery for executor streams.
- **Frontend** (`apps/web`):
  - `src/services/syncService.ts` — field-preserving merge for `tool_data`.
  - `src/features/chat/hooks/useExecutorStream.ts` — persist queued placeholder to IndexedDB.
- **Data stores**: additional Redis progress writes (keyed by `stream_id`, existing TTL); no schema change to MongoDB message documents.
- **No API contract changes**; `POST /cancel-stream/{stream_id}` and WebSocket event shapes are unchanged.
