"""Nurture email sequence definition (GAIA-523).

Each step teaches exactly one thing GAIA does, with one CTA. Steps are
declarative data; send/skip mechanics live in app/services/nurture.
"""

from dataclasses import dataclass

from app.constants.referrals import (
    NURTURE_SHARE_CTA_LABEL,
    NURTURE_SHARE_SUBJECT,
    REFERRALS_PAGE_PATH,
    ReferralNudge,
)


@dataclass(frozen=True)
class NurtureStep:
    """One email in the nurture sequence, evaluated by app/services/nurture."""

    key: str
    day_offset: int  # days since user signup
    template: str
    subject: str
    skip_predicate: str | None = None  # key into app/services/nurture/predicates.py
    context_builder: str | None = None  # key into app/services/nurture/context_builders.py
    cta_path: str | None = None  # appended to FRONTEND_URL; None = no button (reply is the CTA)
    cta_label: str | None = None
    requires_onboarding: bool = True  # held (not skipped) until onboarding completes
    enabled: bool = True
    nudge: ReferralNudge | None = None  # a referral pitch: also spends the referral nudge budget


NURTURE_STEPS: tuple[NurtureStep, ...] = (
    NurtureStep(
        key="first_win",
        day_offset=1,
        template="nurture_first_win.html",
        subject="Give GAIA one real job today",
        skip_predicate="used_chat",
        cta_path="/c",
        cta_label="Give GAIA a job",
        requires_onboarding=False,
    ),
    NurtureStep(
        key="onboarding_nudge",
        day_offset=2,
        template="nurture_onboarding_nudge.html",
        subject="Two minutes to finish setting up GAIA",
        skip_predicate="onboarding_completed",
        cta_path="/onboarding",
        cta_label="Finish setup",
        requires_onboarding=False,
    ),
    # Skips only when BOTH Gmail and Calendar are connected; the template
    # adapts its pitch (and the builder its CTA label) to whichever is missing.
    NurtureStep(
        key="connect_gmail",
        day_offset=3,
        template="nurture_connect_gmail.html",
        subject="Two minutes of setup, and GAIA gets 10x more useful",
        skip_predicate="google_suite_connected",
        context_builder="google_connection_status",
        cta_path="/integrations",
        cta_label="Connect Gmail & Calendar",
    ),
    # Enable when the daily briefing (feat/daily-briefing-openspec) launches,
    # together with an "opened a recent briefing" skip predicate.
    NurtureStep(
        key="morning_brief",
        day_offset=5,
        template="nurture_morning_brief.html",
        subject="GAIA worked while you slept",
        cta_path="/dashboard",
        cta_label="See today's brief",
        enabled=False,
    ),
    NurtureStep(
        key="smart_todos",
        day_offset=8,
        template="nurture_todos.html",
        subject="Your todo list should be doing the work, not you",
        skip_predicate="uses_todos",
        cta_path="/todos",
        cta_label="Hand GAIA a todo",
    ),
    NurtureStep(
        key="workflows",
        day_offset=11,
        template="nurture_workflows.html",
        subject="Set it up once, never think about it again",
        skip_predicate="has_workflow",
        cta_path="/workflows",
        cta_label="Build your first workflow",
    ),
    NurtureStep(
        key="channels",
        day_offset=14,
        template="nurture_channels.html",
        subject="You don't actually have to open the app",
        skip_predicate="linked_platform",
        cta_path="/settings/linked-accounts",
        cta_label="Link a channel",
    ),
    # Day 15 is the earliest slot the caps leave free without starving a later step.
    NurtureStep(
        key="share_gaia",
        day_offset=15,
        template="nurture_share_gaia.html",
        subject=NURTURE_SHARE_SUBJECT,
        skip_predicate="never_used_chat",
        context_builder="referral_gift_prices",
        cta_path=REFERRALS_PAGE_PATH,
        cta_label=NURTURE_SHARE_CTA_LABEL,
        nudge=ReferralNudge.NURTURE_EMAIL,
    ),
    NurtureStep(
        key="founder_checkin",
        day_offset=21,
        template="nurture_checkin.html",
        subject="How is GAIA actually working for you?",
        requires_onboarding=False,
    ),
)

# Send window: a step only fires while days-since-signup is within
# [day_offset, day_offset + grace]. Prevents back-filling old accounts.
NURTURE_BACKFILL_GRACE_DAYS = 2

# Local hour (user timezone) at which nurture emails go out.
NURTURE_SEND_HOUR_LOCAL = 9

# Frequency guardrails: step day_offsets run 1,2,3,5,8,11,14,15,21 (earliest three
# consecutive), so a 2/week cap would starve the day-3/day-14 steps. 3/week with
# 2-day minimum spacing fits the schedule and guarantees at most one email/2 days.
NURTURE_MAX_EMAILS_PER_WEEK = 3
NURTURE_MIN_DAYS_BETWEEN_EMAILS = 2

# UTM tags appended to every CTA so activation attribution works in PostHog.
NURTURE_UTM_SOURCE = "nurture"
NURTURE_UTM_MEDIUM = "email"
