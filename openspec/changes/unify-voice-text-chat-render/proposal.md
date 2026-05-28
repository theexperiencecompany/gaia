## Why

The previous voice-mode unification (`unify-voice-mode-with-text-ui-and-gradient`) put text and voice on the same chat surface, and the follow-up fix pass (`fix-voice-mode-pipeline-bugs`) plumbed every backend SSE payload through to the frontend so tool cards, OpenUI markup, and follow-up actions render identically in both modes. That second pass deliberately routed the *full* `response` field to the chat surface immediately, which means the bot bubble text now races ahead of the TTS audio — by the time the user *hears* "here's a draft for u", the bubble has already finished typing the whole sentence and rendered the OpenUI card. Users perceive this as the bubble talking over the agent.

The user's directive: keep the text-mode renderer (same `ChatRenderer` / `ChatBubbleBot` / OpenUI parser), keep every non-spoken event flowing immediately (tool calls, follow-up actions, OpenUI fences inside `response`), but stream the *spoken* portion of `response` into the bubble in lockstep with the TTS audio so the bubble fills as the agent speaks.

## What Changes

- Split the worker's `response` handling into two paths:
  - **UI-only fragments** (OpenUI fenced blocks, directive prefixes, sentinel/markup the TTS sanitiser strips) → forward to the frontend immediately on `backend-stream-event` so tool cards, embedded UI, and structured markup appear in the bubble the moment the backend emits them
  - **Spoken text fragments** (what survives TTS sanitisation) → buffered for ElevenLabs as before, but **not** forwarded on `backend-stream-event`; the frontend instead receives this text via LiveKit's TTS-aligned agent transcription (`use_tts_aligned_transcript` is already on)
- Non-`response` events (`tool_data`, `follow_up_actions`, `main_response_complete`, `[DONE]`) keep their existing behaviour: forwarded immediately, no TTS contribution
- Frontend `useVoiceMessages`:
  - Stops appending `event.response` to the bot turn for spoken text. Instead, subscribes to `useTranscriptions()` filtered to the agent identity and writes the TTS-aligned text into the same bot turn
  - Continues to append immediate UI-only fragments (new event shape: `{"response_ui": "..."}`), tool_data, and follow_up_actions to the same turn
  - Bot bubble visual order is preserved: spoken text + OpenUI cards interleave by arrival order; the small lag between immediate UI and aligned speech is the intended UX (UI ahead of speech is the explicit trade-off in the directive)
- Verify the existing mount-preservation contract end-to-end: `/c` ↔ `/c/:id` in voice mode must not remount `ChatPage`, the LiveKit `Room`, or the gradient. `history.replaceState` is already in place; this change adds an explicit spec scenario and a manual verification step
- Verify the gradient mute contract end-to-end: when source is `"mic"` and mic is muted, the spectrum raf must be cancelled and the gradient must settle. Existing code is in place; this change adds explicit scenarios

## Capabilities

### New Capabilities

<!-- None -->

### Modified Capabilities

- `voice-mode`: change the contract for how `response` field content reaches the chat surface — spoken text arrives via TTS-aligned transcription, UI-only fragments arrive immediately, all other events continue arriving immediately

## Impact

- **Backend (`apps/voice-agent`)**
  - `src/llm.py` — `gen()` no longer forwards the raw SSE payload unconditionally when the event carries a `response` field. Instead, it splits the response value, emits a `{"response_ui": "..."}` event on `FRONTEND_STREAM_TOPIC` for the non-spoken fragments, and only buffers the spoken fragments for TTS. Plumbing events (`tool_data`, `follow_up_actions`, `main_response_complete`, `conversation_id`, `conversation_description`) continue to forward as-is
  - `src/utils.py` — adds a `split_response_for_ui_and_tts(piece: str) -> tuple[str, str]` helper that returns `(ui_only, tts_text)`. Reuses the existing `OPENUI_FENCE_RE` / `DIRECTIVE_PREFIX_RE` / `TAG_RE` / `SENTINEL_RE` / `MARKDOWN_RE` patterns so the contract stays single-sourced
  - `src/constants.py` — adds `RESPONSE_UI_KEY = "response_ui"` to `__all__`
- **Frontend (`apps/web`)**
  - `src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts` — replaces the `event.response` accumulator with two sources: (a) `useTranscriptions()` filtered to the agent identity for spoken text, (b) a new `event.response_ui` branch for immediate UI-only fragments. `event.response` itself is no longer read (the worker doesn't emit it any more)
  - `src/features/chat/components/voice-agent/VoiceControlBarContainer.tsx` — no functional change; this change adds verification that `history.replaceState` keeps the LiveKit `Room` mounted across `/c` ↔ `/c/:id`
  - `src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts` — no functional change; this change adds explicit verification of the mic-mute and `document.hidden` pause paths
- **No DB / API schema changes**
- **No new dependencies**
- **No changes to `libs/shared/`**
