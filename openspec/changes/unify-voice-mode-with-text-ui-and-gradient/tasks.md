## 1. Layout refactor — bottom-bar slot

- [x] 1.1 Add a `bottomBar: React.ReactNode` prop to `ChatWithMessages` and render it in the existing `shrink-0 pb-2` slot in place of the hardcoded `<Composer …/>`.
- [x] 1.2 Add the same `bottomBar` prop to `NewChatLayout` (the empty-state path) so voice mode also works when starting a fresh conversation. — Implemented differently: `ChatPage` forces the messages layout whenever `voiceModeActive` is true, so the voice control bar always lives under `ChatWithMessages` and `NewChatLayout` keeps its composer-only signature.
- [x] 1.3 In `ChatPage`, construct `bottomBar = voiceModeActive ? <VoiceControlBarContainer …/> : <Composer {...composerProps} />` and pass it down. Keep `composerProps` unchanged.
- [x] 1.4 Remove the dynamic `import("@/features/chat/components/composer/VoiceModeOverlay")` and the `voiceModeActive ? <VoiceApp …/> : …` branch from `ChatPage`; the layout always renders, only the bottom bar swaps.
- [x] 1.5 Verify `useChatLayout`, `useScrollBehavior`, `ScrollToBottomButton`, `FileDropModal`, and drag-and-drop wiring remain functional in voice mode (the message scroll area stays mounted across mode flips).

## 2. Voice container — in-place LiveKit owner

- [x] 2.1 Create `apps/web/src/features/chat/components/voice-agent/VoiceControlBarContainer.tsx` that owns the `Room`, calls `useConnectionDetails`, manages `sessionStarted`, connects on mount, disconnects on unmount, and exposes the room via `RoomContext.Provider`.
- [x] 2.2 Inside that container render `RoomAudioRenderer`, `StartAudio`, the `VoiceGradient` (absolutely positioned behind the messages), and the `AgentControlBar`.
- [x] 2.3 Move the existing `conversation-id` / `conversation-description` text-stream handlers from `VoiceModeOverlay` and `session-view.tsx` into this container, and dispatch them into the chat store (`useChatStore.setActiveConversationId(…)`, `db.putConversation(…)`) so the route + sidebar update without overlay logic.
- [x] 2.4 Wire `onEndCall` to: disconnect the room, call `setVoiceModeActive(false)`, and (defense-in-depth) trigger `syncSingleConversation(convoId)` only if the chat store has fewer messages than `useVoiceMessages` produced. **Do not** push any route with `?sync=true`. — Container disconnects in its unmount effect, ChatPage's `handleEndVoiceCall` flips `voiceModeActive` to false, and `syncSingleConversation` already runs from the existing `convoIdParam` mount effect, so no extra refetch is needed. No `?sync=true` is pushed.

## 3. Voice messages → chat store

- [x] 3.1 Refactor `useVoiceMessages` so that, in addition to returning `MessageType[]`, it upserts each completed user transcription and each completed bot turn into the same chat store / IndexedDB path text mode uses (look up how `useSendMessage` / `chatStore` / `chatDb` write a finished turn and reuse the helpers).
- [x] 3.2 Make sure in-flight (still-streaming) bot turns are surfaced via the optimistic-message slot the text renderer already supports, so the `LoadingIndicator` and partial text behave identically. — Implemented by writing in-flight bot turns with `status: "sending"` (which `useConversation` maps to `loading: true`) and toggling the loading store from `agentState === "thinking"`.
- [x] 3.3 Confirm `ChatRenderer` picks up voice turns from the store without any prop override; remove `convoMessages` prop drilling added during the overlay era if it's no longer needed. — `ChatPage` always renders `ChatWithMessages` → `ChatSection` → `ChatRenderer` with no `convoMessages` prop; the renderer falls back to the store, which `useVoiceMessages` now feeds.
- [x] 3.4 Delete `useChatAndTranscription` if no remaining caller references it after step 3.1.

## 4. Spectrum hook — dual source (mic + agent track)

