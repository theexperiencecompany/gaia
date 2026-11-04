"""The shapes thrown at the playbook surface, as data.

Each scenario is one workflow whose step text is a script for the scripted
model (tools/llm-stub): [[tool:<name> <json>]] calls, then [[say:]].
Every fire of that workflow re-sends the same script, so a scenario reads as a
sequence of fires with an expectation on what each one did — authored, then
replayed, then starved of data and healed, and so on. What is asserted is the
Observation of the fire: the execution record, the playbook's lifecycle
fields, the workflow's decline tally and pause state, and the worker's own
events. Never prose, never a tool result the model wrote.

Under the stub the executor is re-prompted to end with a decision and re-runs
the script, so an agent run writes or declines twice: a written playbook is
revision 2 after its first authoring, and a second decline in the same run is
uncounted. Expectations below are written for that.

A write picks calls by their number in the run record, which counts every
finished call of the run from 1 in the order it finished: for a script, the
position of the call in it, the playbook tools included. The re-run appends
after them, so the numbers a script's write names hold on both passes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import json
from typing import Any

from .client import GaiaClient
from .observe import Observation, Store


@dataclass(frozen=True)
class Context:
    """What an expectation or a setup step may reach for."""

    client: GaiaClient
    store: Store
    user_id: str
    workflow_id: str
    marks: dict[str, Any] = field(default_factory=dict)


Expectation = Callable[[Observation, Context], bool]
Setup = Callable[[Context], None]


@dataclass(frozen=True)
class Fire:
    name: str
    expect: Expectation
    why: str
    before: Setup | None = None


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    script: str
    fires: Sequence[Fire]
    category: str = "todos"
    before: Setup | None = None


def tool(name: str, args: dict[str, Any]) -> str:
    return f"[[tool:{name} {json.dumps(args)}]]"


def script(*parts: str) -> str:
    return " ".join((*parts, "[[say:done]]"))


def write(picks: list[dict[str, Any]], description: str = "drive") -> str:
    return tool(
        "write_playbook",
        {"description": description, "steps": picks, "result_brief": "Say what ran."},
    )


def decline(
    kind: str, *, integrations: list[str] | None = None, branch_on: str | None = None
) -> str:
    args: dict[str, Any] = {"kind": kind, "reason": "drive"}
    if integrations is not None:
        args["integrations"] = integrations
    if branch_on is not None:
        args["branch_on"] = branch_on
    return tool("decline_playbook", args)


LIST_PENDING = tool("list_todos", {"completed": False})
#: The first call of a script that opens with LIST_PENDING, named for later steps.
LS_PICK = {"call": 1, "id": "ls"}


def _todo(title: str) -> str:
    return tool("create_todo", {"title": title})


#: Expectation wording and step fragments that recur across scenarios.
ITEM_ID = "$item.id"
WHY_NO_PLAYBOOK = "no playbook"
WHY_REPLAY_SUCCESS = "replay success"
WHY_STILL_ACTIVE = "still active"
BRANCH_ON_INBOX = "whether inbox has mail"


# --- setup steps ---------------------------------------------------------------


def seed_todos(*titles: str) -> Setup:
    def run(ctx: Context) -> None:
        for title in titles:
            ctx.client.create_todo(title)

    return run


def complete_all(ctx: Context) -> None:
    ctx.client.complete_all_pending()


def remember_playbook_id(ctx: Context) -> None:
    playbook = ctx.store.playbook(ctx.workflow_id)
    ctx.marks["playbook_id"] = playbook.playbook_id if playbook else None


def edit_prompt(ctx: Context) -> None:
    ctx.store.edit_workflow_prompt(ctx.workflow_id, "edited by the drive")


def mark_start(ctx: Context) -> None:
    """Mark the moment before the fire, in the database's own clock, so a count of what it created is not skewed by clock drift."""
    ctx.marks["started"] = ctx.store.db.command("serverStatus")["localTime"]


# --- expectations --------------------------------------------------------------


