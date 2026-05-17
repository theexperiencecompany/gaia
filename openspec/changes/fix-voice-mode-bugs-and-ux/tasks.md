## 1. Voice mode state store (Zustand)

- [x] 1.1 Create `apps/web/src/stores/voiceModeStore.ts` — Zustand store with `voiceModeActive: boolean`, `voiceSessionId: string | null`, `discoveredConversationId: string | null`, and actions `enterVoiceMode()` (sets active=true + mints a new sessionId via `crypto.randomUUID()`), `exitVoiceMode()` (resets active=false, clears sessionId), `setDiscoveredConversationId(id)`. Wrap with `devtools`. Do NOT persist (in-memory only).
- [x] 1.2 Export named selector hooks for the common reads (`useVoiceModeActive`, `useVoiceSessionId`, `useDiscoveredConversationId`) using `useShallow` where applicable.
- [x] 1.3 In `apps/web/src/features/chat/components/interface/ChatPage.tsx`, delete the local `useState(voiceModeActive)` (line 74). Replace reads with `useVoiceModeActive()` from the store. Replace `setVoiceModeActive(true)` in `composerProps.voiceModeActive` with `useVoiceModeStore.getState().enterVoiceMode()`. Replace `setVoiceModeActive(false)` in `handleEndVoiceCall` with `exitVoiceMode()`.
- [x] 1.4 In `apps/web/src/features/chat/components/voice-agent/VoiceControlBarContainer.tsx`, replace the local `useState(discoveredConversationId)` (line 112) with a setter from the store. Keep the same auto-redirect effect (lines 131-136) — but read the value from the store.
- [ ] 1.5 Verify the redirect flow: start voice mode on `/c`, observe `router.replace("/c/<id>")` fires, the new route mounts, and `useVoiceModeActive()` is still `true` (because the store survives the page remount). — **Manual verification, deferred to user.**

## 2. Unified message store (voice writes to chatStore)

- [x] 2.1 Audit `apps/web/src/stores/chatStore.ts` for the message-upsert action used by text-mode streaming. Identify the public action signature (likely `upsertMessage` or similar). If a single-message-upsert action does not exist, add one (do not introduce a voice-specific path — voice and text use the same mutation). — `addOrUpdateMessage(message: IMessage)` already exists (chatStore.ts:104). Sorts by createdAt. No new action needed.
- [x] 2.2 Rewrite `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts` from a return-value hook into a side-effect hook:
  - Accept a `conversationId: string | null` argument.
  - Subscribe to the LiveKit bot stream and user transcriptions as before.
  - On each user transcription update, compute the current user-group MessageType and call the chatStore upsert action.
  - On each bot turn update (`response`, `tool_data`, `follow_up_actions`, `main_response_complete`), call the chatStore upsert action with the bot MessageType.
  - Return `void` (or expose internal status if needed for debugging).
  - User-group `message_id`: `voice-user-${firstTranscriptionStreamId}` (stable across appends).
  - Bot turn `message_id`: prefer the id from the bot stream event if present; otherwise `voice-bot-${roomSid}-${turnIndex}` (deterministic so sync can reconcile). — Writes use `optimistic: true` so `mergeMessageLists` cleans them up during post-call `syncSingleConversation`.
- [x] 2.3 In `VoiceControlBarContainer.tsx`, update the `useVoiceMessages()` call site: pass `conversationId` and drop the return-value assignment to `voiceMessages`. Remove `voiceMessages` from `VoiceSessionValue` (`VoiceSessionContext.tsx:14-21`) — it's no longer needed.
- [x] 2.4 In `apps/web/src/features/chat/components/interface/ChatRenderer.tsx`, delete the `convoMessages?: MessageType[]` prop (lines 30-32, 35-38). The renderer reads only from `useConversation()`.
- [x] 2.5 In `apps/web/src/features/chat/components/interface/sections/ChatSection.tsx`, delete the `convoMessages` prop and stop forwarding it.
- [x] 2.6 In `apps/web/src/features/chat/components/interface/layouts/ChatWithMessages.tsx`, delete the `convoMessages?: MessageType[]` prop (lines 22-27, 36, 47).
- [x] 2.7 In `ChatPage.tsx`, delete the `VoiceModeChatBody` helper (lines 41-71). Both modes now use plain `<ChatWithMessages>` directly. The voice-mode branch (lines 232-257) still renders `<VoiceControlBarContainer>` and `<VoiceModeBackground>`, but the chat body is just `<ChatWithMessages bottomBar={<VoiceControlBarSlot/>} />` (no `convoMessages` prop).
- [ ] 2.8 Verify text history persists when entering voice mode: open `/c/<id>` with existing messages, click voice mode, confirm prior messages remain visible. Confirm new voice turns appear below them in chronological order. — **Manual verification, deferred to user.**
- [ ] 2.9 Verify no duplicate-flash on hang-up: run a voice turn that produces a response with emoji (which the local sanitized voice turn omits). End the call, observe `syncSingleConversation` runs, and confirm the on-screen bubble is the server canonical (with emoji), with no duplicate bubble flashed during the swap. — **Manual verification, deferred to user.**

