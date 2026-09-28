"""Parse comms' narration output into a turn outcome: reply, silence, or reaction.

When comms narrates a background executor update that is not worth a full message,
its output is a single control line instead of prose:

    SILENCE: <reason>  → deliver nothing (the reason is logged, not shown)
    REACT: <emoji>     → deliver a lightweight emoji acknowledgment

Anything else is an ordinary reply. Parsing is strict — the whole trimmed message
must be one control line — so prose that merely mentions the word never triggers
it, and the safe failure is "treat as a normal reply" (a stray directive shows as
text) rather than silently dropping a real message.
"""

import re

from app.constants.comms import REACT_KEYWORD, SILENCE_KEYWORD, CommsDirectiveKind
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.agent_models import CommsDirective

# Single logical line only (no DOTALL/MULTILINE): a real directive is one line,
# so any multi-line reply falls through to REPLY and can never be mis-silenced.
_DIRECTIVE_RE = re.compile(rf"^({SILENCE_KEYWORD}|{REACT_KEYWORD}):[ \t]*(.*)$", re.IGNORECASE)


def interpret_comms_output(text: str) -> CommsDirective:
    """Classify comms' final narration text as a reply, a silence, or a reaction."""
    match = _DIRECTIVE_RE.match(text.strip())
    if match:
        # Comms ends every reply with the bubble separator; it is never payload.
        keyword = match.group(1).upper()
        payload = match.group(2).replace(NEW_MESSAGE_BREAKER, "").strip()
        if keyword == SILENCE_KEYWORD:
            return CommsDirective(CommsDirectiveKind.SILENCE, payload)
        # A REACT with no emoji is meaningless: a break-only payload falls
        # through to REPLY instead of rendering an empty reaction.
        if payload:
            return CommsDirective(CommsDirectiveKind.REACT, payload)
    return CommsDirective(CommsDirectiveKind.REPLY, text)
