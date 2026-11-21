"""How a run composes and voices its brief, and what its message links."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from tests.briefing_run_world import (
    BRIEF_ID,
    BRIEF_LINK,
    DATE,
    USER,
    VOICE,
    World,
    brief_work,
    completions,
    composed,
    delivered_plan,
    fact_id,
    items_block,
    own,
    own_open,
    salvaged,
    stored_brief,
    todo_link,
    tracked,
    weekly_reply,
    winback,
    wrote,
)
from tests.helpers import captured_wide_event

from app.agents.core import agent as agent_module
from app.agents.llm.client import metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
from app.agents.prompts.briefing_prompts import (
    RecentLines,
)
from app.constants.briefing import (
    BRIEF_VOICE_LABEL,
    MAX_VOICE_ATTEMPTS,
    BriefForm,
    BriefingKind,
    BriefingRunOutcome,
)
from app.models.brief_composition_models import BriefComposition
from app.models.brief_payload_models import (
    BriefVoice,
)
from app.models.brief_slot_models import CountName
from app.models.short_link_models import ShortLinkTargetType
from app.services.analytics_service import AIFeature
from app.services.briefing.goals import StatedGoal
from app.services.briefing.pipeline import run_brief
from app.services.briefing.work import TrackedWork
from app.services.cost_budget import DAILY_BUDGET_STOP_FREE

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestTheComposition:
    async def test_a_composition_broken_on_every_attempt_still_sends_what_holds_of_it(
        self, world: World
    ) -> None:
        """Dhruv's Nov 11: a heading typing a stray "9" failed the brief and he got nothing."""
        world.track(brief_work())
        world.composer.side_effect = None
        world.composer.return_value = BriefComposition.model_validate(
            {
                "blocks": [
                    items_block(
                        "9 things waiting",
                        [
                            {
                                "id": 1,
                                "action": "approve",
                                "outcome": None,
                                "title": "Priya reply",
                                "detail": None,
                            }
                        ],
                    )
                ]
            }
        )

        async with captured_wide_event() as event:
            assert await run_brief(USER, BriefingKind.DAILY) is BriefingRunOutcome.SENT

        assert world.composer.await_count == 2
        assert len(salvaged(event, "composition")) == 1
        (section,) = world.stored().sections
        assert (section.title, [i.text for i in section.items]) == (
            "Replies to send",
            ["Priya reply"],
        )
        world.notify.assert_awaited()

    async def test_the_composition_is_one_call_metered_to_the_user(self, world: World) -> None:
        world.track(brief_work())

        await run_brief(USER, BriefingKind.DAILY)

        assert world.composer.await_args.kwargs["config"] == metered_config(USER)


