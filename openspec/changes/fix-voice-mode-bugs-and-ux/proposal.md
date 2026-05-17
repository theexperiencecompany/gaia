## Why

The unified voice mode (shipped by `unify-voice-mode-with-text-ui-and-gradient`) and its first fix pass left five concrete bugs that block day-to-day use:

- The WebGL2 gradient renders only after a production build, never in `nx dev web`.
- Activating voice mode from a fresh `/c` triggers a `router.replace("/c/:id")` that **remounts** the page component (the two route segments are distinct in App Router), wiping the local `voiceModeActive` state and killing voice mode mid-session.
- A user who pauses mid-thought produces a separate user bubble per finalised LiveKit transcription, instead of one bubble with paragraph breaks. The bot turn then renders **above** all user bubbles because the seq-counter reconcile closes over a stale `transcriptions` array (handler is registered with deps `[room]` only).
- The "Preparing voice mode" connection state shows a chip and a flat gradient — no visual feedback that the system is "working" then "ready to listen."
- Voice and text turns live in two separate stores: text in `chatStore`/IndexedDB, voice in `useVoiceMessages` in-memory. When voice mode toggles on, the `convoMessages` prop override hides text history entirely. After hang-up, the in-memory voice turns and the server-canonical sync briefly overlap, producing a flash of duplicate messages (notably when the server response contains emoji that the TTS-sanitised voice response did not).

These are user-facing and block both internal demos and external use.

## What Changes

- **Voice mode state persistence:** Lift `voiceModeActive` and the discovered conversation id out of `ChatPage`'s local state into a new Zustand `voiceModeStore`. The store survives Next.js route remounts, so the `/c → /c/:id` redirect no longer kills voice mode. Replace `setVoiceModeActive(boolean)` call sites with store actions; ChatPage subscribes to the store.

- **Unified message store (BREAKING for the voice-mode internal contract):** Voice turns from `useVoiceMessages` no longer flow through a `convoMessages` prop override. Instead, voice turns are written into the same `chatStore` text mode uses, with a stable `message_id` derived from the LiveKit bot stream (or a deterministic local id reconciled on sync). Remove the `convoMessages?: MessageType[]` override prop from `ChatRenderer`, `ChatSection`, `ChatWithMessages`, and `ChatPage`. `VoiceModeChatBody` collapses into `ChatWithMessages`. After hang-up, `syncSingleConversation` reconciles by `message_id` — no duplicate flash.

- **User transcription grouping (NEW_MESSAGE_BREAK):** Consecutive user transcriptions between bot turns are merged into a **single** `MessageType` whose `response` joins each transcription with `<NEW_MESSAGE_BREAK>` (reusing `splitMessageByBreaks` from `libs/shared/ts/src/utils/messageBreakUtils.ts`). When a bot turn starts, the current user group is "closed"; the next user transcription opens a new group. The bot turn is sequenced after the closed group, fixing the bot-above-user ordering bug as a side effect.

- **Loading-state procedural spectrum:** Add a `"loading"` source to `useVoiceSpectrum` that drives the spectrum bins with a low-pass-filtered random walk (organic jitter, not buzzy noise) while `isConnecting` is true. When `isConnecting` flips to false, fade the loading spectrum to zero over ~300ms, then hand off to `"mic"`/`"agent-track"`. The gradient now "vibrates" during prepare and visibly "settles" when listening starts — pairing the visual with the existing chip text.

- **Gradient dev-mode robustness:** Add a `gl.getProgramParameter(prog, gl.LINK_STATUS)` check after every (re)link in `VoiceGradient.tsx` with a `console.warn` and a recovery path (delete program, recompile, re-link). Add a `key` prop on the gradient bound to the voice session id so Turbopack HMR and React 19 StrictMode ref-callback double-invokes are guaranteed to mount a fresh canvas per session.

## Capabilities

### New Capabilities

<!-- None — this change extends the existing voice-mode capability. -->

### Modified Capabilities

- `voice-mode`: Adds requirements for voice mode state persistence across route navigation, single-store unified message rendering, user transcription grouping via NEW_MESSAGE_BREAK, loading-state procedural spectrum, and gradient init diagnostics. Removes the `convoMessages` prop-override contract (voice turns now flow through `chatStore` like text turns).

## Impact

- **Frontend (`apps/web`)**
  - NEW: `src/stores/voiceModeStore.ts` — Zustand store for `voiceModeActive`, `discoveredConversationId`, and any cross-route voice session state. Persists nothing (in-memory only).
  - `src/stores/chatStore.ts` — accepts voice turn upserts via a new action (or reuses existing message upsert with a `source: "voice"` hint if useful for analytics).
  - `src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts` — rewrites internal model to user-group + bot-turn pairs joined by NEW_MESSAGE_BREAK; writes turns to `chatStore` instead of returning a `MessageType[]`.
  - `src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts` — adds `"loading"` source with procedural jitter + fade-out on transition.
  - `src/features/chat/components/voice-agent/VoiceControlBarContainer.tsx` — reads `voiceModeStore`; replaces the prop-driven `voiceMessages` exposure with direct chatStore writes; uses `"loading"` spectrum source while `isConnecting`.
  - `src/features/chat/components/voice-agent/VoiceGradient.tsx` — LINK_STATUS guard + recovery; receives `key={voiceSessionId}` from caller.
  - `src/features/chat/components/voice-agent/VoiceModeBackground.tsx` — passes the session key into `VoiceGradient`.
  - `src/features/chat/components/voice-agent/VoiceSessionContext.tsx` — drops `voiceMessages` from the context value (no longer needed; chatStore is the source of truth).
  - `src/features/chat/components/interface/ChatPage.tsx` — drops `voiceModeActive` local state in favour of the store; drops `VoiceModeChatBody`; uses plain `ChatWithMessages` for both modes.
  - `src/features/chat/components/interface/layouts/ChatWithMessages.tsx`, `sections/ChatSection.tsx`, `ChatRenderer.tsx` — remove the `convoMessages` prop override; ChatRenderer reads only from `useConversation()`.
- **Backend:** No changes. The voice worker's text streams (`response`, `tool_data`, `follow_up_actions`, `conversation_id`, `conversation_description`) are unchanged. Server-side message canonicalisation is unchanged.
- **Database / API schema:** No changes. No new third-party dependencies.
