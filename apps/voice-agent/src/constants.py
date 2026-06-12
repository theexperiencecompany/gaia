"""Voice agent constants — SSE protocol tokens, TTS flush thresholds, compiled regexes."""

import re

SSE_DATA_PREFIX = "data:"
DONE_SENTINEL = "[DONE]"
FRONTEND_STREAM_TOPIC = "backend-stream-event"
RESPONSE_KEY = "response"
MAIN_RESPONSE_COMPLETE_KEY = "main_response_complete"
# Backend sends this (voice-mode streams only) carrying a delegated executor's
# narrated answer for the agent to SPEAK. The frontend renders the same answer
# from its WebSocket push, so this is never forwarded to the UI — TTS only.
# Must match VOICE_TTS_KEY in apps/api/app/agents/core/background/executor_runner.py.
VOICE_TTS_KEY = "voice_tts"

# TTS flush thresholds (chars)
TTS_MIN_SENTENCE_CHARS = 40
TTS_HARD_FLUSH_CHARS = 120
TTS_MIN_EMIT_CHARS = 15
TTS_FINAL_MIN_CHARS = 1

# Cap on how many times a flush is deferred while a tag straddles chunk boundaries
OPEN_TAG_DEFER_CAP = 4

# Prometheus metrics server (lk_agents_* worker metrics, scraped by the
# observability stack). 9102 avoids the ARQ worker's 9100 when both run
# natively on one host. The multiproc dir lets prometheus_client aggregate
# metrics from LiveKit's forked job processes into the main worker's /metrics.
PROMETHEUS_METRICS_PORT = 9102
# World-readable metric shards only — nothing sensitive lands in this directory.
PROMETHEUS_MULTIPROC_DIR = "/tmp/voice-agent-prometheus"  # nosec B108  # NOSONAR python:S5443

# Minimum silence (s) after the user stops speaking before their turn is declared
# complete. Raised above LiveKit's 0.5s default so a brief mid-thought pause does
# not cut the user off; the MultilingualModel still extends up to its max delay
# when it predicts the user will continue.
MIN_ENDPOINTING_DELAY_S = 0.8

# aiohttp sock_read timeout (s) for the backend chat-stream request. MUST exceed
# the backend's VOICE_EXECUTOR_RESULT_TIMEOUT_S (90s): on a delegated turn the
# backend parks the SSE stream with no bytes on the wire while it waits for the
# executor, so a shorter read timeout would abort the turn and lose the spoken
# answer before it is sent.
BACKEND_REQUEST_TIMEOUT_S = 120.0

TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*(?:\s+[^>]*)?/?>")
# Message-break sentinel only. TAG_RE (run earlier) strips the bracketed
# <NEW_MESSAGE_BREAK> form; this catches any unbracketed residue. Matching the
# FULL token name (never the bare word "new") so ordinary prose is left intact.
SENTINEL_RE = re.compile(r"NEW_MESSAGE_BREAK")
MARKDOWN_RE = re.compile(r"[*_#`]")
WHITESPACE_RE = re.compile(r"\s+")
# Fenced OpenUI blocks: ":::openui ... :::" or unterminated tail at end of stream.
# The lazy quantifier DOES expand (verified): "\Z" only matches at end-of-input,
# so the alternation is position-anchored, not an always-empty match.
OPENUI_FENCE_RE = re.compile(r":::openui[\s\S]*?(?::::|\Z)")  # NOSONAR python:S6019
# Lingering ":::directive" prefixes after fence stripping (defence in depth)
DIRECTIVE_PREFIX_RE = re.compile(r":::[a-zA-Z]+\b")
# Open OpenUI fence at the tail of a buffer (used to defer TTS flush)
OPEN_OPENUI_FENCE_TAIL_RE = re.compile(r":::openui(?![\s\S]*:::)")

VOICE_SYSTEM_PROMPT = (
    "You are a voice assistant. Respond in spoken, conversational language. "
    "Use short sentences. No lists, no bullet points, no markdown, no code blocks, "
    "no headings. Do not use symbols or special characters. "
    "Answer directly without preamble. "
    "When uncertain, say so briefly rather than giving a long hedged answer."
)

__all__ = [
    "SSE_DATA_PREFIX",
    "DONE_SENTINEL",
    "FRONTEND_STREAM_TOPIC",
    "RESPONSE_KEY",
    "MAIN_RESPONSE_COMPLETE_KEY",
    "VOICE_TTS_KEY",
    "TTS_MIN_SENTENCE_CHARS",
    "TTS_HARD_FLUSH_CHARS",
    "TTS_MIN_EMIT_CHARS",
    "TTS_FINAL_MIN_CHARS",
    "OPEN_TAG_DEFER_CAP",
    "PROMETHEUS_METRICS_PORT",
    "PROMETHEUS_MULTIPROC_DIR",
    "MIN_ENDPOINTING_DELAY_S",
    "BACKEND_REQUEST_TIMEOUT_S",
    "TAG_RE",
    "SENTINEL_RE",
    "MARKDOWN_RE",
    "WHITESPACE_RE",
    "OPENUI_FENCE_RE",
    "DIRECTIVE_PREFIX_RE",
    "OPEN_OPENUI_FENCE_TAIL_RE",
    "VOICE_SYSTEM_PROMPT",
]
