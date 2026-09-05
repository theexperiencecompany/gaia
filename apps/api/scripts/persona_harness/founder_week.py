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

# BriefingPayload.mood's closed set (app/models/briefing_models.py BriefingMood).
_VALID_MOODS = frozenset({"clear", "packed", "idle", "winback", "weekly"})

_GOAL_FOCUS = "raise a pre-seed; ship daily"
# Enough to observe queued -> running (the worker actually engaging the real
# execution path); NOT meant to wait out full completion of a real multi-tool
# research task, which can legitimately run for many minutes.
_DAY1_EXECUTION_TIMEOUT_S = 60.0


async def _day_zero(ctx: HarnessContext) -> None:
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


def _note_rotation_draw(
    ctx: HarnessContext,
    briefing: dict,
    weekday: int,
    seen_briefing_ids: set[str],
    template_families: list[str],
) -> None:
    # Identity of the briefing doc each family came from. A run that skips
    # (bootstrap-pending, dormancy, winback backoff) returns 200 without
    # generating, leaving the previous doc in place — re-reading it would count
    # the same draw again and fake a rotation violation. Only genuinely new
    # briefing documents are rotation evidence.
    family = briefing["payload"].get("template_family")
    briefing_id = str(briefing.get("id") or briefing.get("_id") or "")
    if family and briefing_id not in seen_briefing_ids:
        seen_briefing_ids.add(briefing_id)
        template_families.append(family)
    elif family:
        ctx.log(
            actor="harness",
            surface="founder-week",
            content=(
                f"day {weekday + 1}: briefing run skipped (no new edition doc) — "
                "not counted as a rotation draw"
            ),
        )


async def _proposal_for_day(
    ctx: HarnessContext, weekday: int, ignored_proposal_id: str | None
) -> str | None:
    proposal_id = await steps.pick_latest_proposal(ctx)
    if proposal_id is not None and proposal_id == ignored_proposal_id:
        # pick_latest_proposal just grabs the most recent `proposed` GAIA
        # todo — without this guard, the very next day's iteration would
        # "un-ignore" it by approving it itself, defeating the whole point
        # of leaving it untouched until it expires.
        proposal_id = None
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
    return proposal_id


async def _approve_and_execute(ctx: HarnessContext, proposal_id: str, weekday: int) -> None:
    resp = await steps.approve_todo(ctx, proposal_id)
    ctx.report.expect(
        resp.status_code == 200,
        f"day {weekday}: approve on the brief's proposal succeeds",
        expected=200,
        found=resp.status_code,
    )
    if weekday == 1:
        # A real research+draft task under a real LLM can run for many
        # minutes — blocking the persona on full completion would make
        # this flaky on task complexity, not on correctness. The proof
        # this step exists for is that the worker actually engaged the
        # real execution path rather than a fixture shortcut; leaving
        # `queued` (picked up, now `running` or already settled) is
        # that proof. See `wait_for_execution` — it stops polling the
        # moment status leaves queued/running, so a `running` result
        # here means it was still genuinely mid-flight at the deadline.
        status = await steps.wait_for_execution(
            ctx, proposal_id, timeout_s=_DAY1_EXECUTION_TIMEOUT_S
        )
        ctx.report.expect(
            status != "queued",
            "day 1: the ARQ worker actually engaged the approved todo "
            "(real execution, not a fixture shortcut)",
            expected="running | done | needs_you | failed",
            found=status,
        )
        return
    status = await steps.wait_for_execution(ctx, proposal_id, timeout_s=10.0)
    if status in ("queued", "running"):
        await steps.force_complete_todo(ctx, proposal_id)
        ctx.log(
            actor="harness",
            surface="mongo:force_complete",
            content=f"day {weekday}: real execution didn't settle in 10s, force-completed {proposal_id}",
        )


