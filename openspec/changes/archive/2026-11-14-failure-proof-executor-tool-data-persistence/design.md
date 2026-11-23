## Context

GAIA streams chat through a two-agent graph: `comms_agent` (front door) delegates real work to `executor_agent` via the `call_executor` tool. The executor runs as a detached `asyncio.Task` and publishes its tool events straight to the stream's Redis pub/sub channel via `make_redis_stream_writer` (`redis_writer.py`), which the frontend renders live. Those same events are appended to an in-memory per-`stream_id` collector (`executor_capture.py`). The collector is the **only** record of executor tool_data until the turn's final MongoDB write.

There are three terminal flows, and all three discard the collector instead of persisting it when the turn does not complete on the happy path:

1. **Live (Stop button / `cancel-stream`)** — `_attach_executor_tool_data` (`stream.py:482-483`) early-returns on `state.is_cancelled`, so executor cards are never `$push`ed onto the comms message.
2. **Command (`cancel_executor`)** — cancels the executor stream; `_finalize_executor_run` (`executor_runner.py:536-541`) sees `was_cancelled` and skips `_dispatch_executor_result` entirely.
3. **Queued background** — same `_finalize_executor_run` skip; additionally the live placeholder in `useExecutorStream` lives only in the Zustand store and is never written to IndexedDB.

The frontend then deletes its own copy: `mergeMessageLists` (`syncService.ts:38-44`) does wholesale "remote always wins" replacement, so the `syncWithRetry` that fires ~3s after Stop overwrites the locally-saved (on-abort) message with the card-less backend copy.

Executor tool_data is never checkpointed durably — unlike comms text/tool_data, which `process_data_chunk` writes to Redis stream-progress (`chunks.py:53,71`) and `recover_stream_state` reads back. So a crash or restart mid-run loses everything.

## Goals / Non-Goals

**Goals:**
- Executor tool_data survives all three stop/cancel paths and renders after refresh.
- Executor tool_data is durable across an API crash/restart mid-run (recoverable from Redis).
- Queued runs always leave a record in MongoDB (success, error, or cancelled-partial), saved before any WebSocket push.
- Client sync never deletes locally-retained tool_data.
- No duplicate tool cards when both the happy-path attach and a terminal-path drain run for the same stream.

**Non-Goals:**
- Resuming/continuing a cancelled executor run — cancellation still stops the work; we only persist what was already produced.
- Changing the `POST /cancel-stream/{stream_id}` contract or WebSocket event shapes.
- MongoDB message-document schema changes (`tool_data` already exists on the message model).
- Reworking comms-text persistence (already durable via stream-progress).

## Decisions

### 1. (Option A — chosen) In-process drain; no Redis checkpoint
The reported failures are all *cancellations within a live process* (Stop button, `cancel_executor`, queued-cancel). Every terminal handler runs in the same process as the in-memory `tool_event_collector`, so reading the collector at cancellation time is sufficient and reliable. We do **not** add a Redis durable checkpoint of executor tool_data.
- Rationale: a Redis checkpoint only adds value for a mid-run process crash, and crash-survivability is incomplete without a separate startup recovery sweep to re-drive persistence (no handler re-runs after a crash) — that is beyond the reported scope and would add code to the per-tool-event hot path. The checkpoint shape also mismatches (`update_progress` expects `{"tool_data": [...]}` while executor events are raw until `absorb_collector_event` runs). Deferred; revisit only if mid-run OOM/crash data-loss becomes a concern (Option B).
- Consequence: `drain_executor_tool_data` stays the single drain. It is a **non-destructive** read, so correctness depends on **single-ownership** (Decision 2), not on emptying the collector.

### 2. Drain-and-persist on every terminal path; idempotent by single-ownership
Replace the cancellation early-returns with an unconditional "drain collector → persist cards" step on the path that *owns* the stream. `drain_executor_tool_data` is a **non-destructive** read, so duplicates are prevented not by emptying the source but by ensuring exactly one owner persists per stream:
- **Live** (comms delegated via `call_executor`, shared `stream_id`): the comms-side `_attach_executor_tool_data` is the sole owner — it `$push`es onto `messages.$.tool_data`. The executor's own `_finalize_executor_run` self-persists only when `is_queued`/`workflow_id`, so for live it never touches Mongo. We remove the `is_cancelled` early-return from `_attach_executor_tool_data` only.
- **Queued / workflow** (own `queued_*` stream, no comms orchestrator): the executor's `_finalize_executor_run` is the sole owner. On cancel it drains and saves a partial message (Decision 3).
- Rationale: keeps one persistence shape (`drain_executor_tool_data` + reconstruct/group) across success and cancellation and preserves the existing single-owner split, satisfying "unify, don't patch the broken branch." No card-identity dedup layer is needed because the owner is unique per stream.

