# apps/voice-agent

LiveKit-based voice agent worker for GAIA. Handles real-time voice sessions using Deepgram STT, ElevenLabs TTS, and a custom LLM adapter that streams responses from the GAIA backend.

## Key Commands

```bash
# Sync Python dependencies (run after pulling changes)
nx run voice-agent:sync

# Start the worker
nx dev voice-agent       # runs: uv run python -m src start

# Lint (ruff)
nx lint voice-agent      # runs: uvx ruff check src/

# Format (ruff)
nx format voice-agent    # runs: uvx ruff format src/

# Download model files (VAD/turn-detection)
cd apps/voice-agent && uv run python -m src download-files
```

## Architecture

```
src/
  __main__.py   — CLI entrypoint; dispatches `start` or `download-files`
  worker.py     — Core agent logic: CustomLLM, prewarm, entrypoint
  config.py     — VoiceAgentSettings (pydantic-settings + Infisical injection)
```

**CustomLLM** (`worker.py`): A `livekit.agents.llm.LLM` subclass that streams SSE from `POST /api/v1/chat-stream` on the GAIA backend. It flushes text to ElevenLabs TTS in sentence-sized chunks (flush at sentence boundary ≥40 chars, or hard flush at 120 chars) to minimize latency.

**Startup sequence**: `prewarm()` preloads the Silero VAD model in the worker process → `entrypoint()` is called per room → credentials (agent token + conversation ID) are extracted from LiveKit participant metadata JSON.

**Settings**: `VoiceAgentSettings` extends `BaseAppSettings` from `gaia-shared`. Secrets are injected via Infisical on first load. The voice agent loads `apps/api/.env` for shared Infisical bootstrap variables before loading its own config.

**Logging**: Structured JSON logs written to `./logs/` via `shared.py.logging.configure_file_logging` (picked up by Promtail in local dev).

## Code Style

- Dependency manager: **uv** (never pip directly)
- Linter/formatter: **ruff** (via `uvx ruff`)
- All imports at the top of the file — no inline imports (the `__main__.py` pattern of conditional imports in `try/except` is an existing exception for CLI dispatch only)
- All function parameters and return values must have type annotations
- Use `Optional[T]` for nullable values (already established pattern in the codebase)
- Do not create test files unless explicitly asked

## Gotchas

- The worker depends on `gaia-shared` (`libs/shared/py`) — run `nx run voice-agent:sync` (which first syncs `shared-python`) if shared code changes
- `DEEPGRAM_API_KEY` is consumed directly by the `livekit-plugins-deepgram` plugin via environment variable — it does not need to be passed explicitly in code
- Noise cancellation uses LiveKit's BVC (`noise_cancellation.BVC()`) — requires the `livekit-plugins-noise-cancellation` package
- Turn detection uses `MultilingualModel` from `livekit.plugins.turn_detector.multilingual` — model files must be downloaded before first run (`download-files` command)
- `preemptive_generation=True` and `use_tts_aligned_transcript=True` are set on `AgentSession` — do not remove these without understanding latency implications
- Docker image is published to `ghcr.io/theexperiencecompany/gaia-voice-agent` via `nx docker:build voice-agent`
