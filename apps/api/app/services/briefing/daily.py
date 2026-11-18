"""The daily brief's standing: the reader's idle ladder, winback and first brief, and what it looks back on."""

from dataclasses import dataclass, replace
from datetime import datetime

from typing_extensions import override

from app.agents.prompts.briefing_prompts import (
    VoicePromptBlocks,
    VoiceSituation,
    build_briefing_voice_prompt,
)
from app.constants.briefing import BriefingKind, BriefingRunOutcome
from app.constants.user_activity import ActivityStatus
from app.db.repositories.briefings import briefing_repository
from app.models.brief_composition_models import ChartBlock, QuoteBlock
from app.models.brief_payload_models import BriefingMood, BriefingPayload, BriefVoice
from app.models.briefing_state_models import BriefingDormancy, BriefingStateDocument
from app.models.user_models import UserDocument
from app.services.briefing import chat_sync, wind_down
from app.services.briefing.calendar_read import CalendarRead
from app.services.briefing.candidates.pool import GatheredCandidates
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.goals import StatedGoal, format_goal_block, stated_goals
from app.services.briefing.lifecycle import bootstrap_should_skip, clear_bootstrap, wake_or_skip
from app.services.briefing.lookback import (
    Lookback,
    WinbackState,
    compute_winback_state,
    format_lookback_block,
    last_brief,
    lookback_since,
)
from app.services.briefing.prose import Writing, reader_block
from app.services.briefing.run_times import describe_briefing_schedule, user_brief_slots
from app.services.briefing.sections import Laid
from app.services.briefing.slots import figures_in
from app.services.briefing.standing import Standing, VoiceInputs, VoiceRequest
from app.services.hil.utils import untrusted_fence
from app.services.integrations.user_integrations import (
    ConnectedIntegration,
    get_connected_integrations_named,
)
from app.services.user_activity.status import activity_status_of
from shared.py.wide_events import log


@dataclass(frozen=True)
class DailyStanding(Standing):
    """The reader's standing for today's brief; ladder is set once the run knows whether it has news."""

    user: UserDocument
    state: BriefingStateDocument
    clock: UserClock
    goals: list[StatedGoal]
    lookback: Lookback
    winback: WinbackState
    is_first: bool
    #: Where the idle ladder stood before today.
    prior: BriefingDormancy
    ladder: wind_down.IdleLadder | None = None

    @override
    @property
    def since(self) -> datetime:
        return self.lookback.since

    @property
    def _ladder(self) -> wind_down.IdleLadder:
        if self.ladder is None:
            raise RuntimeError("the daily brief read its idle ladder before climbing it")
        return self.ladder

    @override
    async def climbed(self, gathered: GatheredCandidates, pool: FactPool) -> "DailyStanding":
        """Climb the idle ladder now the run knows whether it has news.

        Nothing to report and no goal (or an ignored goal question) escalates to a plain
        warning, one goodbye, then dormancy; the ladder also says whether today asks about
        the goal. A new account's first week never climbs it.
        """
        ladder = await wind_down.climb_idle_ladder(
            self.user,
            self.prior,
            self.clock.date_str,
            has_news=gathered.has_news,
            has_goal=bool(self.goals),
        )
        return replace(self, ladder=ladder)

    @override
    def quiet_before_composing(self, pool: FactPool) -> bool:
        return False

    @override
    def quiet_after_composing(self, laid: Laid, calendar: CalendarRead) -> bool:
        """Say whether today gets the quiet note: no event, nothing the ladder says, nothing new placed.

        What an earlier brief already showed as it stands is no reason for an edition, nor a
        stalled goal's progress or a note about it; a chart or a quote shows something that moved.
        A winback and a first brief always go out.
        """
        if self.winback.is_winback or self.is_first:
            return False
        told = all(c.is_repeat for picked in laid.chosen.picked for _, c in picked)
        shows_movement = any(isinstance(b, ChartBlock | QuoteBlock) for b in laid.blocks)
        return (
            told
            and not shows_movement
            and not calendar.events
            and self._ladder.wind_down is None
            and self._ladder.goal_question is wind_down.GoalQuestion.ASKED
        )

    @override
    async def voice(self, inputs: VoiceInputs) -> VoiceRequest:
        ladder = self._ladder
        user_id = self.user.id
        lookback = await format_lookback_block(user_id, inputs.reads, self.lookback, self.clock)
        # A user who stopped coming back is offered fewer briefs, never silently dropped.
        offer_lighter = await activity_status_of(user_id) == ActivityStatus.IDLE
        facts = inputs.facts
        goal = format_goal_block(self.goals)
        blocks = VoicePromptBlocks(
            reader=reader_block(self.user),
            facts=facts.block,
            goal=goal,
            lookback=lookback,
            replies=await chat_sync.format_replies_block(user_id, self.since),
            setup=await _setup_block(
                self.user, self.state, first_week=ladder.first_week, offer_lighter=offer_lighter
            ),
            signals=inputs.signals,
        )
        prompt = build_briefing_voice_prompt(
            date_local=self.clock.date_str,
            blocks=blocks,
            situation=VoiceSituation(
                winback=self.winback.is_winback and ladder.wind_down is None,
                is_first_briefing=self.is_first,
                wind_down=ladder.wind_down,
                first_week=ladder.first_week,
                offer_lighter_cadence=offer_lighter,
                goal_asked_recently=ladder.goal_question is wind_down.GoalQuestion.ASKED,
            ),
            recent=inputs.recent,
            fence=untrusted_fence(),
        )
        quiet_lead = self.winback.is_winback or ladder.wind_down is not None
        return VoiceRequest(
            prompt=prompt,
            writing=Writing(
                # What was done since the last brief, and the goals they stated, are the user's own
                # record, quotable as they stand.
                values=replace(
                    facts.values, quoted=facts.values.quoted | figures_in([lookback, goal])
                ),
                lead=None if quiet_lead else facts.lead,
                recent=inputs.recent,
                grounds=f"{facts.block}\n{inputs.signals}",
            ),
        )

    @override
    def mood(self, draft: BriefVoice) -> BriefingMood:
        return BriefingMood.WINBACK if self.winback.is_winback else draft.mood

    @override
    def pushes(self, payload: BriefingPayload) -> bool:
        """Push a brief with anything in it.

        The ladder's goal question, warning and goodbye, and a winback, are messages in their
        own right, so they push even on an otherwise empty day.
        """
        empty = not payload.blocks and not payload.undrawn and not payload.calendar
        return not empty or self._ladder.wind_down is not None or self.winback.is_winback

    @override
    async def settle(self) -> None:
        """Clear the bootstrap and the ladder's rung."""
        await clear_bootstrap(self.state)
        await wind_down.leave_idle_ladder(self.user.id, self._ladder)


