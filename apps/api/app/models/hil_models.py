"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.constants.hil import HIL_DEFAULT_ENABLED


class HILPreferences(BaseModel):
    """Stored on the user document under ``hil_preferences``."""

    enabled: bool = HIL_DEFAULT_ENABLED
    # Per-tool overrides of the default (curated) gating: tool name -> should-ask.
    # A tool absent from the map uses its default classification. Holds only the
    # tools the user explicitly flipped, so it stays small and survives changes
    # to the defaults.
    tool_overrides: dict[str, bool] = Field(default_factory=dict)


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