def authored(observation: Observation, _ctx: Context) -> bool:
    return observation.playbook is not None and observation.execution.status == "success"


def replayed_ok(observation: Observation, _ctx: Context) -> bool:
    playbook = observation.playbook
    return (
        "replay" in observation.modes
        and playbook is not None
        and playbook.last_run_status == "success"
    )


def refused(needle: str) -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        return observation.playbook is None and any(
            needle in refusal for refusal in observation.refusals
        )

    return check


def declined_ok(observation: Observation, _ctx: Context) -> bool:
    # The scripted model voices one decision on every agent turn it is replayed to.
    return (
        bool(observation.decisions)
        and all(d == "decline_playbook:ok" for d in observation.decisions)
        and observation.workflow.activated
    )


def still_active() -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        return observation.workflow.activated

    return check


def paused_on(integration: str) -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        workflow = observation.workflow
        return not workflow.activated and workflow.blocked_on_integrations == [integration]

    return check


def lifecycle(
    *,
    status: str,
    streak: int | None = None,
    attempts: int | None = None,
    revision: int | None = None,
) -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        playbook = observation.playbook
        if playbook is None or playbook.last_run_status != status:
            return False
        return (
            (streak is None or playbook.suspect_streak == streak)
            and (attempts is None or playbook.heal_attempts == attempts)
            and (revision is None or playbook.revision == revision)
        )

    return check


def both(*checks: Expectation) -> Expectation:
    def check(observation: Observation, ctx: Context) -> bool:
        return all(one(observation, ctx) for one in checks)

    return check


def reason(name: str) -> Expectation:
    return lambda observation, _ctx: name in observation.reasons


def discarded(name: str) -> Expectation:
    return lambda observation, _ctx: name in observation.discards


def playbook_replaced(observation: Observation, ctx: Context) -> bool:
    return observation.playbook is None or observation.playbook.playbook_id != ctx.marks.get(
        "playbook_id"
    )


def for_each_ran(*, at_least: int, ran: int) -> Expectation:
    return lambda observation, _ctx: any(
        count.items >= at_least and count.ran == ran for count in observation.for_each
    )


def executor_failed(observation: Observation, ctx: Context) -> bool:
    return (
        observation.execution.status == "failed"
        and bool(observation.execution.error_message)
        and ctx.store.count_notifications(ctx.user_id, ctx.marks["started"], "X1 an executor") == 1
    )


def refused_kept(needle: str) -> Expectation:
    """Expect a rejected write on a workflow that still holds a playbook."""
    return lambda observation, _ctx: any(needle in refusal for refusal in observation.refusals)


#: Picks the write must refuse, each over a run that listed todos (call 1) and
#: created one (call 2), and the words the refusal has to carry.
REFUSALS: list[tuple[str, str, list[dict[str, Any]], str]] = [
    ("X2", "a call the record does not have", [{"call": 9}], "is not in this run's record"),
    (
        "X3",
        "a marked value that never changes",
        [{"call": 2, "vary": {"title": ""}}],
        "holds no placeholder",
    ),
    ("X4", "$item outside a for_each", [{"call": 2, "vary": {"title": "$item.id"}}], "$item"),
    (
        "X5",
        "for_each over a non-list",
        [LS_PICK, {"call": 2, "for_each": "$steps.ls.count", "vary": {"title": "$item.id"}}],
        "needs a list",
    ),
    (
        "X7",
        "$steps into a field the result lacks",
        [LS_PICK, {"call": 2, "vary": {"title": "$steps.ls.nope"}}],
        "nope",
    ),
    ("X8", "one call picked twice", [{"call": 2}, {"call": 2, "id": "again"}], "picked twice"),
    (
        "X21",
        "an arg the call was not sent",
        [{"call": 2, "vary": {"due": "$today"}}],
        "its arg paths are",
    ),
]


