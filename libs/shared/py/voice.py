"""LiveKit agent names shared by the API (which dispatches) and the voice worker (which registers).

The API mints every voice room with an explicit dispatch to one agent name, and
the worker registers under that name — so a room is only ever joined by its own
environment's worker. Without it, every worker on a LiveKit project auto-joins
every room, and development shares its project with staging. Both sides must
resolve the same name, which is why it lives here.
"""

from typing import Final

PRODUCTION_VOICE_AGENT_NAME: Final[str] = "gaia-voice"
DEVELOPMENT_VOICE_AGENT_NAME: Final[str] = "gaia-voice-dev"
_DEVELOPMENT_ENV: Final[str] = "development"


def voice_agent_name(env: str) -> str:
    """Return the agent name an environment's voice rooms are dispatched to."""
    return DEVELOPMENT_VOICE_AGENT_NAME if env == _DEVELOPMENT_ENV else PRODUCTION_VOICE_AGENT_NAME
