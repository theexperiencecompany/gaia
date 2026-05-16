## Context

Voice mode today is a separate React tree (`VoiceModeOverlay` → `SessionView` → `MediaTiles` + `AgentControlBar`) rendered when `voiceModeActive` toggles on `ChatPage`. It owns its own LiveKit `Room`, its own visualizer (orb / bar visualizer from `components/ui/elevenlabs-ui`), its own message list built from `useChatAndTranscription`, and a bespoke control bar. On hang-up it pushes `/c/<id>?sync=true` to force the text-mode UI to refetch what voice just produced.

The chat-stream SSE protocol the backend already speaks is event-typed at the top-level key:

| Top-level key | Purpose | TTS-eligible? |
|---|---|---|
| `response` | LLM text chunks (may include OpenUI markup like `<Label …>`) | Yes, but markup must be stripped |
| `tool_data` | Tool call descriptors + results | No |
| `tool_output` | Tool execution output (mail bodies, calendar events) | No |
| `follow_up_actions` | Suggested next prompts | No |
| `conversation_id` / `conversation_description` | Metadata | No |
| `main_response_complete` | Boundary marker; TTS off after | Boundary only |

The voice worker (`apps/voice-agent/src/worker.py`) already gates on `RESPONSE_KEY = "response"`, so non-`response` events are not sent to TTS. The remaining bleed is that the LLM streams OpenUI markup *inside* `response`, and the current regex (`_BREAK|_MESSAGE|NEW|<|>` → space) strips only the angle brackets, leaving tag names (`Label`, `Section`, `Text`, attribute values) in the TTS stream.

A friend has shipped a stand-alone WebGL voice gradient at `apps/web/src/app/[locale]/dev/voice-gradient/` driven by `useVoiceSpectrum` (supports `mic`, `synthetic`, `hybrid`, `idle` sources). That spectrum hook today only knows about the local mic; for production it must also react to the remote agent audio track during TTS playback.

## Goals / Non-Goals

**Goals:**
- One chat UI for both modes — voice messages render through `ChatRenderer` / `ChatBubbleBot` / `ChatBubbleUser` with full tool-card, OpenUI, loading-indicator, and follow-up-action support.
- Voice control bar replaces the composer slot (and only that slot) when voice mode is active.
- Visualizer = `VoiceGradient`, fed by a spectrum hook that switches its audio source by `agentState` (listening → mic, speaking → agent track, thinking/connecting → idle envelope).
- TTS speaks only the final assistant response prose; OpenUI markup, tool calls, tool outputs, and follow-up actions are excluded.
- Mic-device selector in the voice control bar (HeroUI `Dropdown` + `navigator.mediaDevices.enumerateDevices()`).
- No `?sync=true` post-disconnect refetch.

**Non-Goals:**
- No SSE schema change on the backend (`apps/api`) — the existing event taxonomy already provides the type discriminators we need.
- No new visualizer designs beyond the existing `VoiceGradient`.
- No mobile/desktop app changes — web-only refactor. The voice gradient does need WebGL2; we keep the existing orb files *only* if the mobile app imports them (verified during implementation).
- No backend turn-detection rewrite. The mid-utterance-pause regression is best-effort: we will tune the existing `MultilingualModel` / VAD configuration if a low-risk parameter exists, otherwise document and skip.
- No new persistence path for voice messages beyond what `useVoiceMessages` already produces; we feed its output into the same chat-store stream the text mode reads.

## Decisions

### 1. UI composition — one layout, swappable bottom bar

`ChatWithMessages` (and `NewChatLayout`) accept a new prop, `bottomBar: React.ReactNode`, that the layout renders in the existing `shrink-0 pb-2` slot. `ChatPage` decides what to put there: `<Composer …/>` in text mode, `<VoiceControlBar …/>` in voice mode. The scrollable message area, drag-and-drop wiring, scroll-to-bottom button, and `ChatSection` remain untouched.

