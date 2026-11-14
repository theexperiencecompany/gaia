"""Voice agent constants — SSE protocol tokens, TTS flush thresholds, compiled regexes."""

import re
from typing import Final

from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.context import AnalyticsContext


class LogTag:
    """Greppable bracketed prefixes for real-time log lines, one per area.

    Mirrors app.constants.log_tags.LogTag in the API: prefix every
    log.info / log.warning / log.error / log.debug message so a
    single token filters the area's logs (grep '\\[VOICE\\]' /
    |= "[VOICE-AGENT]"). Structured context still goes in log.set fields.
    """

    VOICE: Final[str] = "[VOICE]"  # config, utils, general worker
    AGENT: Final[str] = "[VOICE-AGENT]"  # agent.py — session/turn lifecycle


SSE_DATA_PREFIX = "data:"
# The frontend's data-channel topics: display events, and the session's conversation id and title.
FRONTEND_STREAM_TOPIC = "backend-stream-event"
CONVERSATION_ID_TOPIC = "conversation-id"
CONVERSATION_DESCRIPTION_TOPIC = "conversation-description"
# The events stream dropped (a deploy, a network blip): wait this long before following again.
FOLLOW_RECONNECT_DELAY_S = 1.0
# Spoken when a reply of this session fails: the reason is provider plumbing, not something to read aloud.
VOICE_ERROR_REPLY = "Sorry, something went wrong on my end. Please try again in a moment."

SENTENCE_ENDINGS = (".", "!", "?")

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


# Single \s before the attribute tail (not \s+): [^>] also matches whitespace,
# and the overlap between the two quantifiers is what makes backtracking blow up.
TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9_-]*(?:\s[^>]*)?/?>")
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
    "LogTag",
    "SSE_DATA_PREFIX",
    "FRONTEND_STREAM_TOPIC",
    "CONVERSATION_ID_TOPIC",
    "CONVERSATION_DESCRIPTION_TOPIC",
    "FOLLOW_RECONNECT_DELAY_S",
    "SENTENCE_ENDINGS",
    "TTS_MIN_SENTENCE_CHARS",
    "TTS_HARD_FLUSH_CHARS",
    "TTS_MIN_EMIT_CHARS",
    "TTS_FINAL_MIN_CHARS",
    "OPEN_TAG_DEFER_CAP",
    "PROMETHEUS_METRICS_PORT",
    "PROMETHEUS_MULTIPROC_DIR",
    "MIN_ENDPOINTING_DELAY_S",
    "TAG_RE",
    "MARKDOWN_RE",
    "WHITESPACE_RE",
    "OPENUI_FENCE_RE",
    "DIRECTIVE_PREFIX_RE",
    "OPEN_OPENUI_FENCE_TAIL_RE",
    "VOICE_SYSTEM_PROMPT",
]


#: Every voice-worker event is the user's own live call.
VOICE_SESSION_ANALYTICS: Final = AnalyticsContext(
    attribution=Attribution(
        actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.VOICE
    )
)
