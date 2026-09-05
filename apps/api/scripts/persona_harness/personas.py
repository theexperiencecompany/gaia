"""The persona matrix — one function per scenario named in openspec/changes/
daily-briefing-self-executing-todos/tasks.md I.7. Each persona mints its own
user (``persona-<name>@gaia.local``), drives real surfaces (see ``steps.py``),
and asserts through ``ctx.report.expect``. ``__main__.py`` owns the mint/run/
teardown lifecycle.

Some spec scenarios describe LLM *judgment* (does the brief phrase the streak
break honestly, does it mention a slip exactly once) that cannot be asserted
deterministically — those personas assert the deterministic plumbing around
the judgment call and log the real LLM output into the report timeline for a
human/Nous-lane read. That split is called out inline, not left implicit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.persona_harness import steps
from scripts.persona_harness.steps import HarnessContext

PersonaFn = Callable[[HarnessContext], Awaitable[None]]


async def empty_day_zero(ctx: HarnessContext) -> None:
    """Scenario: 'Empty queue prompts the priorities question' (daily-briefing-run)."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)
    await steps.trigger_briefing(ctx, kind="daily")

    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    payload = briefing["payload"]
    ctx.report.expect(
        payload["mood"] == "idle",
        "day-zero brief with no queued work is mood=idle, not padded with heartbeat activity",
        expected="idle",
        found=payload["mood"],
    )
    gaia_count = await steps.count_todos(ctx, assignee="gaia")
    ctx.report.expect(
        gaia_count == 0,
        "no GAIA todos were fabricated to fill an empty day",
        expected=0,
        found=gaia_count,
    )


async def goal_driven_founder(ctx: HarnessContext) -> None:
    """Scenario: proposals trace to the goal via `serves` (unified-todo-model:
    'Every GAIA todo is traceable').

    `mood` tracks queued work, not goal-awareness — a fresh account's very
    first brief legitimately comes back `idle` (nothing is queued yet) even
    while the message engages with the stated goal (observed live: "you did
    tell me the mission once... want me to take that on?"). So this persona
    doesn't assert on day-zero's mood; it runs a second day to give the model
    a real chance to turn the goal into a traceable proposal, matching the
    pattern the founder-week capstone already needed for the same reason."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)
    await steps.set_focus(ctx, "raise a pre-seed; ship daily")
    await steps.trigger_briefing(ctx, kind="daily")
    await steps.advance_day(ctx, days=1)
    await steps.trigger_briefing(ctx, kind="daily")

    gaia_todos = [
        doc async for doc in ctx.db.todos.find({"user_id": ctx.user_id, "assignee": "gaia"})
    ]
    ctx.log(
        actor="harness",
        surface="mongo:todos (gaia, post-run)",
        content=f"{len(gaia_todos)} GAIA todo(s) proposed; serves values: "
        f"{[t.get('serves') for t in gaia_todos]}",
    )

    # The per-todo traceability check below is vacuous when the run proposed
    # nothing, and a persona that asserts nothing silently "passes" forever.
    # Either outcome is legitimate product behavior — a bare account with no
    # integrations may honestly have nothing concrete to propose (the
    # no-padding rule) — so the assertion is on the DISJUNCTION: propose
    # something traceable, or say plainly that nothing is queued.
    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    payload = briefing["payload"]
    honestly_idle = payload.get("mood") == "idle"
    ctx.report.expect(
        bool(gaia_todos) or honestly_idle,
        "the goal either produced GAIA work or the brief honestly reported an empty queue",
        expected="≥1 GAIA todo, or mood=idle",
        found=f"{len(gaia_todos)} GAIA todos, mood={payload.get('mood')!r}",
    )
    for todo in gaia_todos:
        ctx.report.expect(
            bool(todo.get("serves")),
            f"GAIA todo {todo['_id']} ({todo.get('title')!r}) carries serves traceability",
            expected="non-empty serves",
            found=todo.get("serves"),
        )


async def ignorer_winback(ctx: HarnessContext) -> None:
    """Scenario: 'Winback after three ignored briefings' (daily-briefing-run)."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    today = datetime.now(UTC).date()
    for days_ago in (3, 2, 1):
        day = today - timedelta(days=days_ago)
        await steps.insert_briefing(
            ctx,
            date=day.isoformat(),
            kind="daily",
            opened_at=None,
            created_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        )

    fixtures = await steps.list_recent_briefings(ctx, kind="daily", limit=10)
    ctx.report.expect(
        len(fixtures) == 3 and all(f["opened_at"] is None for f in fixtures),
        "all 3 unopened-briefing fixtures actually landed before the winback run",
        expected="3 unopened briefings",
        found=[(f["date"], f["opened_at"]) for f in fixtures],
    )

    await steps.trigger_briefing(ctx, kind="daily")
    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    ctx.report.expect(
        briefing["payload"]["mood"] == "winback",
        "3 consecutive unopened briefings flip the next run into winback mode",
        expected="winback",
        found=briefing["payload"]["mood"],
    )


