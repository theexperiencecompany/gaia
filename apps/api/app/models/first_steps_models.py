from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FirstStepKey(StrEnum):
    """The activation checklist, in display order. Mirrored by the web."""

    SAY_HI = "say_hi"
    CONNECT_INTEGRATION = "connect_integration"
    LINK_PLATFORM = "link_platform"
    CREATE_WORKFLOW = "create_workflow"


class FirstStep(BaseModel):
    key: FirstStepKey
    done: bool = Field(description="Derived server-side from a real signal at read time")


class FirstStepsResponse(BaseModel):
    steps: list[FirstStep] = Field(description="Every step, in checklist order")
    collapsed: bool = Field(description="Whether the user collapsed the checklist to its header")


class FirstStepsCollapseRequest(BaseModel):
    """The chevron's new state. Both directions persist, so a checklist expanded
    on one device stays expanded on the next."""

    collapsed: bool


class FirstStepsState(BaseModel):
    """The ``users.first_steps`` subdocument — only the collapse is persisted."""

    collapsed: bool = False
    collapsed_at: datetime | None = None
