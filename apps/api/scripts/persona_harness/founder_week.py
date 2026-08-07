"""The founder-week capstone: a full simulated week against a live stack.

Signup -> goal -> day-zero -> five simulated weekdays (brief -> approve ->
executor completes -> one blocker+answer on day 2 -> an ignored proposal left
to expire) -> Sunday weekly digest. Every touchpoint is recorded verbatim in
the report timeline; day 1 runs a real ARQ execution, days 2-5 may force-
complete via Mongo if the real run is too slow (mission brief I.7).
"""

from __future__ import annotations

from scripts.persona_harness import steps
from scripts.persona_harness.steps import HarnessContext

_GOAL_FOCUS = "raise a pre-seed; ship daily"
_DAY1_EXECUTION_TIMEOUT_S = 90.0


async def run(ctx: HarnessContext) -> None:
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)
    await steps.set_focus(ctx, _GOAL_FOCUS)
    await steps.provision_briefing_workflow(ctx)

    await steps.trigger_briefing(ctx, kind="daily")
    day_zero = await steps.get_latest_briefing(ctx, kind="daily")
    ctx.report.expect(
        day_zero["payload"]["headline"] != "",
        "day-zero brief produced a real headline",
        expected="non-empty headline",
        found=day_zero["payload"]["headline"],
    )

    template_families: list[str] = []
    ignored_proposal_id: str | None = None

    for weekday in range(1, 6):
        await steps.trigger_briefing(ctx, kind="daily")
        briefing = await steps.get_latest_briefing(ctx, kind="daily")
        family = briefing["payload"].get("template_family")
        if family:
            template_families.append(family)

        proposal_id = await steps.pick_latest_proposal(ctx)
        if proposal_id is None and weekday == 1:
            # Day 1 must run real execution regardless of whether the brief
            # itself proposed something — fall back to a harness-seeded
            # proposal rather than silently skipping the real-execution proof.
            proposal_id = await steps.insert_todo(
                ctx,
                title="research pre-seed investors and draft intro DMs",
                assignee="gaia",
                kind="task",
                execution_status="proposed",
                serves=_GOAL_FOCUS,
            )
            ctx.log(
                actor="harness",
                surface="founder-week",
                content=f"day 1: brief proposed nothing — seeded fallback proposal {proposal_id} "
                "so real execution is still exercised",
            )
        if proposal_id is not None:
            resp = await steps.approve_todo(ctx, proposal_id)
            ctx.report.expect(
                resp.status_code == 200,
                f"day {weekday}: approve on the brief's proposal succeeds",
                expected=200,
                found=resp.status_code,
            )
            if weekday == 1:
                status = await steps.wait_for_execution(
                    ctx, proposal_id, timeout_s=_DAY1_EXECUTION_TIMEOUT_S
                )
                ctx.report.expect(
                    status in ("done", "needs_you", "failed"),
                    "day 1: the ARQ worker actually drove the approved todo out of queued "
                    "(real execution, not a fixture shortcut)",
                    expected="done | needs_you | failed",
                    found=status,
                )
            else:
                status = await steps.wait_for_execution(ctx, proposal_id, timeout_s=10.0)
                if status in ("queued", "running"):
                    await steps.force_complete_todo(ctx, proposal_id)
                    ctx.log(
                        actor="harness",
                        surface="mongo:force_complete",
                        content=f"day {weekday}: real execution didn't settle in 10s, force-completed {proposal_id}",
                    )
        else:
            ctx.log(
                actor="harness",
                surface="founder-week",
                content=f"day {weekday}: no proposal in the brief to approve",
            )

        if weekday == 2:
            blocker_id = await steps.insert_todo(
                ctx,
                title="confirm the SAFE cap with counsel",
                assignee="gaia",
                kind="task",
                execution_status="queued",
                serves=_GOAL_FOCUS,
            )
            question = "Should the SAFE cap be $8M or $10M post-money?"
            await steps.run_executor_task(
                ctx,
                sim_task=(
                    f'[[tool:block_todo {{"todo_id":"{blocker_id}","question":"{question}"}}]] '
                    "[[say:Blocked, need your call.]]"
                ),
                agent_task=(
                    f"Call block_todo now for tracked todo id {blocker_id} with question: "
                    f"{question!r}. Do not do anything else."
                ),
            )
            blocked = await steps.get_todo(ctx, blocker_id)
            ctx.report.expect(
                blocked is not None and blocked["execution_status"] == "needs_you",
                "day 2: the blocker actually flipped the todo to needs_you",
                expected="needs_you",
                found=blocked["execution_status"] if blocked else None,
            )
            await steps.answer_todo(ctx, blocker_id, "$10M post-money")
            answered = await steps.get_todo(ctx, blocker_id)
            ctx.report.expect(
                answered is not None and answered["execution_status"] == "queued",
                "day 2: answering the blocker re-queues the run",
                expected="queued",
                found=answered["execution_status"] if answered else None,
            )

        if weekday == 2 and ignored_proposal_id is None:
            ignored_proposal_id = await steps.insert_todo(
                ctx,
                title="cold-email 20 more pre-seed funds",
                assignee="gaia",
                kind="task",
                execution_status="proposed",
                serves=_GOAL_FOCUS,
            )
            ctx.log(
                actor="harness",
                surface="founder-week",
                content=f"day 2: seeded an ignored proposal {ignored_proposal_id} — never approved/dismissed",
            )

        await steps.advance_day(ctx, days=1)

    if ignored_proposal_id is not None:
        # advance_day already pushed this proposal's created_at 4 days into the
        # past (seeded day 2, 3 more advances through day 5) — one more day
        # crosses PROPOSAL_TTL_HOURS=72h so curation expires it on the next run.
        await steps.advance_day(ctx, days=1)
        await steps.trigger_briefing(ctx, kind="daily")
        expired = await steps.get_todo(ctx, ignored_proposal_id)
        ctx.report.expect(
            expired is not None and expired["execution_status"] == "expired",
            "the ignored proposal expired via curation rather than lingering forever",
            expected="expired",
            found=expired["execution_status"] if expired else None,
        )

    await steps.trigger_briefing(ctx, kind="weekly")
    weekly = await steps.get_latest_briefing(ctx, kind="weekly")
    ctx.report.expect(
        weekly["payload"]["mood"] == "weekly",
        "the Sunday run produced a weekly-mood payload",
        expected="weekly",
        found=weekly["payload"]["mood"],
    )
    weekly_family = weekly["payload"].get("template_family")
    if weekly_family:
        template_families.append(weekly_family)
    ctx.report.expect(
        len(template_families) == len(set(template_families)),
        "no edition template family repeated across the week's briefings + weekly digest "
        "(shuffled-cycle rotation law)",
        expected="all distinct",
        found=template_families,
    )
