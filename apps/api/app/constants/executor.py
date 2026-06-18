"""Background executor constants.

Shared key names and internal markers used by the background executor run and
its handoff to the comms agent. Centralized so the executor runner, capture,
and any future consumers reference a single source of truth.
"""

# SSE frame key carrying the executor's narrated answer for voice-mode TTS.
# Must match VOICE_TTS_KEY in apps/voice-agent/src/constants.py — the voice
# agent matches on this exact string to decide what to speak.
VOICE_TTS_KEY = "voice_tts"

# Internal markers prefixing the executor result handed to comms as context.
# Comms re-voices the payload; these markers are stripped from its reply.
EXECUTOR_RESULT_MARKER = "[EXECUTOR_RESULT]"
EXECUTOR_ERROR_MARKER = "[EXECUTOR_ERROR]"
