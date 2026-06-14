## 1. Drain ownership (backend) — Option A: in-process, no Redis checkpoint

> Scope decision: descoped the Redis durable checkpoint + crash-recovery sweep (would need its own re-drive mechanism and is beyond the reported cancellation failures). Cancellation handlers run in the same process as the in-memory collector, so a collector read is sufficient and reliable.

- [x] 1.1 ~~Redis checkpoint in `redis_writer.py`~~ — descoped (Option A). The in-memory `tool_event_collector` remains the single in-process record; cancellation handlers run in-process and can read it directly.
- [x] 1.2 ~~`update_progress` merge for executor tool_data~~ — descoped (Option A). Executor events are raw and only become `{"tool_data": [...]}` via `absorb_collector_event`; no Redis-shape merge needed.
- [x] 1.3 ~~`recover_stream_state` checkpoint read~~ — descoped (Option A). No cross-process recovery; in-process drain covers all cancellation paths.
- [x] 1.4 Confirm `drain_executor_tool_data` is the single drain implementation used by every terminal handler, and that it is a non-destructive read — so idempotency is guaranteed by **single-ownership** (live → comms attaches; queued/workflow → executor self-persists), not by emptying the collector.

## 2. Drain-and-attach on live cancellation (backend)

- [x] 2.1 In `stream.py` `_attach_executor_tool_data`, remove the `if state.is_cancelled: return` early exit; on cancellation, still drain executor tool_data and `$push` the cards onto the saved comms message (`messages.$.tool_data`).
- [x] 2.2 Preserve idempotency via single-ownership: for live streams only the comms `_attach_executor_tool_data` persists executor tool_data (the executor's own `_finalize_executor_run` self-persists only for `is_queued`/`workflow_id`), so the `$push` runs exactly once per stream. `drain_executor_tool_data` is a non-destructive read; no card-identity dedup layer is added.
- [x] 2.3 Verify `_finalize_stream` acts as a backstop: if the stream errored before reaching the attach step, drain + persist any checkpointed executor tool_data there (resolve Open Question on placement).

## 3. Drain-and-persist on command + queued cancellation (backend)

- [x] 3.1 In `executor_runner.py` `_finalize_executor_run`, stop skipping persistence when `was_cancelled`; drain executor tool_data and route it to the save path for queued/workflow cancellations (live stays owned by the comms path — single-ownership).
- [x] 3.2 `_persist_cancelled_executor_result` writes a **cards-only** message (`response=""`, drained tool_data) keyed on `message_id == task_id`; skips the write when zero cards; no comms re-narration, follow-ups, reply-quote, or proactive notification — mirrors the cards-only placeholder the user already saw.
- [x] 3.3 No WebSocket re-broadcast on cancel — the cards were already streamed; durability is the MongoDB write, and the frontend's existing conversation sync reconciles it with the placeholder by `task_id`. (Revises the original WS-push design per review.)
- [x] 3.4 The cancellation persist (drain) runs in the `was_cancelled` branch, which precedes the `if is_queued: teardown_executor_capture(...)` call — drain-before-teardown holds.
- [x] 3.5 Happy queued path (`_deliver_bg_notification`) also keys its saved message on `message_id == task_id` (new `message_id` param passed from `_dispatch_executor_result` for `is_queued`), so a missed WebSocket push can't leave a lingering duplicate placeholder — sync reconciles by id.

## 4. Field-preserving client sync merge (frontend)

- [x] 4.1 In `syncService.ts` `mergeMessageLists`, added `withPreservedToolData` — when overwriting an existing local message with a remote one, preserves a non-empty local `tool_data` if the remote copy's `tool_data` is empty/missing; "remote wins" for all other fields.
- [x] 4.2 Same guard applied to the `status === "sending"` cleanup branch so an aborted-then-saved message keeps its locally-retained cards.

## 5. Persist queued live placeholder (frontend)

- [x] 5.1 In `useExecutorStream.ts`, write the placeholder (keyed by `task_id`) and its accumulating `tool_data` to IndexedDB via `db.putMessage` on creation and on every `tool_data` / `tool_output` event (and on close), not only to the Zustand store.
- [x] 5.2 `useBgMessageWebSocket` now uses `db.replaceMessage(task_id, finalMessage)` when `task_id` is present, atomically removing the persisted placeholder and persisting the final `message_id` message; the field-preserving merge (4.1) keeps live-shown cards if the backend copy lags.

## 6. Verification

- [ ] 6.1 (manual QA — needs live app) Verify all three stop paths preserve cards after refresh: composer Stop, `cancel_executor` command, and cancelling a queued background task.
- [ ] 6.2 (manual QA — needs live app) Verify a successful queued run still renders cards and that WebSocket-failure (simulated) still surfaces the message via sync.
- [ ] 6.3 (manual QA — needs live app) Verify no duplicate cards on a normally-completing live turn (happy-path attach + any backstop drain).
- [x] 6.4 Backend mypy + ruff clean on changed files; `nx type-check web` passes; Biome reports 0 errors on changed files (the remaining `syncSingleConversation` complexity warning and the `jsonFormatters.ts` error are pre-existing, unrelated to this change).
