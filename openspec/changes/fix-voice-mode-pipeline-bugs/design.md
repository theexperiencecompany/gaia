## Context

The voice-agent worker was refactored to split monolithic `worker.py` into `agent.py`, `llm.py`, `utils.py`, `constants.py`, `config.py`. Two startup bugs (LIVEKIT_URL missing, MultilingualModel in prewarm) were fixed in a follow-up. A live test session on 2026-05-24 produced `apps/voice-agent/logs/gaia-2026-05-24.log` and `errors-2026-05-24.log`, which surfaced six residual defects in the runtime pipeline. They span three layers: shared Python secrets bootstrap, voice-agent Python (LLM stream + sanitizer + logger), and Next.js voice-mode hooks. None of the defects have specs today, so they must be added to the `voice-mode` capability that `unify-voice-mode-with-text-ui-and-gradient` introduced and `fix-voice-mode-bugs-and-ux` extended.

Two constraints shape every decision below:

1. The backend `POST /api/v1/chat-stream` SSE contract is owned by `apps/api` and out of scope. Frontend and worker must adapt.
2. LiveKit on Linux uses `forkserver`. Each `JobProcess` is a fresh interpreter that re-imports modules, but **environment variables set in the parent ARE inherited** by forkserver children. This is the lever for the Infisical fix.

## Goals / Non-Goals

**Goals:**
- Eliminate Infisical network calls on JobProcess respawn after the first parent-process bootstrap. Target room-join cost from cold child: under 200ms of secret-related work.
- Ensure TTS never speaks OpenUI fence content, tool-output text, or directive prefixes, even on adversarial backend output.
- Align frontend bot-bubble text with TTS playback so the chat bubble does not race ahead of the spoken audio.
- Keep the user transcription visible in the chat surface for every turn, including preemptive turns where the bot starts before STT finalises.
- Stop the spectrum analyser pipeline from doing wall-clock work when the mic is muted or the tab is hidden.
- Make the structured logger crash-safe against token content that contains `{` / `}` characters.

**Non-Goals:**
- Reducing prewarm count (`num_idle_processes`). The four-process pool is correct for concurrency.
- Caching Infisical secrets to disk. `os.environ` inheritance is enough.
- Reworking the backend SSE event schema. Worker-side filtering is sufficient.
- Replacing Loguru with another logger.
- Adding GPU-shader-level performance work to the gradient. Mute/visibility gating is the cheap, correct fix.
- Rewriting `useVoiceMessages` end-to-end. This change only relaxes the bot-turn guard.

## Decisions

### Decision 1: Move Infisical fetch entirely to the worker main process

The main process already calls `inject_infisical_secrets()` from `start_worker()` and `download_files()` (added in the earlier startup fix). Once those env vars are set in the main process, forkserver children inherit them automatically. The redundant call happens because `bootstrap_settings()` in `apps/voice-agent/src/config.py` calls `inject_infisical_secrets()` again from each child's `prewarm()`.

Fix scope: `apps/voice-agent/src/config.py` only. Remove the `inject_infisical_secrets()` call from `bootstrap_settings()`; have it just construct settings from the inherited environment. The shared `libs/shared/py/secrets.py` is NOT touched, because the duplication is a voice-agent local bug, not a shared-lib concern.

**Alternatives considered:**
- *Sentinel env var inside `inject_infisical_secrets()`* — was the original plan; rejected because other apps (`api`, `bots`) call Infisical exactly once at startup already and don't benefit. Adding guard logic to a shared utility for one consumer's bug is wrong layering.
- *Set `num_idle_processes` higher to reduce respawns* — masks the bug, does not eliminate it.
- *Keep Infisical call in child but skip when `LIVEKIT_URL` is already set* — equivalent in effect but ties the guard to a specific secret name; cleaner to just drop the call.

Safety: if a JobProcess somehow starts without inherited env (e.g., LiveKit changes to `spawn` instead of `forkserver`), the failure mode is a clear missing-env error from `VoiceAgentSettings()` validation, not a silent runtime bug. We accept that.

### Decision 2: Event-type gate before TTS, regex sanitiser as defence-in-depth

In `CustomLLM.gen()`, classify each backend SSE event:
- `response` → spoken candidate text (still pass through sanitizer)
- `tool_data`, `tool_output`, `main_response_complete`, `conversation_id`, `conversation_description`, `follow_up_actions` → frontend only, never TTS
- Anything containing `:::openui` markers in a `response` field → drop the OpenUI block, keep prose before / after

