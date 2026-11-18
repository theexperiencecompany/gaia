"""The weekly digest's standing: the week since Monday, said the same to every reader."""

from dataclasses import dataclass
from datetime import datetime

from typing_extensions import override

from app.agents.prompts.briefing_prompts import VoicePromptBlocks, build_weekly_voice_prompt
from app.constants.briefing import BriefingRunOutcome
from app.models.brief_payload_models import BriefingMood, BriefingPayload, BriefVoice
from app.models.user_models import UserDocument
from app.services.briefing import dormancy
from app.services.briefing.calendar_read import CalendarRead
from app.services.briefing.candidates.pool import GatheredCandidates
from app.services.briefing.clock import UserClock
from app.services.briefing.fact_pool.pool import FactPool
from app.services.briefing.goals import StatedGoal, format_goal_block, stated_goals
from app.services.briefing.prose import Writing, reader_block
from app.services.briefing.sections import Laid
from app.services.briefing.standing import Standing, VoiceInputs, VoiceRequest
from app.services.hil.utils import untrusted_fence
from shared.py.wide_events import log


@dataclass(frozen=True)
class WeeklyStanding(Standing):
    """The digest's standing: it looks back over this week, from Monday."""

    user: UserDocument
    clock: UserClock
    goals: list[StatedGoal]

    @override
    @property
    def since(self) -> datetime:
        return self.clock.this_week().start

    @override
    async def climbed(self, gathered: GatheredCandidates) -> "WeeklyStanding":
        return self

    @override
    def quiet_before_composing(self, pool: FactPool) -> bool:
        """Say whether the week holds nothing to recap: nothing done, due, waiting, found or ahead.

        Undated todos of their own are backlog, never a week's news; a goal whose work moved or
        sat stuck all week is the recap's first answer.
        """
        return all(c.backlog for c in pool.items.values()) and not any(
            goal.done or goal.stalled for goal in pool.goals
        )

    @override
    def quiet_after_composing(self, laid: Laid, calendar: CalendarRead) -> bool:
        return False

    @override
    async def voice(self, inputs: VoiceInputs) -> VoiceRequest:
        facts = inputs.facts
        blocks = VoicePromptBlocks(
            reader=reader_block(self.user),
            facts=facts.block,
            goal=format_goal_block(self.goals),
            signals=inputs.signals,
        )
        return VoiceRequest(
            prompt=build_weekly_voice_prompt(
                date_local=self.clock.date_str,
                blocks=blocks,
                recent=inputs.recent,
                fence=untrusted_fence(),
            ),
            writing=Writing(
                values=facts.values,
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
    async def settle(self) -> None:
        return None


async def stand_weekly(user: UserDocument, clock: UserClock) -> WeeklyStanding | BriefingRunOutcome:
    """Read the digest's standing; a dormant loop has nothing to zoom out on.

    The daily run owns reactivation, so this only reads whether the user came back.
    """
    dstate = dormancy.state_from_user(user)
    if (
        dstate.dormant_since
        and await dormancy.latest_activity_since(user.id, dstate.dormant_since) is None
    ):
        log.info("briefing.weekly_dormant_skip", user_id=user.id)
        return BriefingRunOutcome.DORMANT
    return WeeklyStanding(user=user, clock=clock, goals=await stated_goals(user.id, user))