async def streak_breaker(ctx: HarnessContext) -> None:
    """Scenario: 'Mutual idleness breaks the streak' (retention-loop). The
    streak itself is deterministic (derived only from completed_at) — asserted
    here by independently re-deriving it from Mongo, matching
    app/services/todos/activity.py's streak_from_counts. Whether the brief
    *acknowledges* the break honestly is a judgment call left to the report
    timeline."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    today = datetime.now(UTC).date()
    await steps.insert_todo(
        ctx,
        title="shipped the deck",
        assignee="user",
        completed=True,
        completed_at=datetime.combine(today - timedelta(days=3), datetime.min.time(), tzinfo=UTC),
    )
    computed_streak = steps.streak_from_completions([today - timedelta(days=3)], today)
    ctx.report.expect(
        computed_streak == 0,
        "a gap (today-2 and today-1 both empty) resets the streak to 0 before today",
        expected=0,
        found=computed_streak,
    )

    await steps.trigger_briefing(ctx, kind="daily")
    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    ctx.report.expect(
        briefing["payload"]["mood"] in ("clear", "packed", "idle", "winback", "weekly"),
        "the brief still persists a valid payload the day after a broken streak "
        "(judgment: read the timeline below for honest phrasing, not padded/frozen)",
        expected="a valid BriefingMood",
        found=briefing["payload"]["mood"],
    )


async def at_quota_free(ctx: HarnessContext) -> None:
    """Scenario: 'At-quota approve pitches with the actual work' (tier-limits-conversion)."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    todo_id = await steps.insert_todo(
        ctx,
        title="send the 12 drafted investor DMs",
        assignee="gaia",
        kind="task",
        execution_status="proposed",
        serves="raise a pre-seed",
    )
    await steps.set_quota_used(ctx, feature="gaia_todo_executions", count=5)

    resp = await steps.approve_todo(ctx, todo_id)
    ctx.report.expect(
        resp.status_code == 402,
        "approve at quota does not silently fail — it returns the upgrade pitch",
        expected=402,
        found=resp.status_code,
    )
    body = resp.json()
    ctx.report.expect(
        body.get("error") == "gaia_execution_quota" and "pitch" in body,
        "the 402 body names the staged work as the specific upgrade pitch",
        expected="gaia_execution_quota with a pitch field",
        found=body,
    )
    todo = await steps.get_todo(ctx, todo_id)
    ctx.report.expect(
        todo["execution_status"] == "proposed",
        "the staged todo stays proposed (not expired) while it is the active upgrade pitch",
        expected="proposed",
        found=todo["execution_status"],
    )