`sanitize_for_tts` gains two extra steps applied in this order:
1. Strip fenced OpenUI blocks: `r":::openui[\s\S]*?(?::::|\Z)"` (non-greedy, terminates on closing `:::` or end-of-string for streaming-tail cases).
2. Strip directive prefixes: `r":::[a-zA-Z]+\b"`.

The existing `TAG_RE`, `SENTINEL_RE`, `MARKDOWN_RE`, `WHITESPACE_RE` chain stays.

**Alternatives considered:**
- *Backend changes to never emit OpenUI under `response`* — owned by another team, longer cycle, does not protect against future regressions.
- *Block the full turn if any OpenUI is detected* — kills the leading prose that should be spoken.

### Decision 3 (revised): Forward every backend event as-is; sanitise only the TTS path

The frontend is the canonical renderer of bot content: `response` text contains OpenUI fenced blocks (`:::openui ... :::`) and other markup that the chat renderer parses into tool cards, code blocks, and inline UI. Delaying that text until TTS playback (the original Decision 3) made tool cards appear late and, when TTS-aligned segments did not arrive on time, made the bubble blank.

Revised approach:
- **Worker**: forward every backend SSE payload (response, tool_data, follow_up_actions, main_response_complete, etc.) to the frontend on `backend-stream-event` immediately on receipt. No filtering. The frontend bubble fills as the backend streams.
- **TTS sanitisation**: still applied — `sanitize_for_tts` strips `:::openui` fenced blocks, directive prefixes, HTML tags, sentinels, and markdown so ElevenLabs never speaks UI markup. The text appended to the TTS buffer is the value of `response` events only; plumbing events never enter the TTS buffer.
- **Frontend**: `useVoiceMessages` consumes `event.response` from the custom topic into `turn.response`. No bot-transcription effect. `activeTurnRef` is cleared on `main_response_complete` so the next bot turn opens fresh; the previous bug where new tool_data appended to the prior bubble is fixed by restoring this clear.

This trades TTS/text playback alignment (which the previous design tried to enforce) for predictable, real-time text rendering — the user's explicit preference.

**Alternatives considered (and rejected):**
- *TTS-aligned transcript routing via `useTranscriptions()`* — what the previous revision shipped. Caused two regressions: (a) the chat bubble was sometimes empty because LiveKit's transcription channel didn't always carry every TTS chunk reliably; (b) tool cards rendered late because they waited on the TTS path. The user reported both.
- *Worker subscribes to `conversation_item_added` and forwards on the custom topic* — fires once per complete message, not per chunk.
- *Install a custom `io.TextOutput`* — duplicates the framework's work.

### Decision 4: Let user groups survive preemptive bot turns

`useVoiceMessages` line 216 returns early when `activeTurnRef.current !== null`. Replace this with a "start a *new* user group keyed on the post-bot transcription id" path:
- If a STT-final transcription arrives while a bot turn is active, open a new user group with `startedAt = max(now, activeTurn.startedAt + 1ms)` so the createdAt sort places it after the active bot turn.
- The next bot-turn open then closes that user group as today.

This makes the chat surface look like: `[user A] [bot for A] [user B mid-stream] [bot for B]`. Users see their second utterance even if the bot was still finishing speaking the previous response.

**Alternatives considered:**
- *Discard preemptive bot turns when a new user STT arrives* — defeats the latency benefit of `preemptive_generation=True`.
- *Show the user transcription as a small "you said while listening:" caption* — extra UI surface, inconsistent with text mode.

### Decision 5: Cancel the spectrum raf loop on mute and `document.hidden`

In `useVoiceSpectrum`:
- Replace the in-tick mute attenuation (`out[i] = out[i] * 0.85`) with an effect that cancels `rafRef.current` when `mutedRef.current && sourceRef.current === "mic"`. Restart on unmute.
- Add a `visibilitychange` listener that cancels the raf when `document.hidden` and restarts on visibility.
- The agent-track analyser pipeline is unaffected. The `loading` and `synthetic` sources continue running because they have no audio source to gate.

This reduces tick rate from 60fps to 0fps in the muted-and-mic-source case, eliminating both the GPU spike and the perceived "reacts when muted" behaviour (the residual decay is what users saw moving).

**Alternatives considered:**
- *Render at a lower FPS when muted* — does not address the "reacts when muted" perception.
- *Disconnect the AnalyserNode on mute* — works but adds churn on every mute toggle; raf cancel is simpler.

### Decision 7: Update URL via `window.history.replaceState`, not `router.replace`

When a fresh `/c` voice session discovers its `conversation_id`, the old code called `router.replace("/c/<id>")`. App Router treats `/c` and `/c/[id]` as distinct segments, so the call remounts `ChatPage` → recreates the LiveKit `Room` → tears down the in-flight session. The user loses the first transcription, the first bot response, and the first TTS chunk.