# --- the catalogue -------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    Scenario(
        key="S1",
        title="write then replay, then an edit discards",
        script=script(_todo("drive one"), write([{"call": 1}])),
        fires=[
            Fire("agent run writes the playbook", authored, "playbook stored, exec success"),
            Fire("second run replays it", replayed_ok, "mode replay, pb success"),
            Fire(
                "edited workflow discards the playbook",
                reason("stale_workflow_hash"),
                "a discard event with reason stale_workflow_hash",
                before=edit_prompt,
            ),
        ],
    ),
    Scenario(
        key="S5",
        title="a blocked integration pauses the workflow",
        script=script(decline("blocked_missing_integration", integrations=["github"])),
        fires=[Fire("paused on github", paused_on("github"), "paused, blocked_on [github]")],
    ),
    Scenario(
        key="S9",
        title="for_each caps, then an empty source is suspect, then the streak runs out",
        before=seed_todos("drive fe A", "drive fe B", "drive fe C"),
        script=script(
            LIST_PENDING,
            tool("update_todo", {"todo_id": "${FIRST_PENDING}", "completed": False}),
            write(
                [
                    LS_PICK,
                    {
                        "call": 2,
                        "id": "mark",
                        "for_each": "$steps.ls.todos",
                        "max_items": 1,
                        "vary": {"todo_id": ITEM_ID},
                    },
                ]
            ),
        ),
        fires=[
            Fire(
                "for_each playbook authored",
                lambda observation, _ctx: observation.playbook is not None
                and observation.playbook.has_for_each,
                "playbook with a for_each step",
            ),
            Fire("replay caps at max_items", for_each_ran(at_least=2, ran=1), "items >= 2, ran 1"),
            # The finishing agent's rewrite is not driven here: in that run the replay's
            # calls are numbered first, and a scripted model cannot read the record to
            # pick around them as a real one does.
            Fire(
                "empty list after a full replay is suspect",
                both(reason("replay_suspect"), lifecycle(status="suspect", streak=1)),
                "streak 1",
                before=complete_all,
            ),
            Fire(
                "the next fire heals it: a rewrite that keeps the suspect streak",
                both(reason("heal"), lifecycle(status="not_run", streak=1, attempts=2)),
                "heal, rewritten, streak 1 survives",
            ),
        ],
    ),
    Scenario(
        key="S6",
        title="heal attempts run out",
        before=seed_todos("drive heal seed"),
        script=script(LIST_PENDING, write([LS_PICK])),
        fires=[
            Fire("authored with items", authored, "stored"),
            Fire("replays full", replayed_ok, WHY_REPLAY_SUCCESS),
            Fire(
                "empty replay is suspect; the finishing agent is attempt 1, its empty rewrite refused",
                both(
                    lifecycle(status="suspect", streak=1, attempts=1),
                    refused_kept("returned no items in this run"),
                ),
                "suspect 1, attempts 1",
                before=complete_all,
            ),
            Fire(
                "heal run is attempt 2, refused again",
                both(reason("heal"), lifecycle(status="suspect", attempts=2)),
                "attempts 2",
            ),
            Fire(
                "attempts exhausted: discarded, the agent runs",
                lambda observation, _ctx: observation.playbook is None
                and "heal_attempts_exhausted" in observation.discards,
                "discard heal_attempts_exhausted",
            ),
        ],
    ),
    Scenario(
        key="SX",
        title="disable inside the run that wrote",
        script=script(
            _todo("drive x"),
            write([{"call": 1}]),
            tool("disable_playbook", {"reason": "drive"}),
        ),
        fires=[
            Fire(
                "nothing stored",
                lambda observation, _ctx: observation.playbook is None,
                WHY_NO_PLAYBOOK,
            )
        ],
    ),
    Scenario(
        key="X1",
        title="an executor that dies is a failed fire, announced once",
        script=script("[[tool:create_todo {bad json}]]"),
        before=mark_start,
        fires=[
            Fire(
                "recorded failed, one notification",
                executor_failed,
                "status failed, error carried, told once",
            )
        ],
    ),
    *(
        Scenario(
            key=key,
            title=title,
            script=script(LIST_PENDING, _todo("drive dup"), write(steps)),
            fires=[Fire("refused at the write", refused(needle), f"rejection mentions {needle!r}")],
        )
        for key, title, steps, needle in REFUSALS
    ),
    Scenario(
        key="X9",
        title="order_branches without branch_on is not a decision",
        script=script(decline("order_branches")),
        fires=[Fire("still active", still_active(), WHY_STILL_ACTIVE)],
    ),
    Scenario(
        key="X10",
        title="blocked without integrations is not a decision",
        script=script(decline("blocked_missing_integration")),
        fires=[Fire("still active", still_active(), WHY_STILL_ACTIVE)],
    ),
    Scenario(
        key="X11",
        title="blocked_auth_expired pauses the workflow",
        script=script(decline("blocked_auth_expired", integrations=["gmail"])),
        fires=[Fire("paused on gmail", paused_on("gmail"), "paused, blocked_on [gmail]")],
    ),
    Scenario(
        key="X13",
        title="blocked_no_budget is free",
        script=script(decline("blocked_no_budget")),
        fires=[Fire("still active", still_active(), WHY_STILL_ACTIVE)],
    ),
    Scenario(
        key="X14",
        title="a workflow is asked on every run, however many times it declined",
        script=script(decline("unstable_discovery")),
        fires=[
            Fire(f"decline {n}", declined_ok, "decline accepted, workflow active")
            for n in range(1, 5)
        ],
    ),
    Scenario(
        key="X16",
        title="a write after a decline in the same run stores the playbook",
        script=script(decline("unstable_discovery"), _todo("drive x16"), write([{"call": 2}])),
        fires=[Fire("stored", authored, "playbook stored")],
    ),
    Scenario(
        key="X17",
        title="placeholders rendered at replay",
        script=script(
            _todo("Run at 2026-01-01 for someone"),
            write([{"call": 1, "vary": {"title": "Run at $today for $user.name"}}]),
        ),
        fires=[
            Fire("accepted at the write", authored, "stored"),
            Fire(
                "replay renders $today and $user.name",
                lambda observation, ctx: replayed_ok(observation, ctx)
                and ctx.store.count_todos(
                    ctx.user_id, r"^Run at 20[0-9]{2}-[0-9]{2}-[0-9]{2} for (?!\$)"
                )
                >= 1,
                "a todo titled with the rendered date and name",
            ),
        ],
    ),
    Scenario(
        key="X18",
        title="an $ask no model fills: three failed replays, then the body is given up",
        script=script(
            _todo("drive ask"),
            write([{"call": 1, "id": "a", "vary": {"title": {"$ask": "a fresh title"}}}]),
        ),
        fires=[
            Fire("accepted at the write", authored, "stored"),
            Fire(
                "stopped; the finishing agent rewrites, spending attempt 1",
                both(reason("replay_stopped"), lifecycle(status="not_run", attempts=1)),
                "attempts 1",
            ),
            Fire(
                "the same again spends attempt 2",
                both(reason("replay_stopped"), lifecycle(status="not_run", attempts=2)),
                "attempts 2",
            ),
            Fire(
                "the third failed replay discards the body",
                both(
                    reason("replay_stopped"),
                    discarded("heal_attempts_exhausted"),
                    playbook_replaced,
                ),
                "discard heal_attempts_exhausted",
                before=remember_playbook_id,
            ),
        ],
    ),
    Scenario(
        key="X22",
        title="a decline inside a heal run deletes the playbook",
        before=seed_todos("drive x22 seed"),
        script=script(LIST_PENDING, write([LS_PICK]), decline("unstable_discovery")),
        fires=[
            Fire("authored (the decline after the write leaves it)", authored, "stored"),
            Fire("replays full", replayed_ok, WHY_REPLAY_SUCCESS),
            Fire(
                "suspect replay; the finishing agent's decline deletes the playbook",
                lambda observation, _ctx: observation.playbook is None
                and "replay_suspect" in observation.reasons,
                WHY_NO_PLAYBOOK,
                before=complete_all,
            ),
        ],
    ),
]
