## 1. Worker: split helper

- [x] 1.1 In `apps/voice-agent/src/utils.py`, add `split_response_for_ui_and_tts(piece: str) -> tuple[str, str]` that returns `(ui_only, tts_text)`. `ui_only` is the concatenation of every substring matched by `OPENUI_FENCE_RE`, `DIRECTIVE_PREFIX_RE`, `TAG_RE`, and `SENTINEL_RE` (in source order). `tts_text` is the result of running `sanitize_for_tts(piece)` on the original piece
- [x] 1.2 Export the new helper in `apps/voice-agent/src/utils.py`'s `__all__`
- [x] 1.3 In `apps/voice-agent/src/constants.py`, add `RESPONSE_UI_KEY = "response_ui"` and export it in `__all__`

## 2. Worker: response-event split path

- [x] 2.1 In `apps/voice-agent/src/llm.py` `gen()`, after the existing per-event `_forward_stream_event_to_frontend(data)` call, remove that unconditional forward for events where `RESPONSE_KEY` is present and is the only content-bearing key. Keep the unconditional forward for every other event (plumbing keys, multi-key events, `[DONE]`)
- [x] 2.2 For response-only events, compute `(ui_only, tts_text) = split_response_for_ui_and_tts(piece)`. If `ui_only` is non-empty, build a `{"response_ui": ui_only}` JSON string and forward it via `_forward_stream_event_to_frontend(...)` *before* touching the TTS buffer
- [x] 2.3 Continue to append `tts_text` (the spoken slice) to `text_buffer` using the existing flush logic — no behaviour change on the TTS side
- [x] 2.4 If both `ui_only` and `tts_text` are empty (a response chunk that sanitises to nothing), emit neither — do not forward an empty `response_ui`

## 3. Frontend: bot transcription branch

- [x] 3.1 In `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts`, remove the `if (typeof event.response === "string" && event.response)` accumulator branch in the bot-stream handler. Replace with a branch that reads `event.response_ui` (string) and appends it to `turn.response`. Order: handle `response_ui` first, then `tool_data`, then `follow_up_actions`, then `main_response_complete`
- [x] 3.2 Add a new `useEffect` that subscribes to the already-running `useTranscriptions()` array (the hook is already called for user STT). Filter to transcriptions whose `participantInfo.identity !== room.localParticipant.identity` — those are the agent's TTS-aligned transcriptions
- [x] 3.3 In that effect, for each bot transcription whose `streamInfo.id` is not in a per-turn consumed set, append `t.text` to the active bot turn's `response` and add the id to the consumed set. If no active bot turn exists, open one via the existing `openBotTurn()` helper
- [x] 3.4 Reset the per-turn consumed set when a new bot turn opens. Persist completed turns' consumed sets so late-arriving transcriptions still patch the closed turn's bubble (look up the turn by `streamInfo.timestamp` falling in the turn's `startedAt` → next-turn-`startedAt` window)
- [x] 3.5 Call `addOrUpdateMessage(turnToIMessage(turn, cid))` after every transcription append so the bubble re-renders

## 4. Frontend: regression-lock verifications

- [x] 4.1 Confirm by inspection that `VoiceControlBarContainer.tsx` still uses `window.history.replaceState` (not `router.replace`) for the `/c` → `/c/:id` URL update
- [x] 4.2 Confirm by inspection that `useVoiceSpectrum.ts` still cancels `rafRef` on `(source === "mic" && isMuted)` and on `document.hidden`
- [x] 4.3 Confirm by inspection that both `/c/page.tsx` and `/c/[id]/page.tsx` render the same `<ChatPage />` and the message renderer is `ChatRenderer` in both modes

## 5. Quality gates

- [x] 5.1 Run `nx lint voice-agent`
- [x] 5.2 Run `nx run web:type-check`
- [x] 5.3 Run `nx lint web`
- [x] 5.4 Run `uvx ruff format src/` from `apps/voice-agent/` to apply formatter

## 6. Live verification

- [ ] 6.1 Start the worker with `LOG_LEVEL=DEBUG mise dev`; in the web app, open a fresh `/c` and start voice mode
- [ ] 6.2 Speak "draft an email about my CPU spikes". Confirm the bot bubble's spoken text fills in roughly aligned with the TTS audio (no large pre-spelling)
- [ ] 6.3 Confirm the Email Draft (OpenUI card) renders in the same bot bubble, appearing on or shortly before the spoken introduction
- [ ] 6.4 Confirm the URL updates from `/c` to `/c/:id` without a visible chat-surface remount, and the first user transcription + first bot response remain visible after the URL change
- [ ] 6.5 Mute the microphone mid-call. Confirm the gradient stops reacting; switch tabs and confirm the same
- [ ] 6.6 Speak a follow-up while the bot is still speaking. Confirm the new user bubble appears below the active bot bubble, and the bot's next response opens a fresh bubble below it
- [ ] 6.7 Confirm `apps/voice-agent/logs/errors-*.log` gains no new entries during the session
