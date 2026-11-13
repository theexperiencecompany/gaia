"""Onboarding, first-steps checklist and nurture email events."""

from enum import StrEnum
from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "FirstStepsCollapsed",
    "FirstStepsStepClicked",
    "NurtureEmailSent",
    "OnboardingCheckoutRetried",
    "OnboardingCompleted",
    "OnboardingPhaseCompleted",
    "OnboardingReset",
    "OnboardingRestarted",
    "OnboardingSkipped",
    "OnboardingSocialProfilesConfirmed",
    "OnboardingStarted",
    "OnboardingStep",
    "OnboardingWritingStyleExampleRegenerated",
    "OnboardingWritingStyleSaved",
    "ReportedOnboardingStep",
]


class OnboardingStep(StrEnum):
    """A wizard milestone, stamped once per onboarding run on users.onboarding.steps_reached."""

    STARTED = "started"
    QUESTIONS_ANSWERED = "questions_answered"
    PAYWALL_REACHED = "paywall_reached"
    PAID_REVEAL_SEEN = "paid_reveal_seen"
    FIRST_CHAT_OPENED = "first_chat_opened"


#: The steps only the browser sees; questions_answered is stamped by the answers save itself.
ReportedOnboardingStep = Literal[
    OnboardingStep.STARTED,
    OnboardingStep.PAYWALL_REACHED,
    OnboardingStep.PAID_REVEAL_SEEN,
    OnboardingStep.FIRST_CHAT_OPENED,
]


class OnboardingStarted(ServerEvent):
    """A user opened the onboarding wizard for the first time this onboarding run."""

    event: ClassVar[str] = "onboarding:started"
    budget_per_user_day: ClassVar[int] = 10


class OnboardingSkipped(WebEvent):
    """A developer skipped onboarding with the dev-only shortcut."""

    event: ClassVar[str] = "onboarding:skipped"
    budget_per_user_day: ClassVar[int] = 50

    source: Literal["dev_skip"]


class OnboardingRestarted(WebEvent):
    """A user wiped the wizard from the restart modal; only the browser knows the reset came from there."""

    event: ClassVar[str] = "onboarding:restarted"
    budget_per_user_day: ClassVar[int] = 10

    from_stage: Identifier


class OnboardingCheckoutRetried(WebEvent):
    """A user came back from a failed or stalled checkout and asked for the plans again."""

    event: ClassVar[str] = "onboarding:checkout_retried"
    budget_per_user_day: ClassVar[int] = 50

    reason: Literal["declined", "confirmation_timeout"]


class OnboardingPhaseCompleted(ServerEvent):
    """A user reached a wizard step past the start; the answer shape rides only on questions_answered."""

    event: ClassVar[str] = "onboarding:phase_completed"
    budget_per_user_day: ClassVar[int] = 10

    phase: OnboardingStep
    needs: list[Identifier] | None = None
    has_other_need: bool | None = None


class OnboardingCompleted(ServerEvent):
    """A user left the platform step and submitted onboarding; linked_platform is None when they skipped."""

    event: ClassVar[str] = "onboarding:completed"
    budget_per_user_day: ClassVar[int] = 10

    needs: list[Identifier]
    has_other_need: bool
    linked_platform: Identifier | None = None


class OnboardingReset(ServerEvent):
    """A user's onboarding was fully reset."""

    event: ClassVar[str] = "onboarding:reset"
    budget_per_user_day: ClassVar[int] = 10


class OnboardingWritingStyleSaved(ServerEvent):
    """A user saved an edited writing-style summary."""

    event: ClassVar[str] = "onboarding:writing_style_saved"
    budget_per_user_day: ClassVar[int] = 50

    summary_length: int


class OnboardingWritingStyleExampleRegenerated(ServerEvent):
    """A user regenerated the example email for their writing style."""

    event: ClassVar[str] = "onboarding:writing_style_example_regenerated"
    budget_per_user_day: ClassVar[int] = 50


class OnboardingSocialProfilesConfirmed(ServerEvent):
    """A user confirmed their social profiles."""

    event: ClassVar[str] = "onboarding:social_profiles_confirmed"
    budget_per_user_day: ClassVar[int] = 50

    profile_count: int
    platforms: list[Identifier]


class FirstStepsCollapsed(ServerEvent):
    """A user collapsed or expanded the activation checklist; carries how many steps were done, never which."""

    event: ClassVar[str] = "first_steps:collapsed"
    budget_per_user_day: ClassVar[int] = 10

    collapsed: bool
    steps_done: int
    steps_total: int


class FirstStepsStepClicked(WebEvent):
    """A checklist row was clicked; completion is server-derived, but the click never reaches it."""

    event: ClassVar[str] = "first_steps:step_clicked"
    budget_per_user_day: ClassVar[int] = 10

    step: Identifier
    done: bool
    surface: Literal["dashboard", "widget"]


class NurtureEmailSent(ServerEvent):
    """A lifecycle nurture email went out."""

    event: ClassVar[str] = "nurture:email_sent"
    budget_per_user_day: ClassVar[int] = 10

    step: Identifier
    day_offset: int