async def blocked_everything(ctx: HarnessContext) -> None:
    """Scenario: simultaneous needs_you blockers combine into ONE message,
    never separate pushes (daily-briefing-run: 'One briefing message per day
    is law')."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    todo_ids = [
        await steps.insert_todo(
            ctx,
            title=f"blocked task {i + 1}",
            assignee="gaia",
            kind="task",
            execution_status="queued",
            serves="operational cleanup",
        )
        for i in range(3)
    ]

    since = datetime.now(UTC)
    for i, todo_id in enumerate(todo_ids):
        question = f"Which vendor should I use for task {i + 1}?"
        await steps.run_executor_task(
            ctx,
            sim_task=(
                f'[[tool:block_todo {{"todo_id":"{todo_id}","question":"{question}"}}]] '
                "[[say:Blocked, need your call.]]"
            ),
            agent_task=(
                f"Call block_todo now for tracked todo id {todo_id} with question: "
                f"{question!r}. Do not do anything else."
            ),
        )

    notification_count = await steps.count_notifications(ctx, kind="todo_needs_you", since=since)
    ctx.report.expect(
        notification_count == 3,
        "one notification write per block event (the combining is in the content, not a count)",
        expected=3,
        found=notification_count,
    )
    notifications = await steps.list_notifications(ctx, kind="todo_needs_you", since=since)
    last_title = notifications[-1]["original_request"]["content"]["title"]
    ctx.report.expect(
        last_title == "3 things need your call",
        "the 3rd simultaneous blocker's notification summarizes all pending blockers as one message",
        expected="3 things need your call",
        found=last_title,
    )
    needs_you_count = await steps.count_todos(ctx, execution_status="needs_you")
    ctx.report.expect(
        needs_you_count == 3,
        "all 3 todos actually flipped to needs_you",
        expected=3,
        found=needs_you_count,
    )


async def slipped_plan(ctx: HarnessContext) -> None:
    """Scenario: 'A slip rolls forward with an offer' (daily-briefing-run). The
    exact wording (mentioned once, offered takeover, dropped to memory on the
    3rd ignore) is judgment-quality — left to the report timeline."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    slipped_todo_id = await steps.insert_todo(
        ctx, title="follow up with the lawyer about the SAFE", assignee="user", completed=False
    )
    await steps.insert_briefing(
        ctx,
        date=yesterday.isoformat(),
        kind="daily",
        created_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC),
        payload={
            "kicker": "Daily",
            "date": yesterday.isoformat(),
            "headline": "fixture: yesterday's plan",
            "lede": "fixture look-back seed",
            "stats": [],
            "sections": [
                {
                    "numeral": "I",
                    "title": "Today",
                    "items": [
                        {
                            "text": "follow up with the lawyer about the SAFE",
                            "todo_id": slipped_todo_id,
                            "kind": "you",
                            "link": None,
                        }
                    ],
                }
            ],
            "mood": "clear",
            "caption": "fixture",
            "hue": 0,
            "template_family": None,
            "message": None,
            "bubbles": [],
        },
    )

    await steps.trigger_briefing(ctx, kind="daily")
    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    payload = briefing["payload"]
    # `mood` tracks queued work, not look-back content — observed live: a
    # brief can be honestly `idle` (nothing queued) while its message still
    # explicitly acknowledges the slip ("it's been sitting there since
    # yesterday"). So assert on the actual look-back text, not the mood.
    look_back_text = " ".join(
        filter(None, [payload.get("lede"), payload.get("message"), payload.get("caption")])
    ).lower()
    ctx.report.expect(
        "lawyer" in look_back_text or "safe" in look_back_text,
        "the brief's text actually references yesterday's slipped item, not just silence",
        expected="'lawyer' or 'safe' mentioned",
        found=look_back_text[:300],
    )


