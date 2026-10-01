"""Comms directive protocol: the control tags and the outcomes they map to.

The tags comms emits when a turn is not worth a full message. Shared by the
prompts (which instruct comms) and the parser (which interprets comms' output)
so the two can never drift apart. Tag-shaped like NEW_MESSAGE_BREAKER.
"""

from enum import StrEnum

SILENCE_TAG = "SILENCE"
EMOJI_TAG = "EMOJI"
#: The line format the tags replaced ("REACT: 👍"). Only the parser reads it:
#: comms checkpoints written before the tags carry such turns, and a model
#: imitating its own history still emits them.
LEGACY_REACT_KEYWORD = "REACT"

#: The directives as the prompts show them to comms.
SILENCE_DIRECTIVE = f"<{SILENCE_TAG}>brief reason</{SILENCE_TAG}>"
EMOJI_DIRECTIVE = f"<{EMOJI_TAG}>one emoji</{EMOJI_TAG}>"


class CommsDirectiveKind(StrEnum):
    REPLY = "reply"
    SILENCE = "silence"
    REACT = "react"