## 3. User transcription grouping with NEW_MESSAGE_BREAK

- [x] 3.1 In `useVoiceMessages.ts`, replace the per-transcription `userMessagesSeq` model (current lines 171-196) with a "current user group" model. Maintain a ref `currentUserGroupRef: { startStreamId: string; transcriptionTexts: Map<string, string> } | null`.
- [x] 3.2 On every transcription update (effect on `[transcriptions]`):
  - Filter to local-participant transcriptions with non-empty text.
  - If `activeTurnRef.current !== null` (bot is mid-turn): do NOT append to the active user group. Start a new group from the next transcription seen.
  - Else: if `currentUserGroupRef.current === null`, create a new group with the first transcription's stream id. Add/update the transcription text in the group's map (keyed by stream id, so updates-in-place replace prior text for that id).
  - Build the joined response string: `Array.from(group.transcriptionTexts.values()).join("<NEW_MESSAGE_BREAK>")`.
  - Upsert the user MessageType into chatStore with `message_id: \`voice-user-${group.startStreamId}\``.
- [x] 3.3 In the bot-stream handler in `useVoiceMessages.ts`, when a new bot turn starts (`activeTurnRef.current === null`): close the current user group by setting `currentUserGroupRef.current = null`. Then proceed with the bot turn creation as before. Use a monotonic counter for the bot's seq IF the chatStore needs explicit ordering, otherwise rely on insertion order.
- [x] 3.4 In `apps/web/src/features/chat/components/bubbles/user/ChatBubbleUser.tsx`, update the text rendering path: when `text` contains `<NEW_MESSAGE_BREAK>`, call `splitMessageByBreaks(text)` and render each split as a separate paragraph inside the SAME bubble (e.g., one `<div>` per split, separated by margin or by `\n\n` since the bubble already uses `whitespace-pre-wrap`). Do NOT render multiple bubbles per `MessageType`.
- [x] 3.5 Update the avatar/timestamp/actions footer of `ChatBubbleUser` to use the joined text (with breaks replaced by `\n\n`) when generating copy text — reuse the pattern from `ChatBubble_Actions.tsx:54`.
- [x] 3.6 Remove the seq-counter logic from `useVoiceMessages.ts` (lines 15-16, 50, 55-62, all `seq` fields). Ordering is now structural — bot turns can only start after a user group is implicitly closed by activeTurnRef being null, and they sequence into chatStore in insertion order.
- [ ] 3.7 Verify pause grouping: speak "hello", pause 2s, speak "how are you", pause 2s, speak "tell me a joke". Confirm one user bubble appears containing all three lines separated by paragraph breaks. Then verify the next bot response renders below the bubble, and a follow-up user utterance starts a new bubble. — **Manual verification, deferred to user.**

## 4. Loading-state procedural spectrum

- [x] 4.1 In `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts`, add a new source value `"loading"` to the `source` parameter type union. Add an internal `loadingAmplitudeRef = useRef(1)` and a `loadingDecayingRef = useRef(false)`.
- [x] 4.2 Implement the loading-source branch in the per-frame update loop:
  - Maintain per-bin target values that refresh every ~80ms (track elapsed time in the RAF loop): `target[i] = Math.random() * 0.30`.
  - Smooth current toward target: `current[i] += (target[i] - current[i]) * 0.12`.
  - Multiply by `loadingAmplitudeRef.current` so the fade-out applies uniformly.
- [x] 4.3 Add a public `decayLoading()` method on the hook return value. When called: set `loadingDecayingRef.current = true`. In the RAF loop, when decaying: `loadingAmplitudeRef.current = Math.max(0, loadingAmplitudeRef.current - dt / 300)`. When it reaches 0, allow the caller to switch the `source` prop to the next state.
- [x] 4.4 In `VoiceControlBarContainer.tsx`, update the `spectrumSource` selection (lines 156-161):
  ```
  spectrumSource =
    isConnecting ? "loading" :
    agentState === "speaking" && remoteTrack ? "agent-track" :
    agentState === "listening" ? "mic" :
    "idle"
  ```
