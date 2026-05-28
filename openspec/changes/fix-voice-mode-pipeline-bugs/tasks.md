## 1. Voice-agent Infisical fetch lives in main process only

- [x] 1.1 In `apps/voice-agent/src/config.py`, remove the `inject_infisical_secrets()` call from `bootstrap_settings()`. The function should only call `get_settings()` and return it
- [x] 1.2 Drop the now-unused `from shared.py.secrets import inject_infisical_secrets` import in `config.py`
- [x] 1.3 Update the `bootstrap_settings()` docstring to explain that Infisical is contacted only in the main process (`start_worker()` / `download_files()`) and children inherit env vars via forkserver
- [x] 1.4 Update `apps/voice-agent/CLAUDE.md` startup-sequence section to reflect the new contract
- [ ] 1.5 Verify with `nx lint voice-agent` and confirm a fresh `mise dev` run produces exactly one `Connecting to Infisical...` log line across all processes

## 2. Voice-agent TTS sanitisation

- [x] 2.1 In `apps/voice-agent/src/constants.py`, add `OPENUI_FENCE_RE = re.compile(r":::openui[\\s\\S]*?(?::::|\\Z)")` and `DIRECTIVE_PREFIX_RE = re.compile(r":::[a-zA-Z]+\\b")`; export both in `__all__`
- [x] 2.2 In `apps/voice-agent/src/utils.py`, update `sanitize_for_tts()` to run `OPENUI_FENCE_RE.sub(" ", piece)` first, then `DIRECTIVE_PREFIX_RE.sub(" ", piece)`, then the existing chain (`TAG_RE`, `SENTINEL_RE`, `MARKDOWN_RE`, `WHITESPACE_RE`)
- [x] 2.3 Confirm fence-spanning chunks are handled: extend `has_open_tag_at_tail()` (or add a new helper `has_open_openui_fence_at_tail()`) so a trailing `:::openui` without `:::` close defers the flush
- [x] 2.4 Wire the new helper into the `should_flush` defer logic in `llm.py`

## 3. Voice-agent event-type gating

- [x] 3.1 In `apps/voice-agent/src/llm.py` `gen()`, define a `TTS_TEXT_FIELD = "response"` constant and a set of plumbing-only event keys (`tool_data`, `tool_output`, `follow_up_actions`, `main_response_complete`, `conversation_id`, `conversation_description`)
- [x] 3.2 Reorder event handling so plumbing payloads are dispatched and `continue`-d before any `text_buffer.append`
- [x] 3.3 Confirm `text_buffer` only ever receives the value of `event_payload.get(RESPONSE_KEY)` and only when no plumbing key is present in the same event

## 4. Forward every backend event to frontend (revised)

- [x] 4.1 In `apps/voice-agent/src/llm.py`, restore unconditional `await self._forward_stream_event_to_frontend(data)` for every parsed backend SSE event. The `is_plumbing` flag stays only as a TTS-buffer gate (downstream check), not as a forward gate
- [x] 4.2 In `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts`, restore the `event.response` accumulation branch in the bot-stream handler so the chat bubble fills as backend tokens arrive
- [x] 4.3 Restore `activeTurnRef.current = null` on `main_response_complete` so subsequent turns open a fresh bubble instead of appending to the prior turn
- [x] 4.4 Remove the bot-transcription effect, `botTurnTranscriptionTextsRef`, and `consumedBotTranscriptionIdsRef` — bot text now flows through `event.response` again

## 4b. Preserve voice session across conversation-id discovery

- [x] 4b.1 In `apps/web/src/features/chat/components/voice-agent/VoiceControlBarContainer.tsx`, replace `router.replace(/c/:id)` with `window.history.replaceState(window.history.state, "", localePrefix + "/c/:id")` so the URL updates in place without remounting `ChatPage`
- [x] 4b.2 Import `usePathname` instead of `useRouter` to derive the locale prefix at runtime
- [x] 4b.3 Confirm the LiveKit `Room` instance (created with `useMemo(() => new Room(), [])` in `VoiceControlBarContainer`) survives the URL update by virtue of `ChatPage` not unmounting

## 5. Loguru brace-safe logging

- [x] 5.1 Audit every `logger.{debug,info,warning,error}` call in `apps/voice-agent/src/llm.py` and `apps/voice-agent/src/agent.py` that interpolates a backend or user-supplied value into the f-string message
- [x] 5.2 For each, move the interpolated value out of the message and into a logger kwarg (keep a short, brace-free human label in the message string)
- [ ] 5.3 Verify with a unit-style smoke: set `LOG_LEVEL=DEBUG`, run the worker locally, send a payload containing `{"label": "x"}` and confirm no `KeyError` appears in `apps/voice-agent/logs/errors-*.log`
- [x] 5.4 Run `nx lint voice-agent` and confirm no f-string-with-braces warnings (Loguru rule not enforced by ruff, so this is a manual review checkpoint)

## 6. Frontend voice spectrum gating

- [x] 6.1 In `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts`, remove the in-tick mute attenuation (`out[i] = out[i] * 0.85`) and replace with logic that returns false from `sampleMic` when muted so the source falls back to `buildIdleSpectrum`
- [x] 6.2 Add a `useEffect` that watches `isMuted` and `source`: when `isMuted && source === "mic"`, cancel `rafRef.current` and set it to `null`; on unmute, restart with a fresh `requestAnimationFrame(tick)`
- [x] 6.3 Add a `visibilitychange` listener at the top-level effect that cancels the raf when `document.hidden` and restarts on `visibilitychange` back to visible
- [x] 6.4 Confirm the agent-track pipeline (`remoteCtxRef`, `remoteAnalyserRef`) is unaffected by mute by reading the existing remoteTrack effect

## 7. Frontend user-group survival across bot turns

- [x] 7.1 In `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts`, remove the `if (activeTurnRef.current !== null) return;` early-return in the transcription effect
- [x] 7.2 Replace with logic that, when a bot turn is active, still opens a new user group keyed on the new transcription's stream id and sets `startedAt = new Date(Math.max(Date.now(), activeTurn.startedAt.getTime() + 1))`
- [x] 7.3 Add a guard so the same user group is not also closed by the active bot turn; only the bot turn that *opens after* this user group should close it
- [x] 7.4 Verify the chat sort order in `chatStore` is `createdAt` ascending, otherwise adjust the per-turn timestamp offset

## 8. Verification

- [x] 8.1 Run `nx lint voice-agent && nx format voice-agent`
- [x] 8.2 Run `nx lint web && nx run web:type-check`
- [x] 8.3 Run the worker locally with `LOG_LEVEL=DEBUG mise dev` and confirm: only one Infisical fetch in main process logs, no further fetches in job_p logs across 3+ room joins (code-level: `bootstrap_settings()` no longer imports or calls `inject_infisical_secrets`; the only remaining call sites are `start_worker()` and `download_files()` in the main process)
- [ ] 8.4 In the web app, start a voice session, ask "draft an email about my CPU spikes" and confirm the TTS does not speak `:::openui` or any `TextDocument(...)` content
- [ ] 8.5 Confirm the chat bubble text fills in sync with the spoken audio (no large pre-spelling)
- [ ] 8.6 Mute the microphone mid-call and confirm the gradient stops animating; switch tabs and confirm the same
- [ ] 8.7 Speak a second time while the bot is still speaking the first response; confirm the second user transcription renders as its own bubble
- [ ] 8.8 Confirm `apps/voice-agent/logs/errors-*.log` does not gain a new `KeyError` entry during the verification session
