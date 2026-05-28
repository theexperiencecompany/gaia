## Context

Today the voice worker (`apps/voice-agent/src/llm.py`) forwards every parsed SSE event from the GAIA backend to the frontend on `FRONTEND_STREAM_TOPIC` immediately, *and* buffers a sanitised slice of any `response` field for the LiveKit TTS plugin. The frontend `useVoiceMessages` hook reads `event.response` from the data-channel stream and appends it to the active bot turn in `chatStore`, so the bubble fills as backend tokens arrive — typically several seconds before the corresponding TTS audio plays.

The earlier `unify-voice-mode-with-text-ui-and-gradient` change put both modes on the same `ChatRenderer`. The follow-up `fix-voice-mode-pipeline-bugs` change forwarded all backend payloads through to the frontend to preserve OpenUI fidelity and tool-card rendering. Those two changes solved the rendering-parity problem but left the spoken-text/audio race condition open.

`AgentSession` already runs with `use_tts_aligned_transcript=True` and `preemptive_generation=True`. The TTS-aligned transcript is published by LiveKit on a `_ParticipantTranscriptionOutput` channel and is consumed on the frontend via the `useTranscriptions()` hook from `@livekit/components-react`. We previously tried a transcription-only path for bot text and reverted it because (a) OpenUI markup never reached the bubble, and (b) chunks arrived in fragments that did not align with our turn boundaries. The fix is to keep the immediate path for everything *except* the spoken portion of `response`, and only use TTS-aligned transcription for that one slice.

## Goals / Non-Goals

**Goals:**

- Spoken text in the bot bubble fills in synchronisation with the agent's TTS audio
- OpenUI cards, tool_data, follow_up_actions, and any other non-spoken content continue to appear in the bubble immediately on arrival
- The same `ChatRenderer` + `ChatBubbleBot` + OpenUI parser are used for both text and voice modes (already true; verify and lock down)
- The chat surface, gradient, and LiveKit `Room` survive the `/c` → `/c/:id` URL change in voice mode (already implemented; verify and lock down via spec scenarios)
- Voice gradient ignores mic input when the mic is muted (already implemented; verify and lock down)

**Non-Goals:**

- Changing the text-mode flow — text mode `Composer` and chat rendering are untouched
- Splitting the bot bubble into multiple components for voice vs text — single component, single store
- Re-attempting TTS-aligned text for tool_data, follow_up_actions, or OpenUI markup. Those keep the immediate-forward path the previous change established
- Adding any new dependency to the worker or the web app
- Changing the `libs/shared/py/secrets.py` contract or the Infisical bootstrap path

## Decisions

### Decision 1: Split `response` into UI-only and TTS-spoken at the worker, not the frontend

When the worker parses a `response` event it runs the payload through a new `split_response_for_ui_and_tts(piece) -> (ui_only, tts_text)` helper. UI-only is the substring that the TTS sanitiser would have stripped — OpenUI fences, directive prefixes, sentinel tokens, and HTML tags. TTS-text is what survives sanitisation.

- UI-only fragment → published to the frontend immediately as a new event shape `{"response_ui": "<fragment>"}` on `FRONTEND_STREAM_TOPIC`
- TTS-text fragment → appended to the existing `text_buffer` and yielded to ElevenLabs at the same sentence-boundary cadence as today

The split runs *before* the existing fence-defer guard so a partial OpenUI fence at the tail still defers the TTS flush.

**Alternatives considered:**

- Forward the raw `response` event and split on the frontend: rejected. The frontend would have to duplicate the sanitisation regex set, and a future tweak to the worker's sanitiser would silently desync from the frontend's splitter.
- Stop forwarding `response` entirely and rely on LiveKit transcriptions for *all* bot text including OpenUI markup: rejected. Tried in the previous round; OpenUI markup is stripped before it reaches the TTS plugin, so the transcription channel never carries it, and the bubble never renders the card.
- Send the spoken text immediately *and* via TTS-aligned transcription, deduping on the frontend: rejected. Double source means double the failure modes; the frontend would have to reason about which copy is canonical.

### Decision 2: Frontend reads spoken text via `useTranscriptions()`, not via the data channel

`useVoiceMessages` already runs `useTranscriptions()` for STT (user) text. It will also read agent transcriptions (filtered by the agent participant identity) and append each new transcription's text to the active bot turn's `response`. Transcription updates arrive aligned with TTS audio frames, so the bubble fills as the agent speaks.

The handler dedupes by transcription `streamInfo.id` so re-renders do not re-append. When a new bot turn starts (next `main_response_complete`), the consumed-id set is rolled forward.

**Alternatives considered:**