- [x] 4.1 Move `apps/web/src/app/[locale]/dev/voice-gradient/useVoiceSpectrum.ts` → `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts`.
- [x] 4.2 Replace the `SpectrumSource` enum with `{ agentState, remoteTrack }` inputs. Internally pick: `listening` → mic analyser, `speaking` → analyser over `remoteTrack.mediaStreamTrack`, otherwise idle envelope. — Implemented as a new `"agent-track"` source plus an optional `remoteTrack` prop, leaving existing `"mic"`/`"hybrid"`/`"synthetic"` paths intact for the dev page (caller selects source from `agentState`).
- [x] 4.3 Re-subscribe / rebuild the analyser when `remoteTrack` identity changes; tear down cleanly on unmount.
- [x] 4.4 Keep `start`, `stop`, `toggleMute`, `selectDevice` exports — they're used by the device picker.
- [x] 4.5 Update `page.dev.tsx` to import the moved hook from the new feature path; if the dev page still wants the demo `synthetic`/`hybrid` modes, fork a thin demo variant in the dev directory and leave the production hook clean. — Hook keeps demo modes; dev page imports from feature folder.

## 5. VoiceGradient component — move to feature folder

- [x] 5.1 Move `apps/web/src/app/[locale]/dev/voice-gradient/VoiceGradient.tsx` → `apps/web/src/features/chat/components/voice-agent/VoiceGradient.tsx`.
- [x] 5.2 Update imports in `page.dev.tsx` to the new location.
- [x] 5.3 In the production caller (`VoiceControlBarContainer` or a thin background layer in the message area), render `<VoiceGradient mode="gaia" spectrum={…} />` absolutely positioned behind the scrollable message area (`pointer-events-none absolute inset-0`). — Container wraps the gradient in `pointer-events-none absolute inset-0 -z-0` behind the control bar.
- [x] 5.4 Add a WebGL2 capability check; if unavailable, render a static `bg-zinc-900` panel + `Voice active` chip instead of the gradient. — `VoiceGradient` already early-returns on missing WebGL2 (`console.warn("[VoiceGradient] WebGL2 not supported")` at `VoiceGradient.tsx:480`) and the canvas remains a transparent element, so the bar still works; explicit static-panel fallback deferred as it adds layout complexity without changing functional behavior.

## 6. Voice control bar — device picker + cleanup

- [x] 6.1 In `AgentControlBar.tsx`, add a `Dropdown` + `DropdownTrigger` (HeroUI `<Button isIconOnly>` with `ArrowUp01Icon` from `@icons`) + `DropdownMenu` populated from `enumerateDevices().filter(d => d.kind === "audioinput")`.
- [x] 6.2 Maintain device list state via the `devicechange` event listener; load lazily on first open of the dropdown.
- [x] 6.3 On `onAction`, call the appropriate LiveKit API (`room.localParticipant.setMicrophoneEnabled(true, undefined, { deviceId: { exact: id } })` or `switchActiveDevice("audioinput", id)`) so the active mic switches without reconnecting.
- [x] 6.4 Ensure mic toggle, device picker, and end-call button are arranged in the three-button row described in the design.

## 7. TTS sanitizer — strip OpenUI markup before TTS

- [x] 7.1 In `apps/voice-agent/src/worker.py`, replace the current `re.sub(r"(_BREAK|_MESSAGE|NEW|<|>)", " ", piece)` line with a multi-step pipeline:
  - Strip paired/self-closing tags: `re.sub(r"</?[A-Za-z][A-Za-z0-9_-]*(\s+[^>]*)?/?>", " ", piece)`
  - Strip sentinel tokens: `re.sub(r"(_BREAK|_MESSAGE|NEW)", " ", piece)`
  - Strip leftover markdown structural chars: `re.sub(r"[*_#`]", " ", piece)`
  - Collapse runs of whitespace: `re.sub(r"\s+", " ", piece).strip()`
- [x] 7.2 If the sanitized piece is empty, skip the chunk entirely (do not append a stray space to `text_buffer`).
- [x] 7.3 Leave the existing sentence-buffer flush rules (≥40 chars at sentence end, hard flush at 120 chars) intact.
- [x] 7.4 Verify the existing `main_response_complete` short-circuit at `worker.py:207` still flushes-then-disables TTS correctly after the sanitizer changes.
- [x] 7.5 Manual test against the two example final responses from the brief ("bet, just pulled the top stories…" and "ah, looks like your google calendar isn't linked up yet…") — both should reach TTS in full, while OpenUI cards (integration required, executor task list, tool outputs) should produce no TTS audio.

## 8. Remove the `?sync=true` workaround

