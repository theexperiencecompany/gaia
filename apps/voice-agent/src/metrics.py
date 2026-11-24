"""Count every voice session by how it ended, the signal the voice-session alert reads.

ok is a session that closed for any reason but an error; error is one LiveKit closed
because a model or the room failed. Both series are created at zero in each job process,
so the first error is an increase increase() can see. The counter lives in the default
registry, which LiveKit's worker serves on PROMETHEUS_METRICS_PORT and, through the
multiprocess directory, aggregates across the forked job processes.
"""

from enum import StrEnum

from prometheus_client import Counter


class VoiceSessionOutcome(StrEnum):
    """How one voice session ended."""

    OK = "ok"
    ERROR = "error"


VOICE_SESSION_TOTAL = Counter(
    name="gaia_voice_session_total",
    documentation="Voice sessions by outcome; error is a session LiveKit closed because of an error",
    labelnames=("outcome",),
)


def create_voice_session_series() -> None:
    """Create every voice-session series at zero, so its first increment is visible."""
    for outcome in VoiceSessionOutcome:
        VOICE_SESSION_TOTAL.labels(outcome.value)
