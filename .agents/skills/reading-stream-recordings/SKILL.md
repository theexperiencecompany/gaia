---
name: reading-stream-recordings
description: Read the frontend's on-disk stream recording to see what the browser actually received and rendered during a chat turn — the raw SSE frames in order plus each tool card's render outcome. Use when a card, bubble split, or approval didn't appear and Mongo/backend logs can't tell you why.
---

# Reading Stream Recordings

Mongo shows the turn *after* it finished. Backend logs show what was *emitted*. Neither tells you what the browser received or what it did with it. The dev web app records both, to disk, on every turn.

Use this the moment a symptom is "the card / bubble / approval didn't show up".

---

## 1. Where it lands

`.agents/recording/stream/<ISO-timestamp>-<rand>.ndjson` at the repo root (gitignored).

One file per page load. One JSON object per line, in the order the browser saw them.

```bash
ls -la .agents/recording/stream/          # newest file = your run
```

Written by `apps/web/src/lib/streamRecordingSink.ts` → `apps/web/src/app/api/dev/stream-recording/route.ts`. Dev only: `NODE_ENV` is inlined at build time, so the client sink and the route are both dead in production.

## 2. Producing one

Nothing to enable. Boot the web app in dev (`mise dev --agent`, see `driving-gaia`), open a chat in a real browser, send a message. Every entry ships automatically, batched every 750 ms and flushed on `pagehide`.

## 3. Schema

Every line is a `StreamLogEntry` (`apps/web/src/lib/streamLogger.ts`):

| Field | Meaning |
|---|---|
| `seq` | Monotonic per page load. Line order == arrival order. |
| `ts` | ISO wall clock. |
| `dtMs` | Milliseconds since the most recent stream start — the turn's own clock. |
| `layer` | `sse` · `ws` · `accumulator` · `store` · `db` · `render` · `lifecycle` |
| `event` | Layer-specific name (see below). |
| `turnKey` / `conversationId` | Turn identity. `turnKey` is `pending:<uuid>` until the identity frame binds a conversation. |
| `detail` | Payload. |

Events that matter:

| `layer` / `event` | What it proves | `detail` |
|---|---|---|
| `lifecycle` / `turn:start` | A turn began, and with which prompt | `{ prompt }` |
| `sse` / `frame` | **A raw frame arrived over the wire.** Recorded in `chatApi.ts` before any parsing or dispatch — the two `fetchEventSource` readers there are the app's only SSE readers, so nothing bypasses this. | `{ raw }` (verbatim SSE data), plus `streamId` on the executor/resume stream |
| `sse` / `event:<type>` | The frame parsed into a known event type and was dispatched | — |
| `accumulator` / `applied:<type>` | It reached the turn accumulator | — |
| `store` / `flush` | The turn record was written to the Zustand store | — |
| `render` / `tool:<name>:<outcome>` | **What the bubble did with a `tool_data` entry** | `{ messageId, index, outcome }` |
| `lifecycle` / `turn:close`, `turn:end` | Terminal paths | — |

`render` outcomes (`apps/web/.../TextBubble/useToolRenderAudit.ts`):

- `rendered` — handed to a registered `TOOL_RENDERERS` card
- `unified-thread` — `tool_calls_data` / `subagent_group`, folded into `UnifiedToolThread` by design
- `no-renderer` — **no `TOOL_RENDERERS` entry; `renderTool` returned null and nothing appeared**
- `empty-data` — entry arrived with a null payload; `TextBubble` bails before rendering

## 4. Grep recipes

```bash
F=$(ls -1 .agents/recording/stream/*.ndjson | tail -1)

# What prompt produced this file?
grep '"event":"turn:start"' "$F"

# Did a given frame type ever arrive? (searches the RAW wire payload)
grep '"layer":"sse","event":"frame"' "$F" | grep integration_connection_required

# Every tool card outcome for the turn
grep '"layer":"render"' "$F"

# Anything the renderer dropped
grep -E '"tool:[a-z_]+:(no-renderer|empty-data)"' "$F"

# Contract violations the frontend saw (malformed frames, ghost closes, errors)
grep '"ERROR:' "$F"

# Bubble splits — the break token lives inside `response` frames
grep '"event":"frame"' "$F" | grep NEW_MESSAGE_BREAK

# One turn out of a busy file
grep '"conversationId":"<conversation-id>"' "$F"
```

## 5. Telling the four failure modes apart

Symptom: "X should have shown up and didn't." Run these in order and stop at the first `no`.

| # | Check | `no` means |
|---|---|---|
| 1 | `grep '"event":"frame"' $F \| grep <X>` — is X in a raw payload? | **(a) the backend never emitted it.** Go to the backend: `reading-gaia-logs`, and check the emit site. Do not touch the frontend. |
| 2 | Is there a matching `"event":"event:<type>"` line right after that frame? | **(b) it arrived but did not parse/dispatch.** Look for a neighbouring `ERROR:malformed-frame`, or a schema mismatch in `libs/shared/ts/src/chat/streaming.ts`. |
| 3 | For a `tool_data` frame: is there a `"layer":"render"` line for that tool name, with outcome `rendered`? | **(c) the renderer dropped it.** Outcome `no-renderer` → the `tool_name` is missing from `TOOL_RENDERERS`. Outcome `empty-data` → the payload was null. No `render` line at all → the entry never reached `TextBubble`; check the accumulator/store lines above it. |
| 4 | All three are `yes` | **(d) it rendered but you couldn't see it.** The log is done helping — go to the DOM. Query the page for the card (chrome-devtools MCP `take_snapshot` / `evaluate_script`) and check scroll position, `overflow`, and the bubble-vs-card nesting trap in `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`. |

## 6. What this does NOT tell you

- **Whether a rendered node was visible.** `rendered` means the renderer ran, not that pixels landed. Step 4 above is a DOM job, not a log job.
- **Re-render counts.** `render` outcomes are logged once per `(messageId, index, toolName)`, so the file records what happened to a frame, not how many times React re-ran.
- **Anything outside the browser tab that wrote the file.** Two tabs produce two files.