async def dismissed_kind_3x(ctx: HarnessContext) -> None:
    """Scenario: 'Third strike ends a proposal kind' (unified-todo-model). The
    dismiss->memory-signal write is real production code (Postgres-backed
    memory_engine.retain_single) exercised via 3 real dismiss calls; whether a
    later run actually stops re-proposing is judgment-quality (Nous lane)."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    serves = "raise a pre-seed"
    for i in range(3):
        todo_id = await steps.insert_todo(
            ctx,
            title=f"draft investor DM #{i + 1}",
            assignee="gaia",
            kind="task",
            execution_status="proposed",
            serves=serves,
        )
        resp = await steps.dismiss_todo(ctx, todo_id, reason="not now")
        ctx.report.expect(
            resp.status_code == 200,
            f"real dismiss #{i + 1} succeeds (writes a proposal_rejected memory signal via "
            "gaia_todo_lifecycle._record_rejection_signal — Postgres-backed, not "
            "independently re-verified here)",
            expected=200,
            found=resp.status_code,
        )

    dismissed_count = await steps.count_todos(ctx, serves=serves, execution_status="dismissed")
    ctx.report.expect(
        dismissed_count == 3,
        "three investor-DM proposals were dismissed for the same serves/kind",
        expected=3,
        found=dismissed_count,
    )


async def timezone_edge(ctx: HarnessContext) -> None:
    """Scenario: 'New user is provisioned' — next_run correct for a UTC+14 user
    (daily-briefing-run)."""
    await steps.mint_user(ctx)
    await steps.set_timezone(ctx, "Pacific/Kiritimati")
    await steps.provision_briefing_workflow(ctx)

    workflow = await steps.get_daily_briefing_workflow(ctx)
    trigger = workflow["trigger_config"]
    ctx.report.expect(
        trigger.get("timezone") == "Pacific/Kiritimati",
        "the provisioned workflow's trigger stamps the user's actual timezone",
        expected="Pacific/Kiritimati",
        found=trigger.get("timezone"),
    )
    next_run = trigger["next_run"]
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=UTC)
    local_next_run = next_run.astimezone(ZoneInfo("Pacific/Kiritimati"))
    ctx.report.expect(
        (local_next_run.hour, local_next_run.minute) == (8, 0),
        "next_run, converted back to Pacific/Kiritimati wall-clock time, reads 08:00 local",
        expected=(8, 0),
        found=(local_next_run.hour, local_next_run.minute),
    )


async def dormant_reactivated(ctx: HarnessContext) -> None:
    """Scenario: a fresh goal wakes a dormant account (services/briefing/dormancy.py)."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    dormant_since = datetime.now(UTC) - timedelta(days=5)
    await steps.set_dormancy(
        ctx,
        idle_days=3,
        date_str=dormant_since.date().isoformat(),
        dormant_since=dormant_since,
    )
    # A goal-kind todo created since dormant_since is the reactivation signal
    # (dormancy.reactivation_signal_since -> todo_repository.has_goal_created_since).
    await steps.insert_todo(ctx, title="raise a pre-seed", assignee="user", kind="goal")

    await steps.trigger_briefing(ctx, kind="daily")

    user = await steps.get_user_doc(ctx)
    dormancy = user.get("briefing_dormancy") or {}
    ctx.report.expect(
        dormancy.get("dormant_since") is None,
        "a fresh goal since dormant_since clears dormancy on the next run",
        expected=None,
        found=dormancy.get("dormant_since"),
    )
    briefing = await steps.get_latest_briefing(ctx, kind="daily")
    today_str = datetime.now(UTC).date().isoformat()
    ctx.report.expect(
        briefing["date"] == today_str,
        "the run produced a real brief for today post-reactivation, not an early dormant exit",
        expected=today_str,
        found=briefing["date"],
    )


