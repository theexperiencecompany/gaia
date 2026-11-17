"""Idle wind-down: pause the whole loop when GAIA has nothing to work on.

An idle day is a daily run that found no tracked work and no goal knowledge — the
engine has nothing legitimate to report. On day IDLE_WARN_DAYS the brief warns
plainly; on day IDLE_DORMANT_DAYS it says goodbye once and the loop goes
dormant: the daily brief and the weekly digest both early-exit before any LLM
call, so a goalless account costs a few Mongo reads a day.

Reactivation is pull-based, checked at run start: any activity the user made on
any surface since dormancy began (users.last_active_at, the one activity record)
wakes the loop on its next run. Only the daily run mutates dormancy state; the
weekly digest reads it. This ladder is about having nothing to report; a user who
stops acknowledging briefs is the winback's to back off (briefing.context), never
the workflow-dormancy sweep's, which leaves the briefs alone. A new account's first
week never climbs the ladder: its briefs help the user get started instead.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.constants.briefing import (
    DAILY_BRIEFING_WORKFLOW_KEY,
    ENABLED_BRIEFING_KEYS,
    FIRST_WEEK_DAYS,
    GOAL_QUESTION_REASK,
    IDLE_DORMANT_DAYS,
    IDLE_WARN_DAYS,
)
from app.db.repositories.users import user_repository
from app.models.user_models import BriefingDormancy, UserDocument
from app.utils.timezone import as_utc
from shared.py.wide_events import log

WIND_DOWN_WARN = "warn"
WIND_DOWN_FINAL = "final"


class GoalQuestion(StrEnum):
    """What today's brief does about the goal it remembers."""

    #: No goal is remembered; the voice asks for one: never asked, or asked GOAL_QUESTION_REASK ago.
    NONE = "none"
    #: Ask whether the goal is still live: never asked, or asked GOAL_QUESTION_REASK ago.
    ASK = "ask"
    #: Asked about the goal, or for one, inside the window: not again today, in any wording.
    ASKED = "asked"


@dataclass(frozen=True)
class IdleLadder:
    """Where today's run leaves the user on the ladder; wind_down is None off its rungs."""

    first_week: bool
    idle_days: int
    wind_down: str | None
    goal_question: GoalQuestion = GoalQuestion.NONE


@dataclass
class DormancyState:
    idle_days: int
    date: str | None
    dormant_since: datetime | None
    goal_asked_at: datetime | None = None


def state_from_user(user: UserDocument) -> DormancyState:
    marker = user.briefing_dormancy or BriefingDormancy()
    since = marker.dormant_since
    # Mongo returns naive UTC datetimes; normalize before comparing.
    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return DormancyState(
        idle_days=marker.idle_days,
        date=marker.date,
        dormant_since=since,
        goal_asked_at=as_utc(marker.goal_asked_at),
    )


def in_first_week(user: UserDocument, now: datetime) -> bool:
    """Whether the account signed up under FIRST_WEEK_DAYS ago; an undated one never is."""
    signed_up = as_utc(user.created_at)
    return signed_up is not None and now - signed_up < timedelta(days=FIRST_WEEK_DAYS)


def wind_down_stage(idle_days: int) -> str | None:
    if idle_days >= IDLE_DORMANT_DAYS:
        return WIND_DOWN_FINAL
    if idle_days == IDLE_WARN_DAYS:
        return WIND_DOWN_WARN
    return None


async def latest_activity_since(user_id: str, since: datetime) -> datetime | None:
    """Return when the user last acted on any surface, if at/after since; None when not since.

    Read from Mongo, not the cached user, whose last_active_at can be days stale.
    The cutoff must be timezone-aware.
    """
    dates = await user_repository.get_activity_dates(user_id)
    last_active = as_utc(dates.last_active_at) if dates else None
    return last_active if last_active is not None and last_active >= since else None


async def is_dormant(user: UserDocument) -> bool:
    """Whether the loop is dormant with no activity since: its next run skips before reading anything."""
    since = state_from_user(user).dormant_since
    return since is not None and await latest_activity_since(user.id, since) is None


async def record_idle_day(user_id: str, prior: DormancyState, idle: bool, date_str: str) -> int:
    """Persist today's idle/active outcome; returns the consecutive idle count.

    Same-day reruns don't double-count (the one-brief-per-day law applies to the
    ladder too), and an active day for a user with no marker writes nothing.
    """
    if prior.date == date_str:
        return prior.idle_days
    if not idle and prior.idle_days == 0 and prior.date is None:
        return 0
    idle_days = prior.idle_days + 1 if idle else 0
    await user_repository.set_dormancy_day(user_id, idle_days=idle_days, date_str=date_str)
    return idle_days


def goal_question(prior: DormancyState, now: datetime, *, has_goal: bool) -> GoalQuestion:
    """Say whether today's brief asks about the goal, or for one, or asked too recently to."""
    asked = prior.goal_asked_at
    if asked is not None and now - asked < GOAL_QUESTION_REASK:
        return GoalQuestion.ASKED
    return GoalQuestion.ASK if has_goal else GoalQuestion.NONE


async def climb_idle_ladder(
    user: UserDocument, prior: DormancyState, date_str: str, *, has_news: bool, has_goal: bool
) -> IdleLadder:
    """Record today as idle or active, and return the rung it reached and today's goal question.

    Idle is nothing to report and nothing to work toward: no goal, or a goal asked about with
    the user away since. A new account's first week is never idle.
    """
    now = datetime.now(UTC)
    first_week = in_first_week(user, now)
    question = goal_question(prior, now, has_goal=has_goal)
    ignored = (
        question is GoalQuestion.ASKED
        and prior.goal_asked_at is not None
        and await latest_activity_since(user.id, prior.goal_asked_at) is None
    )
    idle = not has_news and not first_week and (not has_goal or ignored)
    idle_days = await record_idle_day(user.id, prior, idle, date_str)
    return IdleLadder(
        first_week=first_week,
        idle_days=idle_days,
        wind_down=wind_down_stage(idle_days) if idle else None,
        goal_question=question,
    )


async def leave_idle_ladder(user_id: str, ladder: IdleLadder) -> None:
    """Record a goal question that went out, for the goal or for one; pause the loop once the goodbye did."""
    if ladder.goal_question is not GoalQuestion.ASKED:
        await user_repository.record_goal_question(user_id)
    if ladder.wind_down == WIND_DOWN_FINAL:
        await user_repository.enter_briefing_dormancy(user_id)
        log.info("briefing.dormancy_entered", user_id=user_id, idle_days=ladder.idle_days)


async def climb_weekly_ladder(
    user: UserDocument, prior: DormancyState, date_str: str, *, has_news: bool, has_goal: bool
) -> None:
    """Count an empty digest as idle for a user the weekly digest is the only brief of.

    Their loop goes dormant after IDLE_DORMANT_DAYS idle digests in a row; a user with a
    daily brief climbs the ladder on it instead.
    """
    if DAILY_BRIEFING_WORKFLOW_KEY in ENABLED_BRIEFING_KEYS[user.briefing_schedule.frequency]:
        return
    idle = not has_news and not has_goal and not in_first_week(user, datetime.now(UTC))
    idle_days = await record_idle_day(user.id, prior, idle, date_str)
    if idle and idle_days >= IDLE_DORMANT_DAYS:
        await user_repository.enter_briefing_dormancy(user.id)
        log.info("briefing.dormancy_entered", user_id=user.id, idle_days=idle_days)
