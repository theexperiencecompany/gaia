## Context

The `unify-voice-mode-with-text-ui-and-gradient` change introduced a single chat surface that flips between text composer and voice control bar without remounting the message renderer. A follow-on fix change attempted to address residual bugs (gradient bootstrap, message ordering, conversation_id auto-redirect, IndexedDB pollution, TTS sanitiser). It was archived without delivering: in practice, five UX-blocking bugs remain.

This design captures the technical decisions for the second fix pass. It replaces the prior fix change wholesale rather than amending it, because the architectural choice driving most of the remaining bugs — keeping voice turns in an in-memory hook with a `convoMessages` prop override — was the wrong abstraction. This change inverts it.

Current state:
- `ChatPage` holds `voiceModeActive` as local React state. Next.js App Router treats `/c` and `/c/:id` as distinct route segments, so the `router.replace` after `conversation_id` discovery remounts `ChatPage` and resets the state.
- `useVoiceMessages` returns `MessageType[]` to `VoiceControlBarContainer` → `VoiceSessionContext` → `ChatPage` → `convoMessages` prop on `ChatRenderer`. The renderer reads from this override OR the chat store, never both.
- `VoiceGradient` uses a ref callback to dodge StrictMode effect double-invoke. The cleanup omits `loseContext()`. There is no `LINK_STATUS` check after relink, so a silently-failed second link results in a no-op draw loop — exactly the dev-only symptom seen.
- `useVoiceSpectrum` exposes `"mic" | "agent-track" | "idle" | "hybrid"` sources. There is no procedural source.
- `useVoiceMessages` creates one `MessageType` per LiveKit transcription stream id. Pauses → multiple finalised streams → multiple bubbles. The seq-counter reconcile closes over a stale `transcriptions` array because the handler is registered with `[room]` deps.

## Goals / Non-Goals

**Goals:**

- Voice mode state survives the `/c → /c/:id` redirect.
- Text history remains visible when voice mode is activated mid-conversation.
- A user who pauses mid-thought sees a single bubble with paragraph breaks.
- Bot turns sequence after user turns, deterministically.
- The gradient renders reliably in `nx dev web` (StrictMode + Turbopack HMR).
- The "Preparing voice mode" state has a visible "vibrating then settling" gradient that pairs with the existing chip text.
- No backend changes. No new dependencies. No new third-party APIs.

**Non-Goals:**

- Reworking the LiveKit worker dispatch / room negotiation. The prior change's audit concluded current defaults are correct for prod; dev non-determinism is in the FE layer.
- Persisting voice-mode-active state across browser refresh. Voice mode is an interaction-time mode; on refresh the user lands in text mode by default.
- Migrating the TTS sanitizer. Already done in the prior change.
- A new spectrum component. The existing `useVoiceSpectrum` is extended with a new source, not replaced.
- Mobile (`apps/mobile`) parity. Voice mode is web-only for now.

## Decisions

### Decision 1: Lift `voiceModeActive` to a Zustand store, not `window.history.replaceState`

We keep the existing `router.replace("/c/:id")` call. Replacing it with `window.history.replaceState` would update the URL without triggering Next navigation, but `useParams()` would not refresh, requiring us to also drive `convoIdParam` from a manual store — a deeper invasive change with no real upside.

A new `voiceModeStore` (Zustand, in-memory, not persisted) holds:

```
{
  voiceModeActive: boolean
  discoveredConversationId: string | null
  enterVoiceMode: () => void
  exitVoiceMode: () => void
  setDiscoveredConversationId: (id: string | null) => void
}
```

`ChatPage` reads `voiceModeActive` via a selector. Because the store survives the page remount caused by `router.replace`, the voice mode container re-renders on the new `/c/:id` route with the active session intact.

**Alternative considered:** Move the entire voice session (Room + state) to a global provider above the route boundary. Rejected: too invasive and creates a global mount that would keep LiveKit objects alive longer than necessary.

### Decision 2: Voice turns write to `chatStore`, not via a `convoMessages` override prop

