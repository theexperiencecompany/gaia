"""The attribution every server and voice event carries: who acted, what started the run, and where."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Actor(StrEnum):
    """Who performed the action: a human request in this turn, or the agent acting on its own."""

    USER = "user"
    AGENT = "agent"


class Trigger(StrEnum):
    """What started the run an event belongs to."""

    INTERACTIVE = "interactive"
    SCHEDULE = "schedule"
    INTEGRATION_TRIGGER = "integration_trigger"
    WEBHOOK = "webhook"
    SYSTEM = "system"


class EntrySurface(StrEnum):
    """Where the run entered GAIA; WORKER is work no client started."""

    WEB = "web"
    DESKTOP = "desktop"
    BOT = "bot"
    VOICE = "voice"
    WORKER = "worker"


class Attribution(BaseModel):
    """The base properties stamped onto every attributed event by its surface's capture function."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: Actor
    trigger: Trigger
    surface: EntrySurface


__all__ = ["Actor", "Attribution", "EntrySurface", "Trigger"]
