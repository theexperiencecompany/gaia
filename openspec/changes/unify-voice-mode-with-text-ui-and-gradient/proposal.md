## Why

Voice mode currently opens as a separate overlay with its own orb/bar-visualizer UI, re-implementing message rendering and reverse-syncing messages back to text mode on disconnect. This duplicates the chat UI, hides tool cards, loading states, and follow-up actions during voice calls, and forces a `?sync=true` refetch hack on exit. At the same time, TTS speaks UI-targeted content (markdown tokens, tool outputs, integration prompts) because the voice worker filters by regex on the post-formatted stream instead of by event type at the source.

## What Changes

- **BREAKING (internal):** Replace the separate `VoiceModeOverlay` overlay with an in-place mode toggle on `ChatPage`. The existing chat layout (scrollable messages + bottom bar) is reused; only the bottom `Composer` is swapped for a voice control bar when voice is active.
- Voice messages stream into the same `MessageType[]` consumed by `ChatRenderer` / `ChatBubbleBot` / `ChatBubbleUser`, so tool cards, intermediate tool-call events, OpenUI cards, loading indicator, and follow-up actions all render identically to text mode during a voice call.
- Replace the orb (`AgentTile`) + bar visualizer (`BarVisualizer`) with the `VoiceGradient` shader. The gradient is driven by a unified spectrum hook that switches between the local mic stream and the LiveKit agent audio track based on `agentState` (listening → mic; speaking → agent track; thinking → synthetic/idle envelope).
- Add a microphone-device picker (HeroUI `Dropdown` + `enumerateDevices`) next to the mic toggle in the voice control bar, replacing the current single-button bar.
- Backend: tighten the TTS publish path in the voice worker so only the final assistant response text (the `response` field of the chat stream's terminal assistant chunks) is forwarded to TTS — not intermediate tool-call events, tool outputs, integration prompts, follow-up actions, or any other event surfaced to the UI. Sentence-level regex sanitization remains as a safety net, but the event-type filter is the primary gate.
- Remove the `?sync=true` post-disconnect refetch in voice end-call handling — the conversation already lives in the same store/route as voice plays inside the chat page.
- Delete now-orphaned files: `VoiceModeOverlay`, `AgentTile`, `MediaTiles`, the `elevenlabs-ui` directory (Orb, BarVisualizer) if not consumed elsewhere, and any voice hooks superseded by the unified flow (notably `useChatAndTranscription` once `useVoiceMessages` is wired in).

## Capabilities

### New Capabilities

- `voice-mode`: In-place voice interaction that reuses the text-mode chat surface for message rendering, swaps the composer for a voice control bar (mic toggle + device picker + end-call), drives a single shared spectrum-reactive gradient from the user mic and agent audio tracks, and routes only final assistant responses to TTS.

### Modified Capabilities

<!-- None — no prior openspec specs exist in this repo. -->

## Impact

- **Frontend (`apps/web`)**
  - `src/features/chat/components/interface/ChatPage.tsx` — voice mode becomes an inline boolean rendered by the same layout; `VoiceApp` import removed.
  - `src/features/chat/components/interface/layouts/ChatWithMessages.tsx` (and `NewChatLayout.tsx`) — accept a `bottomBar` slot or a `voiceModeActive` flag so they can render the voice control bar instead of `Composer`.
  - `src/features/chat/components/voice-agent/` — new in-place container that owns LiveKit `Room`, spectrum hook, gradient, and control bar; consumes `useVoiceMessages` and pushes turns into the same chat store the text renderer reads from.
  - `src/features/chat/components/voice-agent/agent-control-bar.tsx` — adds device-selector dropdown.
  - `src/features/chat/components/voice-agent/hooks/useVoiceMessages.ts` — exposed as the source of voice-turn `MessageType[]` for the unified renderer; persists into the same store used by text mode.
  - Spectrum hook — moved from `src/app/[locale]/dev/voice-gradient/useVoiceSpectrum.ts` into the voice-agent feature folder, generalized to accept both local mic and a remote `MediaStreamTrack` (agent audio) as sources.
  - `VoiceGradient.tsx` — moved from the dev route into the voice-agent feature folder; the dev page keeps working by importing from the new shared location.
  - Deleted: `VoiceModeOverlay.tsx`, `voice-agent/media-tiles.tsx`, `voice-agent/agent-tile.tsx`, `components/ui/elevenlabs-ui/` (orb + bar-visualizer) if no other consumers, `voice-agent/hooks/useChatAndTranscription.ts` (superseded).
- **Backend (`apps/voice-agent`)**
  - `src/worker.py` — only chunks whose event type is the final assistant response stream are forwarded to the TTS sink. The existing `_BREAK|_MESSAGE|NEW|<|>` regex stays as a defensive cleanup on the surviving text.
- **Backend (`apps/api`)**
  - `app/api/v1/endpoints/chat.py` and the upstream chat service emit no new fields, but the voice worker now classifies events by their existing type (response chunk vs. tool-call vs. follow-up vs. tool-output) — no schema change.
- **Routing**
  - The `router.push('/c/<id>?sync=true')` exit shortcut is removed; the user stays on the current conversation page when ending a call.
- **No DB / API schema changes. No new dependencies.**