### 3. Queued cancellation persists cards-only to Mongo and lets sync reconcile (no WebSocket re-push)
On `was_cancelled`, `_finalize_executor_run` drains the collector and writes a **cards-only** bot message (no result text, no comms re-narration) to MongoDB — and does **not** broadcast it over the WebSocket. The cards were already streamed live and the frontend placeholder rendered + persisted them; re-pushing them is redundant. The saved message is keyed on `message_id == task_id` (the same id the placeholder already uses), so the frontend's existing conversation **sync** reconciles the two by id — automatically deduping with no special client logic and no dependency on a delivered signal.
- Rationale (this revises the original WebSocket-broadcast approach): "everything is already streamed before cancellation," so the only missing guarantee is *durability* (cache clear / other devices) — that is a MongoDB write, which sync already surfaces. Re-broadcasting fabricated a message and forced a no-comms delivery path; keying on `task_id` instead makes the placeholder and the persisted copy the same message.
- Consistency upgrade: the happy queued path (`_deliver_bg_notification`) also now keys its saved message on `message_id == task_id`. Its WebSocket push remains, but only for *immediacy* of the new comms-narrated text — if that push is missed, sync still reconciles by id, closing the lingering-duplicate-placeholder gap that persisting the placeholder would otherwise open.
- Cards-only on cancel: the placeholder showed cards with empty text (comms never narrated mid-stream), so the persisted copy is `response=""` + tool_data — identical to what the user already saw. We skip the write entirely when no cards were produced.

### 4. Field-preserving sync merge for `tool_data`
In `mergeMessageLists`, when overwriting an existing local message with a remote one, do not let an empty/missing remote `tool_data` replace a non-empty local `tool_data`; carry the local value forward. All other fields keep "remote wins."
- Rationale: a targeted, well-scoped guard on the one field that is produced client-side-first during streaming. A blanket field-level deep merge was rejected as broader than the problem and risks masking legitimate backend updates to other fields.

### 5. Persist the queued live placeholder to IndexedDB
`useExecutorStream` writes the placeholder message (keyed by `task_id`) and its accumulating `tool_data` to IndexedDB as events arrive, not only to the Zustand store. The final `conversation.new_message` (handled by `useBgMessageWebSocket`) continues to replace it by `message_id`, removing the `task_id`-keyed placeholder.
- Rationale: matches how the live comms stream already persists incrementally; closes the refresh-before-final gap without a new mechanism. Decision 4's field-preserving merge ensures the later synced final never blanks the restored cards.

## Risks / Trade-offs

- **Double-attach producing duplicate cards** → Single-owner drain (Decision 2): the collector/checkpoint is emptied on first drain, so only one terminal handler ever attaches a given card. Add a dedup guard keyed by card identity as a backstop.
- **Extra Redis writes per tool event** → `update_progress` is already called per comms chunk; executor event volume is comparable. Reuses existing key + TTL, so no new memory-lifecycle risk on the 8GB self-host box.
- **Partial/cancelled queued message could confuse users** → Mark/voice it as a result of stopped work (reuse the existing `[EXECUTOR_RESULT/ERROR]` framing); only persist when cards or partial text exist, so a no-op cancel writes nothing.
- **Recovered checkpoint diverging from what the client rendered** → Both derive from the same event stream; the field-preserving merge keeps the richer copy, so worst case the client keeps its locally-rendered cards rather than losing them.

## Migration Plan

- Purely additive behavior; no data migration. Deploy backend and frontend together (the field-preserving merge protects clients during the window where a backend may still under-persist).
- Rollback: revert independently. Reverting the backend reintroduces the loss-on-cancel but the frontend merge guard still protects locally-retained cards; reverting the frontend restores "remote wins" but the backend now persists cards, so sync no longer blanks them.

## Open Questions

- Should a cancelled queued run with zero produced cards and no partial text write nothing, or a minimal "stopped" marker message? (Leaning: write nothing.)
- For the live path, confirm whether the drain should occur in `_attach_executor_tool_data` only, or also be guaranteed by `_finalize_stream` as a backstop when the stream errors before reaching the attach step.
