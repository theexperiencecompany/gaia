"""When an item that is to be told is told: now, held until an instant, or recorded as a repeat.

Pure, like the policy it follows: what the policy decided, what the Judge made of the item and
the user's attention now (quiet hours, DND, the day's budget, the gap since the last message, who
is here) in, a Placement out, so every limit is provable without a database or a clock. The
policy decides whether the user hears of an item; this decides when, in the order of the design's
Rails (5.5): the user's own timing, silence, answers and timely items, then the unsolicited
limits. A hold is never open-ended: every one ends at an instant, bounded by the item's deadline.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zlib import crc32

from app.constants.outbox_attention import (
    ACTIVITY_OVERRIDE_SECONDS,
    ANSWER_QUIET_GRACE_SECONDS,
    DEADLINE_PROXIMITY_SECONDS,
    FLUSH_JITTER_MAX_SECONDS,
    MAX_DAYTIME_HOLD_SECONDS,
    MAX_DEFERRALS,
    MAX_HOLD_AGE_SECONDS,
    MIN_UNSOLICITED_GAP_SECONDS,
    REPEAT_BACKOFF_SECONDS,
    REPEAT_MUTE_SECONDS,
    STALL_ESCALATE_AFTER_SECONDS,
    TIMELY_LEAD_SECONDS,
    WAIT_MAX_SECONDS,
    WAIT_MIN_HIT_RATE,
    HoldReason,
)
from app.models.attention_settings_models import AttentionSettings
from app.services.outbox.judge_models import JudgeVerdict
from app.services.outbox.judge_verdict import UserClock
from app.services.outbox.models import (
    DropReason,
    ItemHold,
    NoticeReport,
    OutboxReport,
    UrgencyClass,
)
from app.services.outbox.policy import is_answer, is_security_notice, is_users_own, urgency_of

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class FactHistory:
    """How often GAIA has told the user one real-world fact, and when it last did."""

    times_told: int
    last_told_at: datetime


@dataclass(frozen=True, slots=True)
class AttentionState:
    """What the user's attention looks like at the moment an item is placed."""

    user_id: str
    now: datetime
    clock: UserClock
    settings: AttentionSettings
    #: When the user last wrote on any surface; None when they have not lately.
    last_active_at: datetime | None
    unsolicited_today: int
    last_unsolicited_at: datetime | None
    fact_history: FactHistory | None
    #: The hold the item was under before, when this is a flush of it.
    prior_hold: ItemHold | None = None


@dataclass(frozen=True, slots=True)
class Tell:
    """Tell it now."""


@dataclass(frozen=True, slots=True)
class Hold:
    """Tell it at an instant, not before."""

    until: datetime
    reason: HoldReason


@dataclass(frozen=True, slots=True)
class Record:
    """Keep it and never alert it: the user has been told this often enough."""

    reason: DropReason


Placement = Tell | Hold | Record


def _jitter(user_id: str) -> timedelta:
    """Spread of releases that share an instant: stable per user, so a recompute never moves it."""
    return timedelta(seconds=crc32(user_id.encode()) % FLUSH_JITTER_MAX_SECONDS)


def _seconds(value: float) -> timedelta:
    return timedelta(seconds=value)


def _active_within(state: AttentionState, seconds: float) -> bool:
    return state.last_active_at is not None and state.now - state.last_active_at <= _seconds(
        seconds
    )


def _silence(state: AttentionState) -> tuple[HoldReason, datetime] | None:
    """Return why the user is not to be told unprompted now, and when that ends; None when they may be."""
    settings = state.settings
    if settings.dnd_until is not None and settings.dnd_until > state.now:
        return HoldReason.DND, settings.dnd_until
    local = state.clock.timezone.localize(state.now)
    quiet = state.clock.quiet_hours
    if quiet.contains(local):
        return HoldReason.QUIET_HOURS, quiet.end_after(local)
    return None


def next_checkin(state: AttentionState) -> datetime | None:
    """Return the next check-in slot after now on the user's own clock: when quiet hours end, or a chosen time.

    None when the user has no slots at all: no chosen times and quiet hours off.
    """
    local = state.clock.timezone.localize(state.now)
    slots: list[time] = list(state.settings.checkin_times)
    quiet = state.clock.quiet_hours
    if quiet.enabled:
        slots.append(time(quiet.end_hour))
    if not slots:
        return None
    candidates = [
        datetime.combine(local.date() + timedelta(days=day), slot, tzinfo=local.tzinfo)
        for day in (0, 1)
        for slot in slots
    ]
    return min(candidate for candidate in candidates if candidate > local)


def _bounded(until: datetime, latest: datetime | None) -> datetime:
    return until if latest is None else min(until, latest)


def _hold_cap(state: AttentionState) -> datetime:
    """Return the instant no hold on this item outlives, counted from when it was first held."""
    started = state.prior_hold.since if state.prior_hold is not None else state.now
    return started + _seconds(MAX_HOLD_AGE_SECONDS)


def _hold_or_tell(state: AttentionState, until: datetime, reason: HoldReason) -> Hold | Tell:
    """Hold until the instant, never past the hold-age cap; when it has already come, the item has waited long enough."""
    until = min(until, _hold_cap(state))
    return Hold(until, reason) if until > state.now else Tell()


def _checkin_hold(state: AttentionState, latest: datetime | None) -> Hold | Tell:
    """Hold for the next check-in; a user with none is told on their return or at the hold-age cap."""
    slot = next_checkin(state)
    until = _hold_cap(state) if slot is None else slot + _jitter(state.user_id)
    return _hold_or_tell(state, _bounded(until, latest), HoldReason.CHECKIN)