async def stand_daily(
    user: UserDocument, state: BriefingStateDocument, clock: UserClock
) -> DailyStanding | BriefingRunOutcome:
    """Read where the reader stands today, or how the run ends before any model cost."""
    dstate = await wake_or_skip(state)
    if dstate is None:
        return BriefingRunOutcome.DORMANT
    goals = await stated_goals(user.id, user)
    if bootstrap_should_skip(state, bool(goals)):
        log.info("briefing.bootstrap_pending_skip", user_id=user.id)
        return BriefingRunOutcome.BOOTSTRAP_PENDING
    last = await last_brief(user.id, clock, BriefingKind.DAILY)
    winback = await compute_winback_state(user)
    # Gone-quiet backoff: a winback already went out and the user is still silent.
    if winback.should_back_off:
        log.info("briefing.winback_backoff", user_id=user.id, unacknowledged=winback.unacknowledged)
        return BriefingRunOutcome.WINBACK_BACKOFF
    return DailyStanding(
        user=user,
        state=state,
        clock=clock,
        goals=goals,
        lookback=Lookback(last=last, since=lookback_since(clock, last)),
        winback=winback,
        is_first=not await briefing_repository.has_daily_briefing(user.id),
        prior=dstate,
    )


async def _setup_block(
    user: UserDocument, state: BriefingStateDocument, *, first_week: bool, offer_lighter: bool
) -> str:
    """Return the account facts a first-week tip or a lighter-cadence offer may cite."""
    lines: list[str] = []
    if offer_lighter:
        slots = user_brief_slots(user, state.schedule)
        lines.append(f"Their briefs now: {describe_briefing_schedule(slots)}.")
    if first_week:
        connected: list[ConnectedIntegration] = await get_connected_integrations_named(user.id)
        apps = [integration["name"] for integration in connected]
        lines.append(f"Apps they've connected: {', '.join(apps) if apps else 'none yet'}.")
    return "\n".join(lines)