- Custom worker channel that emits the spoken text on TTS playback events (`agent.transcription_finalized` etc.): rejected. We'd be re-implementing what LiveKit publishes for free, and a custom channel cannot align with audio frames the way the built-in transcript does.
- Append spoken text inside the `useVoiceMessages` bot-stream handler, gated on a worker-emitted timestamp: rejected. Worker has no audio-playback timing information at the point it parses SSE — TTS playback happens in the LiveKit room, not the LLM stream.

### Decision 3: Keep one `event.response_ui` shape for all UI-only fragments

The worker emits `{"response_ui": "<fragment>"}` even when the fragment is the entire chunk (i.e. the whole chunk was non-spoken). One shape keeps the frontend handler trivial: detect `response_ui`, append to `turn.response` (so the OpenUI parser sees it in the same string it always did), no special-casing.

We do **not** wrap it into a structured `{"type": "ui_fragment", "content": ...}` envelope. The frontend's existing fan-out (`if event.tool_data`, `if event.follow_up_actions`, etc.) is flat — a new flat key matches that style. No envelope = no marshalling layer to maintain on either side.

### Decision 4: Per-event UI/TTS split, no cross-event coalescing

Each backend event is split independently. We do not buffer UI fragments to coalesce across events — the moment we see a UI fragment, we publish it. This keeps OpenUI cards appearing as early as possible (the entire point of the immediate path) and matches the existing behaviour where every event is forwarded as it arrives.

The only buffering is the existing TTS sentence-boundary buffer, which only ever holds TTS-spoken text now.

### Decision 5: `useTranscriptions()` filtered by agent identity

`room.remoteParticipants` carries the agent's identity. The user transcription branch already filters by `localParticipant.identity`. The new bot branch filters by **not** local participant — every other transcription comes from the agent in our setup. A single combined `useTranscriptions()` subscription with two filtered effects (one for user, one for bot) keeps the hook count flat.

### Decision 6: Lock down the existing `history.replaceState` and gradient-mute paths via spec scenarios

The previous change implemented both. This change does not re-implement either — it adds **`#### Scenario:`** entries in the modified spec so a future refactor cannot silently regress them. Verification tasks in `tasks.md` cover manual end-to-end checks.

## Risks / Trade-offs

- **Risk:** TTS-aligned transcription latency might lag perceived audio by 100–300ms on some networks. → **Mitigation:** This is intrinsic to LiveKit's transcript publishing; the perceived effect is "bubble fills as agent speaks" rather than "bubble fills before agent speaks". The previous failure mode (bubble finishes seconds before audio) is strictly worse. If lag becomes a complaint, we can revisit by tuning ElevenLabs flush thresholds.
- **Risk:** OpenUI cards appear before the agent speaks the sentence that introduces them ("here's a draft" speech arrives after the card). → **Mitigation:** Explicit user trade-off from the directive ("open Ui tags ... should be sent as soon as seen to the frontend as they will not be the part of TTS speech anyways"). Document in the spec scenario so the trade-off is intentional, not a bug.
- **Risk:** TTS-aligned transcription might miss the final sentence if the worker disconnects abruptly. → **Mitigation:** Existing `main_response_complete` event still closes the turn from the data-channel side; the bubble will be whatever transcription reached the client before disconnect.
- **Risk:** Splitting the response per-event could miss an OpenUI fence that spans two events (one event ends mid-fence). → **Mitigation:** Reuse the existing `has_open_openui_fence_at_tail` defer logic. The worker buffers the *TTS* side until the fence closes; the *UI* side publishes whatever opening fence text was in the event. The OpenUI parser on the frontend tolerates partial fences (re-parses each render). If a follow-up parser bug surfaces, we can buffer UI fragments across events too, but per-event is the simplest correct default.
- **Risk:** Removing the `event.response` read path on the frontend breaks any other subscriber of `FRONTEND_STREAM_TOPIC`. → **Mitigation:** `VOICE_STREAM_TOPIC` is consumed by exactly one hook (`useVoiceMessages`). Grep confirms no other reader.
- **Trade-off:** Worker code grows by one helper and the per-event split adds two regex scans per chunk. The CPU cost is negligible compared to the network and LLM-stream costs.

## Migration Plan

- Pure code change. No data migration, no schema change, no backwards-compat shim.
- Roll forward only — once merged, the worker stops emitting `response` events on the data channel and starts emitting `response_ui`. Frontend changes ship in the same PR.
- Rollback: revert the PR. Worker resumes forwarding the raw `response`; frontend resumes reading it. The intermediate state during deploy (new worker, old frontend) would mean a few seconds of "spoken text missing from bubbles" — acceptable for a one-deploy gap given the worker is one process.

## Open Questions

None.
