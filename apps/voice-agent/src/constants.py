"""Voice agent constants — SSE protocol tokens, TTS flush thresholds, compiled regexes."""

import re

SSE_DATA_PREFIX = "data:"
DONE_SENTINEL = "[DONE]"
FRONTEND_STREAM_TOPIC = "backend-stream-event"
RESPONSE_KEY = "response"
RESPONSE_UI_KEY = "response_ui"
MAIN_RESPONSE_COMPLETE_KEY = "main_response_complete"

# TTS flush thresholds (chars)
TTS_MIN_SENTENCE_CHARS = 40
TTS_HARD_FLUSH_CHARS = 120
TTS_MIN_EMIT_CHARS = 15
TTS_FINAL_MIN_CHARS = 1

# Cap on how many times a flush is deferred while a tag straddles chunk boundaries
OPEN_TAG_DEFER_CAP = 4

TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*(?:\s+[^>]*)?/?>")
# Word boundaries prevent mangling substrings like "RENEW", "KNEW", "NEWEST"
SENTINEL_RE = re.compile(r"\b(_BREAK|_MESSAGE|NEW)\b")
MARKDOWN_RE = re.compile(r"[*_#`]")
WHITESPACE_RE = re.compile(r"\s+")
# Fenced OpenUI blocks: ":::openui ... :::" or unterminated tail at end of stream
OPENUI_FENCE_RE = re.compile(r":::openui[\s\S]*?(?::::|\Z)")
# Lingering ":::directive" prefixes after fence stripping (defence in depth)
DIRECTIVE_PREFIX_RE = re.compile(r":::[a-zA-Z]+\b")
# Open OpenUI fence at the tail of a buffer (used to defer TTS flush)
OPEN_OPENUI_FENCE_TAIL_RE = re.compile(r":::openui(?![\s\S]*:::)")

VOICE_SYSTEM_PROMPT = (
    "You are a voice assistant. Respond in spoken, conversational language. "
    # "Use short sentences. No lists, no bullet points, no markdown, no code blocks, "
    "no headings. Do not use symbols or special characters. "
    "Answer directly without preamble. "
    "When uncertain, say so briefly rather than giving a long hedged answer."
)

__all__ = [
    "SSE_DATA_PREFIX",
    "DONE_SENTINEL",
    "FRONTEND_STREAM_TOPIC",
    "RESPONSE_KEY",
    "RESPONSE_UI_KEY",
    "MAIN_RESPONSE_COMPLETE_KEY",
    "TTS_MIN_SENTENCE_CHARS",
    "TTS_HARD_FLUSH_CHARS",
    "TTS_MIN_EMIT_CHARS",
    "TTS_FINAL_MIN_CHARS",
    "OPEN_TAG_DEFER_CAP",
    "TAG_RE",
    "SENTINEL_RE",
    "MARKDOWN_RE",
    "WHITESPACE_RE",
    "OPENUI_FENCE_RE",
    "DIRECTIVE_PREFIX_RE",
    "OPEN_OPENUI_FENCE_TAIL_RE",
    "VOICE_SYSTEM_PROMPT",
]
