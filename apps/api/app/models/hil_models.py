"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.constants.hil import HIL_DEFAULT_ENABLED


class HILPreferences(BaseModel):
    """Stored on the user document under ``hil_preferences``."""

    enabled: bool = HIL_DEFAULT_ENABLED
    always_allowed_tools: list[str] = Field(default_factory=list)


class HILToolRiskRecord(BaseModel):
    """Cached LLM classification for one CUSTOM-integration tool (Mongo
    ``hil_tool_risk``), for durability across restarts/processes.

    Supported/internal tools are never stored here — they resolve straight from
    the tool registry's ``destructive`` flag.
    """

    tool_name: str
    description_hash: str
    is_destructive: bool
    rationale: str = ""
    classified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