def _deadline(report: OutboxReport, verdict: JudgeVerdict | None) -> datetime | None:
    """Return the instant after which telling loses its value: the creator's by, the Judge's deliver_by, or a notice's valid_until."""
    candidates = [
        moment
        for moment in (
            report.delivery_policy.by,
            verdict.deliver_by if verdict is not None else None,
            report.valid_until if isinstance(report, NoticeReport) else None,
        )
        if moment is not None
    ]
    return min(candidates, default=None)


def _may_wait_for_run(
    state: AttentionState, verdict: JudgeVerdict, latest: datetime | None
) -> bool:
    """Whether the run the Judge named is worth holding the item for, within every guardrail."""
    run_at = verdict.wait_run_at
    if verdict.wait_for_run is None or run_at is None:
        return False
    hit_rate = verdict.wait_run_hit_rate
    if hit_rate is None or hit_rate < WAIT_MIN_HIT_RATE:
        return False
    if not state.now < run_at <= state.now + _seconds(WAIT_MAX_SECONDS):
        return False
    if latest is not None and run_at > latest:
        return False
    prior = state.prior_hold
    if prior is None:
        return True
    return prior.deferrals < MAX_DEFERRALS and state.now - prior.since < _seconds(
        MAX_DAYTIME_HOLD_SECONDS
    )


def _repeat_gap(history: FactHistory) -> timedelta:
    """How long after GAIA last told a fact it may tell it again: 1d, then 3d, then 7d, then monthly."""
    if history.times_told > len(REPEAT_BACKOFF_SECONDS):
        return _seconds(REPEAT_MUTE_SECONDS)
    return _seconds(REPEAT_BACKOFF_SECONDS[history.times_told - 1])


def escalated(urgency: UrgencyClass, state: AttentionState) -> UrgencyClass:
    """Return the urgency an item that has been held a long time is placed at: one class higher, never an interrupt."""
    prior = state.prior_hold
    if (
        prior is not None
        and state.now - prior.since >= _seconds(STALL_ESCALATE_AFTER_SECONDS)
        and urgency < UrgencyClass.TIMELY
    ):
        return UrgencyClass(urgency + 1)
    return urgency


def _in_silence(
    report: OutboxReport,
    urgency: UrgencyClass,
    verdict: JudgeVerdict | None,
    state: AttentionState,
    latest: datetime | None,
) -> Placement | None:
    """Place an item that arrives while the user is not to be told unprompted; None when it is not that time."""
    silence = _silence(state)
    if silence is None:
        return None
    reason, ends = silence
    if verdict is not None and is_security_notice(verdict):
        return Tell()
    if urgency is UrgencyClass.INTERRUPT:
        if reason is HoldReason.DND and not is_users_own(report, urgency_of(report)):
            return _hold_or_tell(state, ends, reason)
        return Tell()
    grace = ANSWER_QUIET_GRACE_SECONDS if is_answer(report) else ACTIVITY_OVERRIDE_SECONDS
    if _active_within(state, grace):
        return Tell()
    return _hold_or_tell(state, _bounded(ends + _jitter(state.user_id), latest), reason)


def _unsolicited(
    urgency: UrgencyClass,
    verdict: JudgeVerdict | None,
    state: AttentionState,
    latest: datetime | None,
    *,
    released: bool,
) -> Placement:
    """Place an item nobody asked for and that is not urgent, against the user's limits."""
    if urgency is UrgencyClass.ROUTINE and state.fact_history is not None:
        near_deadline = latest is not None and latest - state.now <= _seconds(
            DEADLINE_PROXIMITY_SECONDS
        )
        if not near_deadline and (
            state.now - state.fact_history.last_told_at < _repeat_gap(state.fact_history)
        ):
            return Record(DropReason.REPEAT_BACKOFF)
    if verdict is not None and _may_wait_for_run(state, verdict, latest):
        run_at = verdict.wait_run_at
        if run_at is not None:
            return Hold(run_at, HoldReason.WAIT_FOR_RUN)
    if released:
        return Tell()
    if urgency is UrgencyClass.BACKGROUND:
        return _checkin_hold(state, latest)
    if state.unsolicited_today >= state.settings.max_unsolicited_per_day:
        return _checkin_hold(state, latest)
    if state.last_unsolicited_at is not None:
        gap_ends = state.last_unsolicited_at + _seconds(MIN_UNSOLICITED_GAP_SECONDS)
        return _hold_or_tell(state, _bounded(gap_ends, latest), HoldReason.GAP)
    return Tell()


def place(
    report: OutboxReport,
    urgency: UrgencyClass,
    verdict: JudgeVerdict | None,
    state: AttentionState,
    *,
    released: bool = False,
) -> Placement:
    """Return when an item the policy decided to tell is told.

    urgency is what the Rails authorized. released says the item already waited out a hold of its
    own kind, so it is not held again for the budget, the gap or a check-in; silence, the user's
    own timing and the hold-age cap apply either way.
    """
    prior = state.prior_hold
    if prior is not None and state.now - prior.since >= _seconds(MAX_HOLD_AGE_SECONDS):
        return Tell()
    urgency = escalated(urgency, state)
    latest = _deadline(report, verdict)
    if latest is not None:
        latest -= _seconds(TIMELY_LEAD_SECONDS)
    not_before = report.delivery_policy.not_before
    if not_before is not None and not_before > state.now:
        return Hold(not_before, HoldReason.NOT_BEFORE)
    silent = _in_silence(report, urgency, verdict, state, latest)
    if silent is not None:
        return silent
    if urgency is UrgencyClass.INTERRUPT or urgency is UrgencyClass.TIMELY or is_answer(report):
        return Tell()
    return _unsolicited(urgency, verdict, state, latest, released=released)
