"""Structured output schema for workflow execution results."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class WorkflowStructuredOutput(BaseModel):
    """Structured data extracted from workflow execution output for dynamic notifications."""

    notification_title: str = Field(
        description="Action-oriented title summarizing what the workflow accomplished, e.g. '3 emails drafted for Project X'"
    )
    notification_body: str = Field(
        description="1-2 sentence summary of the workflow outcomes"
    )
    notification_type: Literal["success", "info", "warning"] = Field(
        default="success",
        description="Notification severity: success for full completion, warning for partial failures, info for neutral outcomes",
    )
    notification_channels: list[Literal["inapp", "telegram", "discord"]] = Field(
        default_factory=lambda: ["inapp"],
        description="Channels to deliver notification to. Include telegram/discord only for urgent or actionable results.",
    )
    requires_user_action: bool = Field(
        default=False,
        description="Whether the user needs to take action based on the workflow results",
    )
    action_items: list[str] = Field(
        default_factory=list,
        description="Up to 3 specific next steps the user should take, if any",
    )

    @field_validator("notification_channels")
    @classmethod
    def ensure_at_least_one_channel(
        cls, v: list[str],
    ) -> list[str]:
        return v if v else ["inapp"]

    @field_validator("action_items")
    @classmethod
    def cap_action_items(cls, v: list[str]) -> list[str]:
        return v[:3]