async def _day2_blocker(ctx: HarnessContext) -> None:
    blocker_id = await steps.insert_todo(
        ctx,
        title="confirm the SAFE cap with counsel",
        assignee="gaia",
        kind="task",
        execution_status="queued",
        serves=_GOAL_FOCUS,
    )
    question = "Should the SAFE cap be $8M or $10M post-money?"
    # Observed live, repeatedly (see blocked-everything persona too):
    # the executor sometimes narrates "I've blocked it" (even writing
    # a canvas note to that effect) without actually invoking
    # block_todo. That mechanism already has a dedicated hard
    # assertion in the blocked-everything persona — here it's an
    # observation, not a gate, so one known-flaky real-LLM miss
    # doesn't abort the rest of the week's simulation.
    blocked = None
    for attempt in range(2):
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
        if blocked is not None and blocked["execution_status"] == "needs_you":
            break
        ctx.log(
            actor="harness",
            surface="founder-week",
            content=f"day 2: block_todo attempt {attempt + 1} did not land "
            f"(execution_status={blocked['execution_status'] if blocked else 'missing'}), retrying",
        )
    landed = ctx.report.observe(
        blocked is not None and blocked["execution_status"] == "needs_you",
        "day 2: the blocker actually flipped the todo to needs_you (within 2 attempts)",
    )
    if not landed:
        ctx.log(
            actor="harness",
            surface="founder-week",
            content="day 2: skipping answer_todo — the blocker never landed "
            "(answer requires needs_you; see blocked-everything for the isolated repro)",
        )
        return
    await steps.answer_todo(ctx, blocker_id, "$10M post-money")
    answered = await steps.get_todo(ctx, blocker_id)
    ctx.report.expect(
        answered is not None and answered["execution_status"] == "queued",
        "day 2: answering the blocker re-queues the run",
        expected="queued",
        found=answered["execution_status"] if answered else None,
    )


async def _seed_ignored_proposal(ctx: HarnessContext) -> str:
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
    return ignored_proposal_id


async def _expire_ignored_proposal(ctx: HarnessContext, ignored_proposal_id: str) -> None:
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


async def _sunday_digest(ctx: HarnessContext, template_families: list[str]) -> None:
    await steps.trigger_briefing(ctx, kind="weekly")
    weekly = await steps.get_latest_briefing(ctx, kind="weekly")
    # `mood` is LLM-chosen from the closed BriefingMood set, not hardcoded to
    # "weekly" in service.py — a week with little real completed work (this
    # capstone's own week, given the LLM-reliability misses logged above) can
    # honestly come back "idle" rather than a padded "weekly" writeup. That's
    # the same no-padding principle the daily brief is held to, so assert the
    # run actually produced a payload, not a specific mood value.
    ctx.report.expect(
        weekly["kind"] == "weekly" and weekly["payload"]["mood"] in _VALID_MOODS,
        "the Sunday run produced a real weekly-kind payload",
        expected=f"kind=weekly, mood in {_VALID_MOODS}",
        found=(weekly["kind"], weekly["payload"]["mood"]),
    )
    weekly_family = weekly["payload"].get("template_family")
    if weekly_family:
        template_families.append(weekly_family)
    # Observation, not a hard gate: this harness has no way to advance the
    # SERVER's own notion of "today" (advance_day only backdates existing
    # Mongo docs), so all 5 "days" in one run share one real wall-clock date.
    # Every daily trigger_briefing call still draws a genuinely fresh
    # choose_edition_family() call, so a repeat here is a real signal worth
    # a human/product look — but asserting it as a hard failure would claim
    # more confidence in the "5 distinct days" framing than this technique
    # actually provides. See the harness's final report for what was and
    # wasn't observed.
    ctx.report.observe(
        len(template_families) == len(set(template_families)),
        "no edition template family repeated across the week's briefings + weekly digest "
        f"(shuffled-cycle rotation law) — draws: {template_families}",
    )


async def run(ctx: HarnessContext) -> None:
    await _day_zero(ctx)

    template_families: list[str] = []
    ignored_proposal_id: str | None = None
    seen_briefing_ids: set[str] = set()

    for weekday in range(1, 6):
        await steps.trigger_briefing(ctx, kind="daily")
        briefing = await steps.get_latest_briefing(ctx, kind="daily")
        _note_rotation_draw(ctx, briefing, weekday, seen_briefing_ids, template_families)

        proposal_id = await _proposal_for_day(ctx, weekday, ignored_proposal_id)
        if proposal_id is not None:
            await _approve_and_execute(ctx, proposal_id, weekday)
        else:
            ctx.log(
                actor="harness",
                surface="founder-week",
                content=f"day {weekday}: no proposal in the brief to approve",
            )

        if weekday == 2:
            await _day2_blocker(ctx)
            if ignored_proposal_id is None:
                ignored_proposal_id = await _seed_ignored_proposal(ctx)

        await steps.advance_day(ctx, days=1)

    if ignored_proposal_id is not None:
        await _expire_ignored_proposal(ctx, ignored_proposal_id)

    await _sunday_digest(ctx, template_families)
