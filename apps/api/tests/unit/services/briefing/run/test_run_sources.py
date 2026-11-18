"""What reaches a brief: held results, one item per subject, signals, desk findings, approvals."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import call

import pytest
from tests.briefing_run_world import (
    DIGEST_REPORT,
    DOCS,
    LOGIN,
    NOW,
    USER,
    World,
    brief_work,
    composed,
    failed_run,
    held,
    remembered,
    scouted,
    skipped,
    tracked,
    wrote,
)

from app.constants.briefing import (
    BriefAction,
    BriefingKind,
    BriefItemSource,
    BriefOutcome,
)
from app.models.brief_slot_models import CountName
from app.models.hil_models import ApprovalLedgerDocument
from app.models.scout_models import (
    ScoutSkipReason,
    Sighting,
)
from app.services.briefing.pipeline import run_brief
from app.services.briefing.work import TrackedWork
from app.services.todos.inbox_desk import INBOX_DESK_REF

pytestmark = pytest.mark.usefixtures("fake_redis")


class TestHeldResults:
    """Results held for the brief are candidates like any other, cleared once the brief went out."""

    async def test_a_held_result_joins_gaias_work_and_every_held_result_is_cleared(
        self, world: World
    ) -> None:
        world.track(brief_work())
        world.held = [held("h1", "Paper digest", DIGEST_REPORT), held("h2", "Digest", "first")]
        world.composer.side_effect = composed(
            {
                "Needs you": ["Approve the Priya reply"],
                "GAIA's work": ["Paper digest: 3 new papers on retrieval", "Investor update"],
            }
        )

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [(s.title, [i.text for i in s.items]) for s in payload.sections] == [
            ("Needs you", ["Approve the Priya reply"]),
            ("GAIA's work", ["Paper digest: 3 new papers on retrieval", "Investor update"]),
        ]
        # Nothing left out is lost: it is on the brief's full page.
        assert [(i.title, i.app, i.kind) for i in payload.uncomposed] == [
            ("Digest: first", "GAIA", "note")
        ]
        # A report's body never reaches the voice to be claimed from.
        assert "two cite your draft" not in world.voice.await_args.args[1]
        assert (world.pending.consumed, world.held) == ([["h1", "h2"]], [])

    async def test_an_item_already_in_the_brief_is_shown_once_and_still_cleared(
        self, world: World
    ) -> None:
        world.track(TrackedWork(completed=[tracked("c1", "Digest: 3 new papers")]))
        world.held = [
            held("h1", "Digest", "3 new papers\nmore detail"),
            held("h2", "Paper digest", DIGEST_REPORT),
            held("h3", "Paper  digest", DIGEST_REPORT),
        ]

        await run_brief(USER, BriefingKind.DAILY)

        texts = [i.text for s in world.stored().sections for i in s.items]
        assert texts == ["Paper digest: 3 new papers on retrieval", "Digest: 3 new papers"]
        assert [sorted(ids) for ids in world.pending.consumed] == [["h1", "h2", "h3"]]
        assert world.held == []

    async def test_a_held_result_with_a_blank_report_shows_only_its_source(
        self, world: World
    ) -> None:
        world.held = [held("h1", "Digest", "  \n ")]

        await run_brief(USER, BriefingKind.DAILY)

        assert [i.text for s in world.stored().sections for i in s.items] == ["Digest"]


class TestOneSubjectIsOneItem:
    async def test_todos_on_one_subject_reach_the_voice_and_the_page_as_one_counted_item(
        self, world: World
    ) -> None:
        """Regression: three approval requests for one Acme MSA renewal became one line with three links."""
        world.track(
            TrackedWork(
                blocked=[
                    tracked("b1", "Approve the Acme MSA renewal"),
                    tracked("b2", "Approve the Acme MSA renewal"),
                    tracked("b3", "approve the  Acme MSA renewal"),
                    tracked("b4", "Reply to Daniel"),
                ]
            )
        )

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        items = [(it.text, it.todo_id, it.count) for s in payload.sections for it in s.items]
        assert items == [("Approve the Acme MSA renewal", "b1", 3), ("Reply to Daniel", "b4", 1)]
        assert world.fact("Acme MSA renewal").count == 3
        assert world.writing is not None
        assert world.writing.values.counts[CountName.NEEDS_YOU] == 2
        assert [(s.value, s.label) for s in payload.stats] == [("2", "waiting on you")]


class TestSourcesReachTheBrief:
    async def test_an_app_signal_a_desk_finding_an_approval_and_a_failed_run_each_land_in_place(
        self, world: World
    ) -> None:
        world.scouts = [*scouted(LOGIN), skipped("Notion")]
        world.todos.add(tracked("desk-1", "Inbox desk", external_ref=INBOX_DESK_REF))
        world.held = [
            held("h1", "Inbox desk", "Stripe payout of 2,400 dollars landed").model_copy(
                update={"source": BriefItemSource.TODO, "source_id": "desk-1"}
            )
        ]
        pending = [
            ApprovalLedgerDocument(
                approval_id="ap_1",
                conversation_id="conv-1",
                user_id=USER,
                fingerprint="fp-1",
                tool_name="GMAIL_SEND_EMAIL",
                summary="Send the invoice to Acme",
            )
        ]
        world.approvals.rows = pending
        failed_run(world, started_at=NOW - timedelta(hours=2))

        await run_brief(USER, BriefingKind.DAILY)

        payload = world.stored()
        assert [
            (s.title, [(i.text, i.app, i.kind, i.action or i.outcome) for i in s.items])
            for s in payload.sections
        ] == [
            (
                "Needs you",
                [
                    ("Send the invoice to Acme", "Gmail", "you", BriefAction.APPROVE),
                    ("CRM sync failed", "GAIA", "failed", BriefAction.RETRY),
                    ("Fix the login redirect", "Linear", "you", BriefAction.REPLY),
                ],
            ),
            (
                "From your apps",
                [("Stripe payout of 2,400 dollars landed", "Gmail", "note", BriefOutcome.FINISHED)],
            ),
        ]
        assert payload.sections[0].items[2].url == LOGIN.url
        assert payload.sources_read == ["Gmail", "Linear", "Google Calendar"]
        assert [(u.app, u.reason) for u in payload.sources_unavailable] == [
            ("Notion", ScoutSkipReason.FAILED)
        ]
        event = world.capture.call_args.args[1]
        assert (event.block_kinds, event.item_count, event.pool_item_count, event.source_count) == (
            ["items", "items"],
            4,
            5,
            3,
        )
        assert world.pending.consumed == [["h1"]]
        # Everything placed is remembered as shown; the held finding is cleared instead.
        assert world.memories.calls_to("mark_shown") == [
            call(
                USER,
                [
                    Sighting("gaia", "approval:ap_1", "you"),
                    Sighting("gaia", "workflow:wf-sync", "failed"),
                    Sighting("linear", LOGIN.external_id, LOGIN.state),
                ],
                NOW,
            )
        ]

    async def test_the_signals_placed_reach_the_voice_with_what_earlier_briefs_said(
        self, world: World
    ) -> None:
        world.scouts = scouted(LOGIN, DOCS)
        earlier = remembered("ENG-12", "Todo")
        world.memory = [earlier.model_copy()]
        world.composer.side_effect = composed(
            {"Needs you": [LOGIN.title], "From your apps": [DOCS.title]},
            reports=frozenset({DOCS.title}),
        )
        world.replies = [
            wrote("[the login redirect](fact:<fact of Fix the login>) still needs you.")
        ]

        await run_brief(USER, BriefingKind.DAILY)

        assert [(c.signal.title, c.memory) for _, c in world.signals if c.signal] == [
            (LOGIN.title, earlier),
            (DOCS.title, None),
        ]
        assert world.voice_prompt.call_args.kwargs["blocks"].signals
        assert world.stored().message == f"[the login redirect]({LOGIN.url}) still needs you."

    async def test_every_signal_the_brief_placed_is_marked_shown_named_or_not(
        self, world: World
    ) -> None:
        """Regression: a signal placed in the edition but not named in the message came back as new."""
        world.scouts = scouted(LOGIN, DOCS)
        world.composer.side_effect = composed(
            {"Needs you": [LOGIN.title], "From your apps": [DOCS.title]},
            reports=frozenset({DOCS.title}),
        )
        world.replies = [wrote("[[fact:<fact of Fix the login>]] is yours today.")]

        await run_brief(USER, BriefingKind.DAILY)

        assert world.memories.calls_to("mark_shown") == [
            call(
                USER,
                [
                    Sighting("linear", LOGIN.external_id, LOGIN.state),
                    Sighting("linear", DOCS.external_id, DOCS.state),
                ],
                NOW,
            )
        ]
        assert world.memories.calls_to("record_seen") == [call(USER, [LOGIN, DOCS], NOW)]
        assert [(m.external_id, m.times_shown) for m in world.memory] == [
            (LOGIN.external_id, 1),
            (DOCS.external_id, 1),
        ]
        _, updates = world.stored().sections
        assert [(i.text, i.kind) for i in updates.items] == [(DOCS.title, "note")]

    async def test_a_day_with_only_signals_is_pushed_and_counted(self, world: World) -> None:
        world.calendar = []
        world.scouts = scouted(DOCS)

        await run_brief(USER, BriefingKind.DAILY)

        world.post.assert_awaited_once()
        assert world.capture.call_args.args[1].signal_count == 1
