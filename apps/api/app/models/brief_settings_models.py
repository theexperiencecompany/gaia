"""The user's briefing settings: when briefs run, which edition families draw, and the off-switch's conflicts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.constants.briefing import (
    DAILY_BRIEFING_HOUR,
    BriefingFrequency,
    EditionChoice,
)
from app.constants.workflows import WorkflowDelivery
from app.schemas.errors import ErrorEnvelope


class BriefingSchedule(BaseModel):
    """When the user wants their briefs: how often, and the daily brief's local hour."""

    frequency: BriefingFrequency = BriefingFrequency.DAILY
    hour: int = Field(default=DAILY_BRIEFING_HOUR, ge=0, le=23)


class BriefingScheduleState(BriefingSchedule):
    """The stored schedule and whether it runs: briefs on a schedule are a Pro feature."""

    paused_for_plan: bool = Field(
        description="The schedule sends briefs, but none run: the user is not on Pro."
    )
    next_daily_brief_at: datetime | None = Field(
        description="When the next daily brief runs (UTC); None while no daily brief runs."
    )


#: Where a workflow's results can go once there is no brief to hold them.
BriefFreeDelivery = Literal[WorkflowDelivery.NOW, WorkflowDelivery.SILENT]


class BriefingScheduleUpdate(BriefingSchedule):
    """A new briefing schedule; turning briefs off also says where brief-delivery workflows go."""

    workflow_deliveries: dict[str, BriefFreeDelivery] = Field(
        default_factory=dict,
        description="New delivery per workflow id, for workflows that deliver to the brief",
    )

    @model_validator(mode="after")
    def deliveries_only_when_turning_off(self) -> "BriefingScheduleUpdate":
        """Refuse new deliveries unless briefs are being turned off."""
        if self.workflow_deliveries and self.frequency is not BriefingFrequency.OFF:
            raise ValueError("workflow_deliveries is only accepted when frequency is off")
        return self

    def schedule(self) -> BriefingSchedule:
        """Return the schedule to store, without the one-off deliveries."""
        return BriefingSchedule(frequency=self.frequency, hour=self.hour)


class BriefingEdition(BaseModel):
    """One daily edition family, and where the user put it."""

    family: str
    name: str
    choice: EditionChoice


class BriefingEditions(BaseModel):
    """Every daily edition family a brief can draw, and where the user put each."""

    editions: list[BriefingEdition]


class BriefingEditionsUpdate(BaseModel):
    """Where the user puts each daily edition family; a family not named stays in the rotation."""

    choices: dict[str, EditionChoice]


class BriefDeliveryWorkflow(BaseModel):
    """A workflow whose results wait for the brief."""

    id: str
    title: str


class BriefDeliveryWorkflowsConflict(ErrorEnvelope):
    """The 409 body when briefs cannot turn off: the workflows still delivering to the brief."""

    workflows: list[BriefDeliveryWorkflow]