The `convoMessages` prop on `ChatRenderer` was introduced to keep voice turns in an in-memory hook. This is what causes text history to be hidden when voice mode toggles on, and the duplicate-flash after hang-up sync.

Inversion: `useVoiceMessages` becomes a side-effect hook (not a return-value hook). It subscribes to the LiveKit bot stream and user transcriptions, and **dispatches updates into `chatStore`** for the current conversation id. The chat store already supports incremental message updates (it's how text-mode streaming works) — voice mode uses the same plumbing.

```
Before:                          After:
useVoiceMessages → MessageType[] useVoiceMessages → void (writes to store)
       ↓                                ↓
VoiceSessionContext.voiceMessages       chatStore (single source of truth)
       ↓                                ↓
ChatPage → convoMessages prop           ChatRenderer (reads store as always)
       ↓
ChatRenderer (override or store)
```

Voice turns use a stable `message_id`:
- User group: deterministic id derived from the LiveKit stream id of the FIRST transcription in the group, plus a "user-group-" prefix.
- Bot turn: prefer the `message_id` emitted in the bot stream (already part of the event); fall back to a deterministic local id reconciled on `syncSingleConversation`.

On hang-up, `syncSingleConversation` pulls the server canonical messages; reconciliation by `message_id` produces no duplicate flash because the canonical version overwrites in place.

**Alternative considered:** Keep the override prop but merge `[...textMessages, ...voiceMessages]` in `ChatRenderer`. Rejected: still two stores, still a flash window during sync; chosen approach has a single source of truth.

### Decision 3: User transcription grouping with `<NEW_MESSAGE_BREAK>`, reusing text-mode infrastructure

A "user group" starts on the first transcription seen after the most recent bot turn closure. Subsequent transcriptions append to the group's `response` string with `<NEW_MESSAGE_BREAK>` separators. When a bot turn starts, the active group is "closed" — the bot turn's seq sits after the group's seq, and the next transcription starts a fresh group.

Rendering: `splitMessageByBreaks` (already used by `TextBubble.tsx:620`) splits on the same token. We do not need a new util.

User-message rendering in `ChatBubbleUser` currently treats `text` as a single string. We have two options:
- (a) Keep `ChatBubbleUser` rendering one bubble per `MessageType`, but inside it, call `splitMessageByBreaks(text)` and render each split as a separate `<div>` inside the bubble with whitespace preserved. The bubble container stays single.
- (b) Render multiple stacked bubbles per `MessageType` like `TextBubble` does for bot messages. Bigger visual change.

We choose (a). The user's described UX is "same message, new line" — a single bubble with paragraph breaks fits that mental model exactly. `ChatBubbleUser` already uses `whitespace-pre-wrap`, so `\n\n` between splits will render visibly.

The seq ordering becomes trivial: user-group.seq is assigned when the group is created; bot turns assigned at start time. Since user groups can only be created when the previous bot turn is closed (or at session start), bot turns always sequence after the user group that triggered them. No race.

**Alternative considered:** Send a `NEW_MESSAGE_BREAK` token from the worker between transcriptions. Rejected: requires backend changes; we want a zero-backend-change pass.

### Decision 4: A `"loading"` spectrum source with procedural low-pass-filtered jitter

`useVoiceSpectrum` adds a new source value. Internal model:

```
loading: {
  // Per-bin random walk, low-pass-filtered for organic feel.
  for bin in bins:
    target[bin] = random() * loadingAmplitude  // refreshes every ~80ms
    current[bin] += (target[bin] - current[bin]) * 0.12  // smoothing
}
```

`loadingAmplitude` is small (0.15-0.30 normalized) so the gradient gently "vibrates" without screaming for attention. When `isConnecting` flips to false, `loadingAmplitude` decays linearly to 0 over ~300ms, then the source switches to `"mic"` or `"agent-track"` per agent state.

The source selection in `VoiceControlBarContainer` becomes:

```
spectrumSource =
  isConnecting ? "loading" :
  agentState === "speaking" && remoteTrack ? "agent-track" :
  agentState === "listening" ? "mic" :
  "idle"
```

**Alternative considered:** Drive the loading state from the shader's `uTime` uniform (e.g., a "loading" branch in the GLSL that ignores spectrum). Rejected: keeps spectrum semantics in one layer; the shader stays oblivious to UI state.

### Decision 5: Gradient `LINK_STATUS` guard + session-key remount

Two complementary safeguards in `VoiceGradient.tsx`:

1. After every `linkProgram` call, check `gl.getProgramParameter(prog, gl.LINK_STATUS)`. On failure: log infolog as `console.warn`, delete the program, recompile shaders, re-link. If the second attempt also fails, fall through to a no-op draw and log an explicit "[VoiceGradient] permanent link failure" so dev users see a clear signal.

2. The caller (`VoiceModeBackground`) passes a `key={voiceSessionId}` prop sourced from `voiceModeStore`. A new id is minted on each `enterVoiceMode()` call. This guarantees:
   - Turbopack HMR that detaches the old gradient gets a brand-new canvas on the next mount, not a re-used canvas with a torn-down GL state.
   - React StrictMode's mount → cleanup → mount pattern stays within the SAME canvas (no remount-by-key triggered), but the LINK_STATUS guard catches the case where shader relink fails on the second attempt.

Together: (1) handles StrictMode silent-failure; (2) handles HMR / mount-state corruption.

**Alternative considered:** Call `loseContext()` in cleanup and accept fresh-context-per-mount. Rejected: comment in current code warns against this; loseContext is intended for explicit teardown, not StrictMode dancing.

## Risks / Trade-offs

- **Risk: voice turns flushed to `chatStore` may collide with server-canonical messages on a slow sync.** Both sides write the same `message_id`. Last writer wins. If the worker's emitted `message_id` matches the server canonical (which it should, since the server is the source of truth for the id), reconciliation is a no-op. → Mitigation: log mismatches; if they appear in practice, add a sync-time `message_id` rewrite (voice turn → server canonical).

- **Risk: a transcription that arrives *after* a bot turn opens (very late STT finalisation) gets grouped into a fresh user group when it semantically belonged to the previous group.** This is the classic "user said something at the very tail of their utterance, the agent had already started preempting." → Mitigation: not catastrophic — the late transcription becomes the first message of the next user group, which is logically correct. The bot's response to the prior utterance still renders correctly.

- **Risk: the LINK_STATUS guard masks a real shader bug that would otherwise be visible after deploy.** → Mitigation: the warn is `console.warn`, not silent; in dev users see it immediately. We do not fall through to "no draw" silently — we explicitly log permanent failure.

- **Trade-off: the `"loading"` spectrum source is procedural, not data-driven.** It does not reflect any real audio. This is a UX hint, not a measurement. We accept this — the alternative would be wiring some other audio source (e.g., a connect-ack ping) just to feed the spectrum, which is far more complex.

- **Trade-off: voice mode state is in-memory only.** A browser refresh during a voice call drops the user out of voice mode. Acceptable — voice mode is a real-time interaction; resuming after refresh is a separate feature.

## Migration Plan

This change touches the FE only and has no DB / API migrations. Deploy in one PR.

Rollback: revert the PR. No data shape changes to undo.

## Open Questions

- **Q1**: Does the LiveKit bot stream's `message_id` actually match what the API persists? If not, we need a reconciliation map in `syncSingleConversation`. → Investigate during task 2; if a mismatch is found, file a backend ticket separately (still no backend change required this round — we can rewrite local ids on sync as a FE-only fix).

- **Q2**: When the user is mid-pause and the bot preempts (preemptive_generation=true), should the bot's response still wait for the user group to close, or render immediately? Current decision: bot turn starts immediately, but its seq is computed against a snapshot of the user group's seq at the moment of the first bot event. The user group, once closed, never reorders. This means the bot bubble will appear *below* the user group as expected, even if more late user transcriptions arrive (those would start a new group below the bot bubble — also logically correct).

- **Q3**: Should the `voiceSessionId` regenerate on every `enterVoiceMode()` even if voice mode is already active? Decision: yes — the only call site is from text mode → voice mode transition, so it's always a fresh session. If we later add a "restart voice session" button, that button will also call `enterVoiceMode()`.
