"""The state one item is judged in, as the Judge reads it: bounded views of what GAIA knows."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.attention_profile_models import ProfileAnswer
from app.services.outbox.judge_models import JudgeVerdict


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserView(_View):
    timezone: str
    usual_wake: str
    usual_sleep: str
    attention_profile: list[ProfileAnswer]


class ItemView(_View):
    producer: str
    outcome: str
    subject: str
    facts: list[str]
    source_excerpt: str | None = None
    producer_suggested: dict[str, str]


class AskView(_View):
    initiative: str
    delivery_timing: str
    may_wake: bool


class MessageView(_View):
    at: datetime
    surface: str
    text: str


class SubjectView(_View):
    label: str
    status: str
    since: datetime | None


class PendingAskView(_View):
    label: str
    question: str
    since: datetime | None


class DeliveryView(_View):
    at: datetime
    channel: str
    summary: str


class CalendarEventView(_View):
    start: str
    end: str | None
    title: str


class SettingsView(_View):
    quiet_hours: str
    unsolicited_budget_per_day: int
    dnd_until: datetime | None = None
    rules: list[str]


class PresenceView(_View):
    last_active_surface: str | None
    last_active_at: datetime | None
    active_surfaces: dict[str, datetime]


class RunView(_View):
    run_id: str
    kind: str
    label: str
    starts_at: datetime
    hit_rate: float | None = Field(
        description="The share of its last runs that produced something told; None before any has."
    )


class HeldView(_View):
    subject: str
    held_minutes: int


class WaitView(_View):
    run_id: str
    subject: str
    decided_at: datetime | None


class JudgeContext(_View):
    """The state one item is judged in; its JSON is what both passes read."""

    now: datetime
    user: UserView
    item: ItemView
    other_items_in_batch: list[ItemView]
    ask: AskView
    recent_user_messages: list[MessageView]
    recent_gaia_replies: list[MessageView]
    open_subjects: list[SubjectView]
    pending_asks: list[PendingAskView]
    recent_deliveries: list[DeliveryView]
    memory: list[str]
    calendar: list[CalendarEventView] | None
    attention_settings: SettingsView
    presence: PresenceView
    upcoming_runs: list[RunView]
    held_items: list[HeldView]
    past_waits: list[WaitView]

    @property
    def offered_runs(self) -> dict[str, str]:
        """The runs the Judge may tell an item to wait for, by id."""
        return {run.run_id: run.label for run in self.upcoming_runs}

    def with_wait_run(self, verdict: JudgeVerdict) -> JudgeVerdict:
        """Return the verdict with the start and hit rate of the run it waits for, which the Rails bound the wait by."""
        run = next((run for run in self.upcoming_runs if run.run_id == verdict.wait_for_run), None)
        if run is None:
            return verdict
        return verdict.model_copy(
            update={"wait_run_at": run.starts_at, "wait_run_hit_rate": run.hit_rate}
        )

    def as_state(self) -> dict[str, object]:
        """Return the context as the JSON state both passes read."""
        return self.model_dump(mode="json", exclude_none=True)
