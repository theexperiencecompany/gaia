"""Voice agent configuration settings."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import SettingsConfigDict

from shared.py.logging import get_contextual_logger
from shared.py.settings import BaseAppSettings

logger = get_contextual_logger("config")

# Load API's .env for shared Infisical bootstrap vars
_api_env_path = Path(__file__).parent.parent.parent / "api" / ".env"
load_dotenv(_api_env_path)


class VoiceAgentSettings(BaseAppSettings):
    """Settings specific to the voice agent worker."""

    GAIA_BACKEND_URL: str = "http://localhost:8000"

    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_VOICE_ID: str | None = None
    ELEVENLABS_TTS_MODEL: str = "eleven_turbo_v2_5"

    # Consumed by livekit-plugins-deepgram via env var — not passed explicitly in code
    DEEPGRAM_API_KEY: str | None = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> VoiceAgentSettings:
    """Return the cached settings instance, constructing it on first call.

    ``VoiceAgentSettings`` reads ``os.environ`` at construction time, so
    Infisical secrets must already be injected (``start_worker()`` does this)
    before the first call — otherwise the cached instance is built from an
    incomplete environment.
    """
    return VoiceAgentSettings()


def bootstrap_settings() -> VoiceAgentSettings:
    """
    Build settings from the inherited process environment. No network I/O.

    Infisical is contacted exactly once in the worker host process from start_worker()
    before LiveKit's forkserver is initialised. Forkserver
    children inherit the parent's os.environ, so each JobProcess's prewarm() reads
    its config from the inherited env without re-fetching from Infisical.
    """
    settings = get_settings()
    logger.info("Voice agent settings initialized")
    return settings


__all__ = ["VoiceAgentSettings", "bootstrap_settings", "get_settings"]