- [x] 4.5 In `VoiceControlBarContainer.tsx`, detect the `isConnecting: true → false` transition with a ref+effect. On transition, call `voice.decayLoading()` so the procedural source fades smoothly into the listening source.
- [ ] 4.6 Manual verification: enter voice mode, observe waveforms vibrate gently while "Preparing voice mode" chip is visible. When agent transitions to listening, chip dismisses and waves smoothly flatten/transition to mic-driven response. — **Manual verification, deferred to user.**

## 5. Gradient init diagnostic + per-session canvas remount

- [x] 5.1 In `apps/web/src/features/chat/components/voice-agent/VoiceGradient.tsx`, after both `linkProgram(gl, vert, wfrag)` and `linkProgram(gl, vert, bfrag)` calls (around lines 522-523), add a `LINK_STATUS` check: `if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.warn("[VoiceGradient] link failed:", gl.getProgramInfoLog(prog)); gl.deleteProgram(prog); /* recompile + relink one retry */ }`. If the retry also fails, `console.error("[VoiceGradient] permanent link failure")` and return null from `initGL` (caller's cleanup ref stays null; no RAF loop).
- [x] 5.2 Extract the compile+link sequence into a small `buildProgram(gl, frag)` helper so the retry path can re-run it cleanly. Keep `compileShader`/`linkProgram` helpers as-is.
- [x] 5.3 In `apps/web/src/features/chat/components/voice-agent/VoiceModeBackground.tsx`, read `voiceSessionId` from `useVoiceModeStore`. Pass `key={voiceSessionId ?? "no-session"}` to the inner gradient render so a new sessionId forces a fresh canvas mount.
- [ ] 5.4 Verify dev-mode rendering: `nx dev web` → activate voice mode from `/c`. Confirm the gradient renders immediately (no need for a page refresh, no `pnpm build` required). Toggle voice mode off and on; confirm each session gets a fresh canvas. — **Manual verification, deferred to user.**
- [ ] 5.5 Verify dev-mode survives a hot reload: with voice mode active, edit `VoiceGradient.tsx` (e.g., change a comment) to trigger Turbopack HMR. Confirm the gradient either continues to render or warns explicitly in console — no silent black canvas. — **Manual verification, deferred to user.**

## 6. Cleanup and verification

- [x] 6.1 Remove dead code: `VoiceModeChatBody` (deleted in task 2.7), `convoMessages` props (deleted in 2.4-2.6), `voiceMessages` field on `VoiceSessionValue` (deleted in 2.3), seq counter and reconcile fn in `useVoiceMessages.ts` (deleted in 3.6).
- [x] 6.2 Search for any remaining references to the removed APIs: `grep -rn "convoMessages" apps/web/src/features/chat | grep -v node_modules` and `grep -rn "voiceMessages" apps/web/src/features/chat | grep -v node_modules` should return only call sites that are explicitly desired (e.g., chatStore action names that are renamed). — Verified: all remaining `convoMessages` refs are legitimate `useConversation()` consumers; no `voiceMessages` refs remain.
- [x] 6.3 Run `nx run-many -t type-check --projects=web,desktop` — must pass clean. — Both projects clean.
- [x] 6.4 Run `nx run-many -t lint --projects=web,desktop` — must pass clean. — Both clean (fixed a pre-existing unrelated import-order issue in `ComposerRight.tsx` via Biome safe autofix to unblock).
- [ ] 6.5 Manual end-to-end on `nx dev web`: — **Manual verification, deferred to user.**
  - [ ] 6.5.1 Activate voice mode from `/c` (no id). Confirm gradient renders, vibrates during prepare, settles when listening starts.
  - [ ] 6.5.2 Speak; observe redirect to `/c/<id>`; confirm voice mode remains active, gradient still visible, chat history still rendered.
  - [ ] 6.5.3 Pause-pause-pause through one utterance; confirm one user bubble with paragraph breaks; bot turn below it.
  - [ ] 6.5.4 End call; confirm voice control bar replaced by composer, all turns remain in the list, no duplicate flash even when the bot response includes emoji.
  - [ ] 6.5.5 Activate voice mode again in the same `/c/<id>`; confirm prior text+voice history remains visible; new turns append below.