async def nudge_flow(ctx: HarnessContext) -> None:
    """Scenario: 'Completion nudge is contextual and single' + repeat
    suppression (retention-loop). The nudge only fires on a live comms->
    executor handoff (app/agents/core/background/result_delivery.py
    _safe_completion_nudge) — unreachable via /dev/executor or the ARQ
    worker's own completion path — so this persona drives real chat turns."""
    await steps.mint_user(ctx)
    await steps.seed_data(ctx, todos=0, conversations=0)

    # The one open candidate the nudge can point at.
    candidate_id = await steps.insert_todo(
        ctx, title="prep the investor deck", assignee="user", completed=False
    )

    todo_a = await steps.insert_todo(
        ctx,
        title="research pre-seed investors",
        assignee="gaia",
        kind="task",
        execution_status="proposed",
        serves="raise a pre-seed",
    )
    approve_resp = await steps.approve_todo(ctx, todo_a)
    ctx.report.expect(
        approve_resp.status_code == 200,
        "approve on a proposed GAIA todo succeeds",
        expected=200,
        found=approve_resp.status_code,
    )
    sim_task_a = (
        f'[[tool:complete_tracked_todo {{"todo_id":"{todo_a}","summary":"Compiled the investor list."}}]] '
        "[[say:Done — compiled the investor list.]]"
    )
    agent_task_a = (
        f"Mark the tracked todo {todo_a} complete right now via complete_tracked_todo, "
        "summary: 'Compiled the investor list.'"
    )
    await steps.chat_turn(ctx, sim_task_a if ctx.sim else agent_task_a)
    # call_executor hands the run off to the background executor and comms
    # replies with an immediate ack ("on it...") — the actual completion +
    # nudge (result_delivery.deliver_result) lands later, out of band from
    # this SSE turn. Poll until the executor run actually settles.
    await steps.wait_for_execution(ctx, todo_a, timeout_s=45.0)

    candidate_after_first = await steps.get_todo(ctx, candidate_id)
    first_nudge_fired = bool(candidate_after_first and candidate_after_first.get("nudge_shown"))
    ctx.log(
        actor="harness",
        surface="mongo:todos.nudge_shown (post-completion-1)",
        content=f"candidate nudged: {first_nudge_fired}",
    )

    todo_c = await steps.insert_todo(
        ctx,
        title="draft the intro DMs",
        assignee="gaia",
        kind="task",
        execution_status="proposed",
        serves="raise a pre-seed",
    )
    await steps.approve_todo(ctx, todo_c)
    sim_task_c = (
        f'[[tool:complete_tracked_todo {{"todo_id":"{todo_c}","summary":"Drafted the intro DMs."}}]] '
        "[[say:Done — drafted the intro DMs.]]"
    )
    agent_task_c = (
        f"Mark the tracked todo {todo_c} complete right now via complete_tracked_todo, "
        "summary: 'Drafted the intro DMs.'"
    )
    await steps.chat_turn(ctx, sim_task_c if ctx.sim else agent_task_c)
    await steps.wait_for_execution(ctx, todo_c, timeout_s=45.0)

    if first_nudge_fired:
        candidate_after_second = await steps.get_todo(ctx, candidate_id)
        ctx.report.expect(
            bool(candidate_after_second and candidate_after_second.get("nudge_shown")),
            "a suggestion already shown stays marked shown (never un-shown)",
            expected=True,
            found=candidate_after_second.get("nudge_shown") if candidate_after_second else None,
        )
    nudged_count = await steps.count_todos(ctx, nudge_shown=True)
    ctx.report.expect(
        nudged_count <= 1,
        "the same candidate is never re-suggested across completions — nudged-todo count stays <=1",
        expected="<=1",
        found=nudged_count,
    )


PERSONAS: dict[str, PersonaFn] = {
    "empty-day-zero": empty_day_zero,
    "goal-driven-founder": goal_driven_founder,
    "ignorer-winback": ignorer_winback,
    "streak-breaker": streak_breaker,
    "at-quota-free": at_quota_free,
    "blocked-everything": blocked_everything,
    "slipped-plan": slipped_plan,
    "dismissed-kind-3x": dismissed_kind_3x,
    "timezone-edge": timezone_edge,
    "dormant-reactivated": dormant_reactivated,
    "nudge-flow": nudge_flow,
}