Fix: use `window.history.replaceState(window.history.state, "", newUrl)` to update the URL in place without triggering Next.js navigation. The React tree, the Room, and the voice session stay mounted. `voiceModeStore.discoveredConversationId` is the canonical conversation id during the voice session; `convoIdParam` becomes correct after the user navigates away and back.

**Alternatives considered:**
- *Lift `VoiceControlBarContainer` into the `(main)` layout* — would survive route changes within the group but breaks the chat-scoped session ownership model.
- *Use Next.js shallow routing* — not supported in App Router; `window.history.replaceState` is the recommended escape hatch.
- *Defer the redirect until voice mode ends* — works, but the URL stays at `/c` during the entire call which breaks link sharing.

### Decision 6: Pass token content as logger kwargs only

In `llm.py` the offending line is:

```python
logger.debug(f"[{now_ts()}] ≈ TOKEN #{total_tokens} | {piece!r}", phase="token", token=piece, ...)
```

Loguru scans the message string for `{name}` placeholders even with `!r` repr. When `piece` is a JSON string like `'{"label": "..."}'`, repr produces `'{"label": "..."}'` which still contains `{"label"}` patterns interpreted as named placeholders.

The fix: move `piece` out of the message string. Use `logger.bind(token=piece).debug(f"[{now_ts()}] ≈ TOKEN #{total_tokens}")` *or* construct the message with `str.replace("{", "{{").replace("}", "}}")` on the inserted content. Decision: use `logger.opt(raw=True)` is not appropriate (also disables level / time); instead, pre-escape braces in any user-content interpolated into the message string, and move full content to kwargs.

Apply the same rule to `TTS FLUSH`, `TTS FINAL`, `BACKEND EVENT`, `STT FINAL`, `STT INTERIM`, and `FORWARD FRONTEND` log lines in `llm.py` and `agent.py`. Going forward, the project rule (already in `.claude/rules/python.md`) is "never f-string user content into log messages"; this change retrofits the existing voice agent.

**Alternatives considered:**
- *Switch off Loguru's brace parsing globally* — affects every other call site, easy to miss.
- *Truncate `piece` to a fixed length* — does not solve the brace problem, just hides it for short tokens.

## Risks / Trade-offs

- **Sentinel env var collisions** → Mitigation: namespace under `GAIA_` prefix (`GAIA_INFISICAL_BOOTSTRAPPED`). Document in `libs/shared/CLAUDE.md`.
- **Forced env-var skip blocks intentional re-fetch on secret rotation** → Mitigation: secret rotation in production requires a worker redeploy regardless; explicit `force=True` parameter on `inject_infisical_secrets` for the rare manual case, defaulted to False.
- **OpenUI fence regex matches inside an inline code span** → Mitigation: the `:::openui` prefix is reserved syntax; backend never emits it inside arbitrary user text. If a future backend change does, the worst case is missing a few words of TTS prose, not crashing.
- **TTS-aligned transcript event order vs raw SSE event order for plumbing** → Mitigation: keep plumbing payloads on the raw path so `conversation_id` / `tool_data` continue to arrive on the frontend in real time. Only `response` text moves to the aligned path.
- **`useVoiceMessages` change creates two adjacent user groups when the user pauses mid-utterance** → Existing behaviour grouped consecutive transcriptions into one bubble with `NEW_MESSAGE_BREAK`. The change keeps that grouping inside a single bot-turn-bounded window. The cross-bot-turn case (which today silently drops the second utterance) becomes a second bubble. This is the desired UX.
- **raf cancel on mute racing with toggleMute** → Mitigation: tick scheduler reads `mutedRef.current` synchronously; toggleMute updates the ref before issuing setState.

## Migration Plan

This is an internal-only change. Deploy order:

1. Ship the `gaia-shared/secrets.py` sentinel change (backwards-compatible; existing call sites still work).
2. Ship the worker changes (Decision 2, 3, 6) and frontend changes (Decision 4, 5) together so the frontend's text alignment expectation matches the worker's emit pattern.
3. Rollback: revert the two commits. The sentinel env var is harmless if the second commit is reverted alone (the worker will still skip the duplicate fetch).

## Open Questions

- Should the TTS-aligned forward also include a token-index field so the frontend can deduplicate against any raw-path leakage during the rollout window? Tentatively no; the raw path will no longer carry `response` fields after this change, so there is nothing to deduplicate against.
- Should the user-group split insert a visible separator in the chat (e.g. a thin divider) so users can tell that the bot answered between two of their utterances? Defer to a follow-up UX pass.
