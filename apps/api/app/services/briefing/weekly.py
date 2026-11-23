"""The weekly digest's standing: the week since Monday, said the same to every reader."""

from dataclasses import dataclass, replace
from datetime import datetime

from typing_extensions import override

from app.agents.prompts.briefing_prompts import VoicePromptBlocks, build_weekly_voice_prompt
from app.constants.briefing import BriefingRunOutcome
from app.models.brief_document_models import BriefSettlement
from app.models.brief_payload_models import BriefingMood, BriefingPayload, BriefVoice
from app.models.briefing_state_models import BriefingStateDocument, BriefingWindDown
from app.models.user_models import UserDocument
from app.services.briefing import wind_down
from app.services.briefing.calendar_read import CalendarRead
from app.services.briefing.candidates.pool import GatheredCandidates
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.goals import StatedGoal, format_goal_block, stated_goals
from app.services.briefing.lifecycle import wake_or_skip
from app.services.briefing.prose import Writing, reader_block
from app.services.briefing.sections import Laid
from app.services.briefing.slots import figures_in
from app.services.briefing.standing import Standing, VoiceInputs, VoiceRequest
from app.services.hil.utils import untrusted_fence


@dataclass(frozen=True)
class WeeklyStanding(Standing):
    """The digest's standing: it looks back over this week, from Monday."""

    user: UserDocument
    state: BriefingStateDocument
    clock: UserClock
    goals: list[StatedGoal]
    #: Where the idle ladder stood before this digest.
    prior: BriefingWindDown
    #: This digest is a weekly-only reader's goodbye: the loop winds down after it.
    goodbye: bool = False

    @override
    @property
    def since(self) -> datetime:
        return self.clock.this_week().start

    @override
    async def climbed(self, gathered: GatheredCandidates, pool: FactPool) -> "WeeklyStanding":
        """Count an empty digest on the ladder of a user the digest is the only brief of."""
        goodbye = await wind_down.climb_weekly_ladder(
            self.user,
            self.state.schedule,
            self.prior,
            self.clock.date_str,
            has_news=not _week_is_empty(pool),
            has_goal=bool(self.goals),
        )
        return replace(self, goodbye=goodbye)

    @override
    def quiet_before_composing(self, pool: FactPool) -> bool:
        """Say whether the digest is the quiet note: an empty week, unless it says the goodbye."""
        return _week_is_empty(pool) and not self.goodbye

    @override
    def quiet_after_composing(self, laid: Laid, calendar: CalendarRead) -> bool:
        return False

    @override
    async def voice(self, inputs: VoiceInputs) -> VoiceRequest:
        facts = inputs.facts
        goal = format_goal_block(self.goals)
        blocks = VoicePromptBlocks(
            reader=reader_block(self.user),
            facts=facts.block,
            goal=goal,
            signals=inputs.signals,
        )
        return VoiceRequest(
            prompt=build_weekly_voice_prompt(
                date_local=self.clock.date_str,
                blocks=blocks,
                recent=inputs.recent,
                fence=untrusted_fence(),
                goodbye=self.goodbye,
            ),
            writing=Writing(
                # The goals they stated are their own words, quotable as they stand.
                values=replace(facts.values, quoted=facts.values.quoted | figures_in([goal])),
                lead=facts.lead,
                recent=inputs.recent,
                grounds=f"{facts.block}\n{inputs.signals}",
            ),
        )

    @override
    def mood(self, draft: BriefVoice) -> BriefingMood:
        return BriefingMood.WEEKLY

    @override
    def pushes(self, payload: BriefingPayload) -> bool:
        return True

    @override
    def settlement(self) -> BriefSettlement:
        return BriefSettlement(winds_down=self.goodbye)


def _week_is_empty(pool: FactPool) -> bool:
    """Say whether the week holds nothing to recap: nothing done, due, waiting, found or ahead.

    Undated todos of their own are backlog, never a week's news; a goal whose work moved or
    sat stuck all week is the recap's first answer.
    """
    return all(c.backlog for c in pool.items.values()) and not any(
        goal.done or goal.stalled for goal in pool.goals
    )


async def stand_weekly(
    user: UserDocument, state: BriefingStateDocument, clock: UserClock
) -> WeeklyStanding | BriefingRunOutcome:
    """Read the digest's standing; a wound-down loop has nothing to zoom out on.

    Activity since the loop wound down wakes the loop here as on the daily.
    """
    dstate = await wake_or_skip(state)
    if dstate is None:
        return BriefingRunOutcome.DORMANT
    return WeeklyStanding(
        user=user,
        state=state,
        clock=clock,
        goals=await stated_goals(user.id),
        prior=dstate,
    )