This keeps `useChatLayout` / `useScrollBehavior` / `ChatRenderer` / `ChatBubbleBot` / `ChatBubbleUser` / `OpenUIRenderer` / all tool cards in the renderer chain — zero duplication.

**Alternative considered:** Render the voice control bar conditionally inside `Composer`. Rejected — `Composer` already has heavy responsibilities (file uploads, workflows, tool selectors); injecting a second mode there couples concerns.

### 2. Voice messages stream into the existing chat store

Today, `useChatAndTranscription` builds a transient `messages` array only consumed inside `SessionView`. In the unified flow, `useVoiceMessages` becomes the single source — but its output is fed into the same store/path that `useConversation()` reads from, so `ChatRenderer` picks them up without any change. Two implementation options:

- **(A) Direct store dispatch:** Each parsed voice turn is upserted into the chat store (`useChatStore` / `chatDb`) so it shows up in `convoMessages` exactly like a text turn. The agent control bar effectively becomes "send a voice turn via LiveKit instead of POST `/chat-stream`."
- **(B) Renderer prop override:** Pass a `convoMessages` override prop down through `ChatWithMessages` → `ChatSection` → `ChatRenderer` (the renderer already accepts that prop today). Voice mode passes `useVoiceMessages()` output; text mode passes nothing and the renderer falls back to the store.

Choose **(A)** for the final state — it eliminates the `?sync=true` refetch entirely and unifies persistence. (B) is a tempting shortcut but it leaves two stores of truth alive and re-introduces a sync question on hang-up. The voice worker already writes the conversation to MongoDB on `main_response_complete`, so on next mount the store hydrates from the canonical source anyway; the in-session store update is the bridge that makes the live UI show the turns without a refetch.

**Alternative considered:** Keep two paths and do an in-memory copy on hang-up. Rejected — that's the `?sync=true` problem in a different costume.

### 3. Visualizer — single spectrum hook, dual source

Move `useVoiceSpectrum` from `src/app/[locale]/dev/voice-gradient/` to `src/features/chat/components/voice-agent/hooks/useVoiceSpectrum.ts` and generalize:

- Accept an optional `remoteTrack: MediaStreamTrack | null` (the agent audio track from `useVoiceAssistant().audioTrack`).
- Internal source selection driven by `agentState` (passed in from the caller):
  - `listening` → mic
  - `speaking` → remote agent track
  - `thinking` / `connecting` → idle envelope (low-amplitude synthetic)
  - `disconnected` → idle
- Drop the `"hybrid"`, `"synthetic"` demo modes from the production hook (keep them in the dev page by re-exporting a thin demo wrapper, or duplicate the dev file under `apps/web/src/app/[locale]/dev/voice-gradient/` if cleanup is simpler).

Move `VoiceGradient.tsx` similarly to `src/features/chat/components/voice-agent/VoiceGradient.tsx`. The dev page imports from the new location.

**Alternative considered:** Drive the bar visualizer with the same audio track. Rejected — the user explicitly wants the gradient and the elevenlabs-ui pieces deleted.

### 4. TTS sanitization — two-stage filter, no backend change

The chat-stream `response` field is the right TTS source, but it can carry OpenUI markup. Implement a stricter sanitizer in the voice worker that runs *before* sentence buffering:

1. **Tag-stripping pass:** Replace `</?[A-Za-z][A-Za-z0-9_-]*(\s+[^>]*)?/?>` with a single space (removes both self-closing and paired OpenUI/HTML tags AND their attributes). This also covers the existing markdown leakage cases the user described (`<Label>`, `<p>`, `<Section>`).
2. **Markdown-token pass:** Strip the existing `_BREAK|_MESSAGE|NEW` sentinel tokens (keep current behavior). Strip leftover markdown structural characters that should not be spoken: bare `*`, `_`, `#`, backticks. Keep periods/commas/question marks/apostrophes.
3. **Whitespace collapse + empty-skip:** Collapse runs of whitespace and skip the chunk if it ends up empty.