class TestTheVoice:
    async def test_the_voice_is_one_structured_call_metered_to_the_user_never_an_agent_turn(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Live: a capped user's voice turn came back as the usage-limit stop text, and the brief failed."""
        capped_turn = AsyncMock(return_value=SimpleNamespace(message=DAILY_BUDGET_STOP_FREE))
        monkeypatch.setattr(agent_module, "call_agent_silent", capped_turn)

        await run_brief(USER, BriefingKind.DAILY)

        schema, _ = world.voice.await_args.args
        kwargs = world.voice.await_args.kwargs
        assert schema is BriefVoice
        assert (kwargs["label"], kwargs["config"]) == (BRIEF_VOICE_LABEL, metered_config(USER))
        assert kwargs["options"].schema_held
        assert world.voice.await_count == 1
        capped_turn.assert_not_awaited()
        assert world.stored().headline == VOICE["headline"]
        assert AIFeature.for_label(BRIEF_VOICE_LABEL) is AIFeature.BRIEFING

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_voice_unreadable_on_every_attempt_still_sends_the_brief_plainly(
        self, world: World, kind: BriefingKind
    ) -> None:
        world.replies = [MalformedStructuredOutputError("invalid JSON: Expecting value")]

        async with captured_wide_event() as event:
            assert await run_brief(USER, kind) is BriefingRunOutcome.SENT

        assert world.voice.await_count == MAX_VOICE_ATTEMPTS
        assert len(salvaged(event, "voice")) == 1
        world.sent_plainly()

    async def test_the_stored_brief_holds_each_slot_filled_from_its_fact(
        self, world: World
    ) -> None:
        world.replies = [
            {**VOICE, "headline": "Sequoia at [[fact:<fact of Sequoia>.time]]", "message": "-"}
        ]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.stored().headline == "Sequoia at 11:00 AM"

    async def test_a_count_the_voice_was_shown_is_voiced_by_its_slot(self, world: World) -> None:
        """Regression: 5 open todos were shown to the model, then rejected when it said 5."""
        world.todos.add(*own_open(5))
        world.calendar = []
        world.replies = [{**VOICE, "headline": "[[count:gaia_todos]] open todos, a quiet morning"}]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.writing is not None
        assert world.writing.values.counts[CountName.OPEN_TODOS] == 5
        assert world.voice.await_count == 1
        assert world.stored().headline == "5 open todos, a quiet morning"

    async def test_the_voice_is_told_what_the_todo_list_holds_beside_gaias_open_work(
        self, world: World
    ) -> None:
        world.todos.add(
            *own_open(5, overdue=1),
            tracked("t1", "Draft the board memo"),
            tracked("t2", "Reconcile the invoices"),
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.writing is not None
        counts = world.writing.values.counts
        assert (
            counts[CountName.OPEN_TODOS],
            counts[CountName.OVERDUE_TODOS],
            counts[CountName.OPEN_TRACKED],
        ) == (5, 1, 2)
        assert (
            "The user's own open todos are counted in [COUNTS]; never voice that list as clear or"
            " empty. [[count:overdue_gaia_todos]] of them are past due: say that count in one"
            " plain line that names them as the user's GAIA todos (\"[[count:overdue_gaia_todos]]"
            " of your GAIA todos is overdue\"), never beside another app's items, and never"
            " list them. GAIA's tracked work holds [[count:open_tracked]] open beside them."
        ) in world.writing.grounds.splitlines()

    async def test_the_voice_is_held_to_what_recent_briefs_printed_of_every_kind(
        self, world: World
    ) -> None:
        world.briefs_read(
            [
                stored_brief(
                    "2026-10-13", BriefForm.EDITION, message="\n  Priya replied overnight.\nMore."
                ),
                stored_brief("2026-10-12", BriefForm.EDITION, BriefingKind.WEEKLY, message=None),
            ]
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.briefings.calls_to("list_recent").count(call(USER, limit=5)) == 1
        assert world.writing is not None and world.writing.recent == RecentLines(
            headlines=["Your morning, sorted"] * 2,
            ledes=["Everything else is moving."] * 2,
            captions=["Onward."] * 2,
            openings=["Priya replied overnight."],
        )

    async def test_a_retry_of_a_brief_that_never_went_out_is_not_held_to_its_own_draft(
        self, world: World
    ) -> None:
        """Regression: a same-day retry was told it repeated the undelivered brief it replaces."""
        undelivered = stored_brief(DATE, BriefForm.EDITION, headline=VOICE["headline"])
        world.briefs_read(
            [
                undelivered.model_copy(
                    update={
                        "delivery": delivered_plan().model_copy(
                            update={"done": [], "completed_at": None}
                        )
                    }
                )
            ]
        )

        await run_brief(USER, BriefingKind.DAILY)

        assert world.voice.await_count == 1
        assert world.stored().headline == VOICE["headline"]

    async def test_a_message_that_leaves_out_the_lead_is_sent_back_until_it_names_it(
        self, world: World
    ) -> None:
        world.track(brief_work())
        world.composer.side_effect = composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )
        world.replies = [
            wrote("The investor update went out."),
            wrote("[Priya's reply](fact:<fact of Priya>) is first; the investor update went out."),
        ]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.writing is not None
        assert world.writing.lead == fact_id(world.writing, "Approve the Priya reply")
        assert world.voice.await_count == 2
        assert world.stored().message == "Priya's reply is first; the investor update went out."

    async def test_a_winback_need_not_refer_to_the_lead_and_reads_as_a_winback(
        self, world: World, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        winback(world)
        world.track(brief_work())
        world.composer.side_effect = composed(
            {"Done overnight": ["Investor update"]},
            lead=("Approve the Priya reply", "Send the reply once you approve"),
        )
        world.replies = [wrote("The investor update went out.")]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.writing is not None and world.writing.lead is None
        assert world.voice.await_count == 1
        assert (world.stored().message, world.stored().mood) == (
            "The investor update went out.",
            "winback",
        )

    async def test_a_figure_from_what_was_done_since_the_last_brief_may_be_typed(
        self, world: World
    ) -> None:
        """E2E busy day: the message named a closed thread from the look-back and was refused."""
        # Done by the user, so only the look-back says it: a daily never places their own work.
        world.todos.add(*completions(user=[own("q3", "Q3 board memo")]))
        world.replies = [{**VOICE, "lede": "The Q3 board memo went out."}]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.writing is not None and "Q3" in world.writing.values.quoted
        assert world.stored().lede == "The Q3 board memo went out."
        assert world.voice.await_count == 1

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_a_figure_from_the_goal_they_stated_may_be_typed(
        self, world: World, monkeypatch: pytest.MonkeyPatch, kind: BriefingKind
    ) -> None:
        """Replay of Nov 8: "a goal of 300 users" was refused, and the retry dropped the goal."""
        goal = StatedGoal("Their growth goal for GAIA is 300 users.")
        world.goals = [goal]
        reply = weekly_reply() if kind is BriefingKind.WEEKLY else VOICE
        world.replies = [{**reply, "lede": "Still aiming for 300 users?"}]

        await run_brief(USER, kind)

        assert world.stored().lede == "Still aiming for 300 users?"
        assert world.voice.await_count == 1

    @pytest.mark.parametrize("kind", [BriefingKind.DAILY, BriefingKind.WEEKLY])
    async def test_the_day_a_goal_was_mentioned_may_be_quoted(
        self, world: World, kind: BriefingKind
    ) -> None:
        """Replay of Nov 8: "you mentioned on June 17" was refused, the 17 in no fact's words."""
        world.goals = [StatedGoal("Their growth goal for GAIA is 300 users.")]
        world.goals_mentioned_at = datetime(2026, 6, 17, 9, tzinfo=UTC)
        reply = weekly_reply() if kind is BriefingKind.WEEKLY else VOICE
        world.replies = [{**reply, "lede": "You mentioned 300 users on Jun 17; still the plan?"}]

        await run_brief(USER, kind)

        assert world.stored().lede == "You mentioned 300 users on Jun 17; still the plan?"
        assert world.voice.await_count == 1


class TestLinks:
    """A forwarded brief exposes exactly the deliverables its message links, nothing more."""

    @pytest.fixture(autouse=True)
    def keyed_mint(self, world: World) -> None:
        def mint(user_id: str, target_type: ShortLinkTargetType, target_id: str) -> str:
            if user_id != USER:
                raise AssertionError(f"minted for {user_id!r}, not the brief's owner")
            if target_type is ShortLinkTargetType.TODO_DELIVERABLE:
                return todo_link(target_id)
            return BRIEF_LINK

        world.mint.side_effect = mint
        world.track(
            TrackedWork(
                completed=[tracked("c1", "Deck", canvas_content="Ten slides")],
                blocked=[tracked("b1", "Reply", canvas_content="A draft reply")],
            )
        )

    async def test_a_linked_item_gets_its_link_on_its_phrase_and_an_unlinked_one_is_never_minted(
        self, world: World
    ) -> None:
        world.replies = [wrote("the deck is done\n[the reply](fact:<fact of Reply>) waits on you")]

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == f"the deck is done\n[the reply]({todo_link('b1')}) waits on you"
        links = {it.todo_id: it.link for sec in payload.sections for it in sec.items}
        assert links == {"b1": todo_link("b1"), "c1": None}
        assert [c.args[2] for c in world.mint.await_args_list] == ["b1", BRIEF_ID]
        assert f"[the reply]({todo_link('b1')}) waits" in world.post.await_args.kwargs["text"]

    async def test_a_slot_with_no_link_behind_it_leaves_its_phrase_as_text(
        self, world: World
    ) -> None:
        """Sharing turned off (or a failed mint) leaves the sentence, not a raw slot."""
        world.mint.side_effect = lambda user_id, target_type, target_id: (
            None if target_type is ShortLinkTargetType.TODO_DELIVERABLE else BRIEF_LINK
        )
        world.replies = [wrote("the [reply](fact:<fact of Reply>) waits")]

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert payload.message == "the reply waits"
        assert all(it.link is None for sec in payload.sections for it in sec.items)
