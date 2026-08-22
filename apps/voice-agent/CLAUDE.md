# apps/voice-agent

LiveKit-based voice agent worker for GAIA. Handles real-time voice sessions using Deepgram STT, ElevenLabs TTS, and a custom LLM adapter that streams responses from the GAIA backend.

## Key Commands

```bash
# Sync Python dependencies (run after pulling changes)
nx run voice-agent:sync

# Start the worker
nx dev voice-agent       # runs: uv run python -m src start

# Lint (ruff)
nx lint voice-agent      # runs: uv run --group dev ruff check src/

# Format (ruff)
nx format voice-agent    # runs: uv run --group dev ruff format src/

# Download model files (VAD/turn-detection)
cd apps/voice-agent && uv run python -m src download-files
```

## Architecture

```
src/
  __main__.py   — CLI entrypoint; dispatches `start` or `download-files`
  agent.py      — prewarm(), entrypoint(), start_worker(), download_files()
  llm.py        — CustomLLM class (SSE streaming + TTS chunking)
  config.py     — VoiceAgentSettings + bootstrap_settings() for Infisical
  constants.py  — SSE tokens, TTS thresholds, compiled regexes, system prompt
  utils.py      — sanitize_for_tts, extract_meta_data, now_ts, ms_since
```

**CustomLLM** (`llm.py`): A `livekit.agents.llm.LLM` subclass that streams SSE from `POST /api/v1/chat-stream` on the GAIA backend. It reuses a single `aiohttp.ClientSession` across turns and flushes text to ElevenLabs TTS in sentence-sized chunks (flush at sentence boundary ≥40 chars, or hard flush at 120 chars) to minimize latency.

**Startup sequence**: `start_worker()` calls `inject_infisical_secrets()` once in the main process before `cli.run_app()` (`download_files()` skips it — it only fetches public model files, so it can run at Docker-build time with no secrets). Each forked `JobProcess` inherits the resulting env vars and calls `prewarm()`, which calls `bootstrap_settings()` to build `VoiceAgentSettings` from the inherited environment (no network I/O) and loads the Silero VAD model into `proc.userdata`. `MultilingualModel` is constructed per room inside `entrypoint()` because its `__init__` needs a job context. `entrypoint()` reads settings + VAD from `ctx.proc.userdata` — zero Infisical calls per room.

**Settings**: `VoiceAgentSettings` extends `BaseAppSettings` from `gaia-shared`. `bootstrap_settings()` is pure: it just constructs the cached settings object. Infisical lives in the main process only because LiveKit's `forkserver` on Linux inherits the parent's env vars into every child.

**Logging**: Structured JSON logs written to `apps/voice-agent/logs/` (absolute path) via `shared.py.logging.configure_file_logging` (picked up by Promtail in local dev; a no-op under `LOG_FORMAT=json`, where stdout NDJSON goes to Loki instead). Set `LOG_LEVEL=DEBUG` to enable full per-token, per-TTS-flush, per-STT, and per-participant debug timeline logs with `HH:MM:SS.mmm` timestamps and millisecond latency measurements.

## Wide events and the observability gate

The worker uses the same wide-event facade as the API (`from shared.py.wide_events import log`), but **there is no middleware here** — nothing opens an event for you. A voice entry point must open its own boundary with `async with log_context(...)` / `wide_task(...)`; inside it, `log.set(...)` / `log.set_ns(...)` attach canonical `VoiceContext` fields and `log.warning(...)` / `log.error(...)` also land in the event's `warnings[]`/`errors[]`.

**A bare `log.set()` proves nothing here.** Outside a boundary it is silently discarded — no error, no line, the fields simply never reach Loki. This is the one place the voice rules are stricter than the ARQ worker rules, where a `log.set()` alone is accepted.

The entry points are not a hardcoded list: `tools/evlog_map/voice.py` parses `WorkerOptions(entrypoint_fnc=…, prewarm_fnc=…)` in `agent.py` and the per-turn coroutine behind `CustomLLM.chat` in `llm.py`, so rewiring the worker moves the gate with it. Score the surface with `python3 tools/evlog_map` (it covers `apps/api/app` **and** `apps/voice-agent/src`); CI gates it per-file against the merge base plus a discovery floor (`--min-entries`). Waive a check that genuinely does not apply with `# evlog-map-disable-next-line <check-id> -- <reason>` — the `--` reason is mandatory.

## Code Style

- Dependency manager: **uv** (never pip directly)
- Linter/formatter: **ruff** (via `uv run --group dev ruff`, pinned by the root uv.lock)
- All imports at the top of the file — no inline imports (the `__main__.py` pattern of conditional imports in `try/except` is an existing exception for CLI dispatch only)
- All function parameters and return values must have type annotations. Use `Any` only for genuinely untyped third-party code.
- Python 3.11+: use modern syntax (`X | None` unions, `match` statements).
- Do not create test files unless explicitly asked

### Tooling and the autofix hook

After every `.py` edit, a PostToolUse hook runs `uv run --project apps/api --group dev ruff format` then `... ruff check --fix` on the file. Formatting, import order/grouping, `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, lowercase generics, unused imports, mutable default args, bare `except`, and `print` are corrected automatically — do not hand-fix them.

What the hook does NOT fix, you handle manually: lint warnings ruff can't auto-resolve (`nx lint voice-agent`, read the rule, fix the cause) and type correctness (there is no `nx type-check` target for voice-agent; keep full annotations and run `uvx mypy src` if you need a type pass). Fix the cause, never silence it.

## Structure & Service Conventions

- One domain per file. Never let a file accumulate unrelated logic across domains.
- Business logic as async module-level functions, not service classes with `__init__`/instance state. If grouping is needed, use `@staticmethod` only — never `self`.
- Code reused across `api`, `voice-agent`, and `bots` belongs in `libs/shared/py/` and is imported via `gaia-shared` — never copied into app code.
- Extract literal values that carry meaning into named constants; no magic strings or numbers.

## Anti-Patterns

- No blocking I/O in async paths — all I/O must be `async`.
- No `time.sleep()` — use `asyncio.sleep()`; use `asyncio.gather()` for concurrent independent ops.
- No global mutable state — pass dependencies explicitly.
- No copying logic from `gaia-shared` into app code — import it.

## Gotchas

- The worker depends on `gaia-shared` (`libs/shared/py`) — run `nx run voice-agent:sync` (which first syncs `shared-python`) if shared code changes
- `DEEPGRAM_API_KEY` is consumed directly by the `livekit-plugins-deepgram` plugin via environment variable — it does not need to be passed explicitly in code
- Noise cancellation uses LiveKit's BVC (`noise_cancellation.BVC()`) — requires the `livekit-plugins-noise-cancellation` package
- Turn detection uses `MultilingualModel` from `livekit.plugins.turn_detector.multilingual` — model files must be downloaded before first run (`download-files` command)
- `preemptive_generation=True` and `use_tts_aligned_transcript=True` are set on `AgentSession` — do not remove these without understanding latency implications
- Docker image is published to `ghcr.io/theexperiencecompany/gaia-voice-agent` via `nx docker:build voice-agent`
