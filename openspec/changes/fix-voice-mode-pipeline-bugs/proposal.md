## Why

Real-session logs from 2026-05-24 show the voice mode pipeline still has six concrete defects after the worker refactor:

1. Every new LiveKit JobProcess respawn re-runs `inject_infisical_secrets()`, adding a 2-3s Infisical round-trip to room-join latency. Logs show fresh "Connecting to Infisical..." entries at 23:25:34, 23:26:04, 23:28:16, 23:33:08 (one per new room/job).
2. TTS speaks OpenUI directives. A real flush from the log: `'bet, drafting that for u now. :::openui root = TextDocument("Email Draft", ...'`. `sanitize_for_tts` only strips angle-bracket tags and a few markdown chars, not `:::openui ... :::` fenced blocks or directive prefixes.
3. The voice gradient pegs GPU and reacts to ambient audio even when the mic is muted. Mute only toggles `track.enabled`; the AnalyserNode pipeline keeps polling and the requestAnimationFrame loop keeps animating at full rate.
4. Frontend bot text arrives before audio because `CustomLLM._forward_stream_event_to_frontend` ships every backend SSE chunk to the room immediately, while the synthesized speech arrives seconds later.
5. The user's transcribed text never appears in some turns. `useVoiceMessages` short-circuits when a bot turn is already active (`activeTurnRef.current !== null`), and with `preemptive_generation=True` the bot turn opens before STT finalises, so the user bubble is silently dropped.
6. A `KeyError: '"label"'` in `llm.py:279` crashes the stream when backend tokens contain `{...}` JSON. Loguru is interpreting the token text as a format string.

These show up on every test session, block dogfooding, and waste real money on retried LLM calls.

## What Changes

- Make Infisical bootstrap idempotent across forkserver children. `inject_infisical_secrets()` returns early when a sentinel env var (set by the previous successful injection) is already present. forkserver inherits the parent's environment, so children skip the network call.
- Replace the post-stream regex sanitiser with an event-type gate at the source. Tokens emitted under a `tool_data` / OpenUI / tool-output event SHALL NOT enter the TTS buffer. The regex sanitiser becomes a defence-in-depth net that also strips `:::openui ... :::` fenced blocks and directive prefixes.
- Defer frontend text forwarding until the matching TTS chunk starts playback. The voice worker SHALL emit frontend text from the LiveKit `tts_aligned_transcript` callback, not from the raw backend SSE loop. Plumbing events (`conversation_id`, `tool_data`, `[DONE]`) keep forwarding immediately on the existing topic.
- Forward STT-final events to the frontend as their own message even when a bot turn is already in flight. `useVoiceMessages` SHALL allow user groups to be opened after a bot turn has started, and the bot turn SHALL sort below the user group by `createdAt`.
- Gate the spectrum animation on mute and visibility. The requestAnimationFrame tick SHALL be cancelled (not just attenuated) when the mic is muted in mic-source mode, and when the document is hidden. The agent-track analyser keeps running.
- Fix the Loguru format crash by passing token content as a logger kwarg only, never as part of the f-string template. Apply the same rule to every existing `logger.{debug,info,error}` call in `llm.py`.

## Capabilities

### New Capabilities

- (none)

### Modified Capabilities

- `voice-mode`: Adds requirements for one-time secret bootstrap across worker processes, event-type-gated TTS sanitisation, TTS-aligned frontend text forwarding, user transcription survival during preemptive bot turns, mute-aware spectrum render gating, and structured-logger safety.

## Impact

- **Backend**: `libs/shared/py/secrets.py` (sentinel env var guard), `apps/voice-agent/src/llm.py` (event-type gate, tts_aligned_transcript wiring, logger kwarg fix), `apps/voice-agent/src/constants.py` (OpenUI fence regex, directive regex), `apps/voice-agent/src/utils.py` (extended `sanitize_for_tts`).
- **Frontend**: `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts` (mute/visibility gating, raf cancel), `apps/web/src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts` (user group survival across bot turn).
- **Logs**: New per-turn alignment debug entries replacing the current "FORWARD FRONTEND on raw SSE" lines; KeyError noise in `errors-*.log` disappears.
- **No API changes**: Backend `chat-stream` SSE contract is unchanged. LiveKit data-channel topic name (`backend-stream-event`) is unchanged.
- **No breaking changes** to other apps. Other consumers of `gaia-shared.secrets` (`apps/api`, `apps/bots`) get the same idempotency benefit transparently.