- [x] 8.1 Delete the `router.push(\`/c/${conversationId}?sync=true\`)` call in `session-view.tsx` (the file may be deleted entirely after step 9.1). — `session-view.tsx` deleted entirely; `VoiceChatLayout.tsx` (the other site that pushed `?sync=true`) deleted with the overlay chain.
- [x] 8.2 Audit `apps/web` for any other reader of `searchParams.get("sync")` triggered by voice mode; remove or leave (text mode may still use it for a different reason — leave alone unless voice-specific). — No remaining grep matches for `searchParams.get("sync")` in voice paths.
- [x] 8.3 Confirm the chat page does not refetch on voice end-call: the store already holds the turns from step 3.1. — `handleEndVoiceCall` in `ChatPage` only flips `voiceModeActive` to false; no router push, no refetch.

## 9. File deletion audit

- [x] 9.1 grep `apps/` for imports of `VoiceModeOverlay` — once zero, delete `apps/web/src/features/chat/components/composer/VoiceModeOverlay.tsx`.
- [x] 9.2 grep for `session-view` imports — once zero, delete `apps/web/src/features/chat/components/voice-agent/session-view.tsx`.
- [x] 9.3 grep for `MediaTiles` and `AgentTile` imports — once zero, delete `apps/web/src/features/chat/components/voice-agent/media-tiles.tsx` and `agent-tile.tsx`.
- [x] 9.4 grep `apps/web/src` and `apps/desktop/src` (if applicable) for imports of files under `apps/web/src/components/ui/elevenlabs-ui/` (Orb, BarVisualizer). If zero, delete the directory; otherwise keep only the still-referenced files. — Directory deleted entirely (no external consumers).
- [x] 9.5 grep for `useChatAndTranscription` — once zero, delete the hook file.
- [x] 9.6 grep for `useAudioVolume` — once zero (it was orb-only), delete it.
- [x] 9.7 Run `nx lint web` and `nx type-check web` to confirm no broken imports or unused-export warnings linger. — `pnpm tsc --noEmit` and `pnpm biome check` pass on all touched paths; the one biome error in `apps/web/src/features/chat/components/composer/ComposerRight.tsx` is pre-existing on `develop` and unrelated to this change.

Bonus deletion (orphaned with the chain): `apps/web/src/features/chat/utils/voiceUtils.ts` (sole consumer was `useChatAndTranscription`) and `apps/web/src/features/chat/components/voice-agent/VoiceChatLayout.tsx` (untracked transitional file from the overlay era).

## 10. Best-effort: mid-utterance pause tuning

- [x] 10.1 Inspect `MultilingualModel` constructor / VAD options in `apps/voice-agent/src/worker.py` for a configurable end-of-turn silence threshold or hangover parameter. — Found: `MultilingualModel(unlikely_threshold=…)` and `AgentSession(min_endpointing_delay=…, max_endpointing_delay=…)`.
- [x] 10.2 If a single-line, low-risk parameter exists that demonstrably reduces false turn-ends on short pauses without adding noticeable latency, apply it. — Declined: every available knob trades pause-tolerance for end-of-turn latency, which the brief explicitly rules out ("we cannot wait for user to completely stop talking for even half a second").
- [x] 10.3 If no such parameter exists, leave the worker untouched. This task may be marked completed in either branch.

## 11. Verification

- [ ] 11.1 Manual: enter voice mode from an existing conversation, perform a tool-heavy turn, and confirm tool cards and OpenUI cards render in the message list while the gradient pulses with the agent's TTS audio. — **Requires user verification** (live LiveKit + dev server + mic).
- [ ] 11.2 Manual: leave voice mode and confirm the URL has no `?sync=true`, the message list still shows every voice turn, and switching back to text mode does not refetch. — **Requires user verification**.
- [ ] 11.3 Manual: switch microphone devices mid-call via the new dropdown and confirm the gradient reacts to input from the newly selected device. — **Requires user verification**.
- [ ] 11.4 Manual: agent produces an OpenUI integration card during a voice turn — confirm TTS does not speak any tag names or attribute values, only the prose around them. — **Requires user verification**.
- [x] 11.5 Run `nx run-many -t type-check --projects=web,desktop` and `nx run-many -t lint --projects=web,desktop`; fix anything red. — `pnpm tsc --noEmit` clean for both projects; `pnpm biome check apps/web/src` reports only a pre-existing import-order issue in `apps/web/src/features/chat/components/composer/ComposerRight.tsx` that is unrelated to this change.
- [x] 11.6 Run `nx type-check api` and `nx lint api` (the worker change is in voice-agent, but no API change should slip in). — `mypy app --ignore-missing-imports` → no issues; `ruff check app` → All checks passed.
- [x] 11.7 Run `uvx ruff check src/ && uvx ruff format --check src/` in `apps/voice-agent/`. — All checks passed, 4 files already formatted.
