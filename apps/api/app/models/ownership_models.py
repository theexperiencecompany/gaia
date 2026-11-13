"""What comms hands the executor about the outcome a request is for, and how to tell the user."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.constants.agents import TimeHorizon
from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource


class DeliveryTiming(StrEnum):
    """When the person who created the producer wants to hear about it."""

    THE_MOMENT = "the_moment"
    AT_TIME = "at_time"
    WHEN_DONE = "when_done"


class DeliveryPolicy(BaseModel):
    """When, and where, the creator of a producer wants to hear, set at creation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timing: DeliveryTiming = DeliveryTiming.WHEN_DONE
    may_wake: bool = False
    #: The chat app the user asked to be told on; None leaves it to where they are active.
    channel: ConversationSource | None = None
    #: False when the user turned this producer's updates off: only what needs them gets through.
    notify: bool = True
    #: Told at this instant and not before; the creator's own timing ("tonight", "after my meeting").
    not_before: datetime | None = None
    #: Told by this instant at the latest; a hold for anything else never outlasts it.
    by: datetime | None = None

    @model_validator(mode="after")
    def _channel_is_a_chat_app(self) -> Self:
        if self.channel is not None and self.channel not in BOT_CONVERSATION_SOURCES:
            raise ValueError(f"{self.channel.value} is not a chat app a message can be sent to")
        return self


@dataclass(frozen=True)
class ExecutorIntent:
    """The structured half of an executor brief: the real goal, how far it reaches, how to tell the user."""

    desired_outcome: str
    time_horizon: TimeHorizon
    defaults_assumed: tuple[str, ...] = field(default_factory=tuple)
    irreversible_approved: bool = False
    delivery: DeliveryPolicy = field(default_factory=DeliveryPolicy)
