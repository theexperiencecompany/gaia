"""Voice agent configuration settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from shared.py.logging import get_contextual_logger
from shared.py.secrets import inject_infisical_secrets
from shared.py.settings import BaseAppSettings

from pydantic_settings import SettingsConfigDict

logger = get_contextual_logger("config")

# Load API's .env for shared Infisical bootstrap vars
_api_env_path = Path(__file__).parent.parent.parent / "api" / ".env"
load_dotenv(_api_env_path)


class VoiceAgentSettings(BaseAppSettings):
    """Settings specific to the voice agent worker."""

    # Backend URL for chat-stream
    GAIA_BACKEND_URL: str = "http://localhost:8000"

    # ElevenLabs TTS
    ELEVENLABS_API_KEY: Optional[str] = None
    ELEVENLABS_VOICE_ID: Optional[str] = None
    ELEVENLABS_TTS_MODEL: str = "eleven_turbo_v2_5"

    # Deepgram STT (used by livekit-plugins-deepgram)
    DEEPGRAM_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )


_settings_instance: Optional[VoiceAgentSettings] = None


@lru_cache(maxsize=1)
def get_settings() -> VoiceAgentSettings:
    """Get cached settings instance."""
    global _settings_instance
    if _settings_instance is None:
        inject_infisical_secrets()
        _settings_instance = VoiceAgentSettings()
        logger.info("Voice agent settings initialized")
    return _settings_instance


def load_settings() -> VoiceAgentSettings:
    """Dynamically loads settings, triggering Infisical only on the first call."""
    return get_settings()


settings = get_settings()


__all__ = ["settings", "load_settings", "VoiceAgentSettings"]