After sanitization, the existing sentence-buffer/flush logic at `worker.py:262–298` continues to gate TTS emission. The `main_response_complete` boundary continues to short-circuit any TTS after the final turn.

**Why no backend change?** The chat-stream is consumed by web, desktop, bots, and the upcoming mobile app — adding a `tts_text` field would force every consumer to learn the new shape. Tag-stripping at the voice worker keeps the contract narrow.

**Alternative considered:** Send a parallel `tts_text` field that excludes OpenUI. Holds for future, but out of scope for this change.

### 5. Mic device selector

Reuse the dev-page pattern: HeroUI `Dropdown` with items from `navigator.mediaDevices.enumerateDevices()` filtered by `kind === "audioinput"`. The picker sits immediately to the right of the mic toggle in `AgentControlBar`. Selecting a device calls `localParticipant.setMicrophoneEnabled(true, undefined, { deviceId: { exact: id } })` and updates the LiveKit track. Device list refreshes on `devicechange`.

### 6. Mid-utterance pause regression

Document it in the spec as a known limitation. During implementation, check whether `MultilingualModel` exposes a configurable end-of-turn silence threshold; if a single-line tweak meaningfully reduces false turn-ends without hurting latency, ship it. Otherwise leave the worker config untouched — the user explicitly authorized skipping this.

### 7. File-deletion audit

After wiring, grep the repo (including `apps/desktop`, `apps/mobile`, `apps/api`) for imports of each candidate-for-deletion file before deleting. The candidates:

| File / dir | Delete if |
|---|---|
| `apps/web/src/features/chat/components/composer/VoiceModeOverlay.tsx` | No remaining imports |
| `apps/web/src/features/chat/components/voice-agent/session-view.tsx` | Folded into the new in-place container |
| `apps/web/src/features/chat/components/voice-agent/media-tiles.tsx` | Replaced by gradient |
| `apps/web/src/features/chat/components/voice-agent/agent-tile.tsx` | Replaced by gradient |
| `apps/web/src/components/ui/elevenlabs-ui/` (orb, bar-visualizer) | No imports outside the deleted voice files; the dev page must also migrate |
| `apps/web/src/features/chat/components/voice-agent/hooks/useChatAndTranscription.ts` | `useVoiceMessages` covers its use |

Anything still referenced by the dev voice-gradient page is migrated, not deleted.

## Risks / Trade-offs

- **Two stores of truth during the cut-over** → Mitigation: land store-write path first (decision #2), verify text-mode renders voice turns live, then remove the `?sync=true` push as the second commit.
- **Tag-stripping regex over- or under-matches** → Mitigation: keep the existing `<` / `>` fallback in place; add explicit no-op for code-fenced content (`...`) so users dictating code don't lose punctuation. Verify against the example transcripts in the user's screenshot before declaring done.
- **VoiceGradient is WebGL2-only** → Mitigation: the gradient already logs a warning and the dev page degrades to no visual. In production, fall back to a static "voice active" badge if `WebGL2RenderingContext` is unavailable. (Most browsers we target support it.)
- **`useVoiceSpectrum` analyser re-attach when agent audio track changes** → Mitigation: hook re-subscribes whenever the `remoteTrack.mediaStreamTrack` identity changes; teardown follows the existing pattern in the dev hook.
- **Mid-utterance pause regression** → Mitigation: documented in spec as known limitation; only adjust VAD if the change is provably non-regressive.
- **Removing `?sync=true` could break first-mount hydration if the store write didn't happen** → Mitigation: keep an explicit `syncSingleConversation(convoId)` call in the voice end-call handler (already part of normal mount logic via `useEffect` in `ChatPage`) as a defense-in-depth, but not a query-param-driven refetch.
- **Deleting elevenlabs-ui breaks the dev voice-gradient page** if it imports anything from there → Mitigation: dev page only uses its own files (`VoiceGradient`, `useVoiceSpectrum`); confirm before deletion. If the BarVisualizer is referenced by any future demo, keep it but mark deprecated; otherwise delete.
