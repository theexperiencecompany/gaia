"""The shapes thrown at the playbook surface, as data.

Each scenario is one workflow whose step text is a script for the scripted
model (``tools/llm-stub``): ``[[tool:<name> <json>]]`` calls, then ``[[say:]]``.
Every fire of that workflow re-sends the same script, so a scenario reads as a
sequence of fires with an expectation on what each one did — authored, then
replayed, then starved of data and healed, and so on. What is asserted is the
``Observation`` of the fire: the execution record, the playbook's lifecycle
fields, the workflow's decline tally and pause state, and the worker's own
events. Never prose, never a tool result the model wrote.

Under the stub the executor is re-prompted to end with a decision and re-runs
the script, so an agent run writes or declines twice: a written playbook is
revision 2 after its first authoring, and a second decline in the same run is
uncounted. Expectations below are written for that.
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


def write(steps: list[dict[str, Any]], description: str = "drive") -> str:
    return tool(
        "write_playbook",
        {"description": description, "steps": steps, "result_brief": "Say what ran."},
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
LS_STEP = {"id": "ls", "tool": "list_todos", "args": {"completed": False}}


def _todo(title: str) -> str:
    return tool("create_todo", {"title": title})


def _add_step(title: str, step_id: str = "add") -> dict[str, Any]:
    return {"id": step_id, "tool": "create_todo", "args": {"title": title}}


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


def complete_all_and_remember_playbook(ctx: Context) -> None:
    complete_all(ctx)
    remember_playbook_id(ctx)


def mark_start(ctx: Context) -> None:
    """The moment before the fire, in the database's own clock, so a count of
    what the fire created is not skewed by clock drift between here and Mongo."""
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
        return (
            observation.playbook is None
            and observation.warned("write_playbook: rejected")
            and observation.warned(needle)
        )

    return check


def declines(count: int, *, active: bool = True) -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        return (
            observation.workflow.playbook_declines == count
            and observation.workflow.activated is active
        )

    return check


def paused_on(integration: str) -> Expectation:
    def check(observation: Observation, _ctx: Context) -> bool:
        workflow = observation.workflow
        return (
            not workflow.activated
            and workflow.blocked_on_integrations == [integration]
            and workflow.playbook_declines == 0
        )

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
    """A rejected write on a workflow that still holds a playbook."""
    return lambda observation, _ctx: observation.warned(needle)


#: Bodies the write must refuse, each on a run that made one honest call, and
#: the word the refusal has to carry.
REFUSALS: list[tuple[str, str, list[dict[str, Any]], str]] = [
    (
        "X2",
        "unknown tool",
        [{"id": "a", "tool": "no_such_tool", "args": {}}],
        "no_such_tool",
    ),
    ("X3", "blank argument", [_add_step("")], "title"),
    (
        "X4",
        "$item outside a for_each",
        [{"id": "a", "tool": "create_todo", "args": {"title": "$item.id"}}],
        "$item",
    ),
    (
        "X5",
        "for_each over a non-list",
        [
            LS_STEP,
            {
                "id": "m",
                "tool": "update_todo",
                "for_each": "$steps.ls.count",
                "max_items": 5,
                "args": {"todo_id": "$item.id"},
            },
        ],
        "needs a list",
    ),
    (
        "X7",
        "$steps into a field the result lacks",
        [LS_STEP, {"id": "a", "tool": "create_todo", "args": {"title": "$steps.ls.nope"}}],
        "nope",
    ),
    (
        "X8",
        "a call the run never made",
        [_add_step("drive dup"), _add_step("drive never", "b")],
        "did not make",
    ),
]


# --- the catalogue -------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    Scenario(
        key="S1",
        title="write then replay, then an edit discards",
        script=script(_todo("drive one"), write([_add_step("drive one")])),
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
        key="SA",
        title="$steps.<handoff> is not an address",
        script=script(
            _todo("drive a"),
            write(
                [
                    {
                        "id": "h",
                        "handoff": "gmail",
                        "steps": [
                            {
                                "id": "fetch",
                                "tool": "GMAIL_FETCH_EMAILS",
                                "args": {"max_results": 3},
                            }
                        ],
                    },
                    {
                        "id": "add",
                        "tool": "create_todo",
                        "args": {"title": "$steps.h.fetch.subject"},
                    },
                ]
            ),
        ),
        fires=[Fire("refused at the write", refused("addresses the handoff"), "no playbook")],
    ),
    Scenario(
        key="SD",
        title="one strike per run",
        script=script(
            decline("order_branches", branch_on="whether inbox has mail"),
            decline("order_branches", branch_on="whether inbox has mail"),
            decline("order_branches", branch_on="whether inbox has mail"),
        ),
        fires=[
            Fire("three declines in one run count once", declines(1), "declines 1"),
            Fire("a second run counts a second strike", declines(2), "declines 2"),
        ],
    ),
    Scenario(
        key="S5",
        title="a blocked integration pauses without a strike",
        script=script(decline("blocked_missing_integration", integrations=["github"])),
        fires=[
            Fire("paused on github", paused_on("github"), "paused, blocked_on [github], no strike")
        ],
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
                    LS_STEP,
                    {
                        "id": "mark",
                        "tool": "update_todo",
                        "for_each": "$steps.ls.todos",
                        "max_items": 1,
                        "args": {"todo_id": "$item.id", "completed": False},
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
            Fire(
                "empty list after a full replay is suspect; the finishing agent rewrites",
                both(reason("replay_suspect"), lifecycle(status="not_run", streak=1)),
                "streak 1 survives the rewrite",
                before=complete_all,
            ),
            Fire(
                "empty again: baseline reaches past the rewrite, streak 2, discarded",
                both(discarded("suspect_streak_exhausted"), playbook_replaced),
                "discard suspect_streak_exhausted",
                before=complete_all_and_remember_playbook,
            ),
        ],
    ),
    Scenario(
        key="S6",
        title="heal attempts run out",
        before=seed_todos("drive heal seed"),
        script=script(LIST_PENDING, write([LS_STEP])),
        fires=[
            Fire("authored with items", authored, "stored"),
            Fire("replays full", replayed_ok, "replay success"),
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
            write([_add_step("drive x")]),
            tool("disable_playbook", {"reason": "drive"}),
        ),
        fires=[
            Fire(
                "nothing stored",
                lambda observation, _ctx: observation.playbook is None,
                "no playbook",
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
        fires=[Fire("not counted", declines(0), "declines 0")],
    ),
    Scenario(
        key="X10",
        title="blocked without integrations is not a decision",
        script=script(decline("blocked_missing_integration")),
        fires=[Fire("not counted", declines(0), "declines 0")],
    ),
    Scenario(
        key="X11",
        title="blocked_auth_expired pauses without a strike",
        script=script(decline("blocked_auth_expired", integrations=["gmail"])),
        fires=[Fire("paused on gmail", paused_on("gmail"), "paused, blocked_on [gmail]")],
    ),
    Scenario(
        key="X13",
        title="blocked_no_budget is free",
        script=script(decline("blocked_no_budget")),
        fires=[Fire("not counted, still active", declines(0), "declines 0")],
    ),
    Scenario(
        key="X14",
        title="the decline lockout, and an edit resets it",
        script=script(decline("unstable_discovery")),
        fires=[
            Fire("strike 1", declines(1), "declines 1"),
            Fire("strike 2", declines(2), "declines 2"),
            Fire("strike 3", declines(3), "declines 3"),
            Fire("past the limit a decline is not asked", declines(3), "declines stay 3"),
            Fire(
                "an edited workflow starts a fresh tally",
                declines(1),
                "declines 1",
                before=edit_prompt,
            ),
        ],
    ),
    Scenario(
        key="X16",
        title="a write after a decline clears the tally",
        script=script(
            decline("unstable_discovery"), _todo("drive x16"), write([_add_step("drive x16")])
        ),
        fires=[
            Fire("stored, declines 0", both(authored, declines(0)), "playbook stored, declines 0")
        ],
    ),
    Scenario(
        key="X17",
        title="placeholders rendered at replay",
        script=script(
            _todo("Run at 2026-01-01 for someone"),
            write([_add_step("Run at $today for $user.name")]),
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
            write(
                [{"id": "a", "tool": "create_todo", "args": {"title": {"$ask": "a fresh title"}}}]
            ),
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
        key="X20",
        title="a handoff playbook through the todos subagent",
        script=script(
            tool("handoff", {"subagent_id": "todos", "task": script(_todo("via todos"))}),
            write([{"id": "h", "handoff": "todos", "steps": [_add_step("via todos")]}]),
        ),
        fires=[
            Fire(
                "authored with a handoff step",
                lambda observation, _ctx: observation.playbook is not None
                and observation.playbook.has_handoff,
                "handoff playbook",
            ),
            Fire("replays inside the subagent", replayed_ok, "replay success"),
        ],
    ),
    Scenario(
        key="X22",
        title="a decline inside a heal run deletes the playbook",
        before=seed_todos("drive x22 seed"),
        script=script(LIST_PENDING, write([LS_STEP]), decline("unstable_discovery")),
        fires=[
            Fire("authored (the decline after the write leaves it)", authored, "stored"),
            Fire("replays full", replayed_ok, "replay success"),
            Fire(
                "suspect replay; the finishing agent's decline deletes the playbook",
                lambda observation, _ctx: observation.playbook is None
                and "replay_suspect" in observation.reasons,
                "no playbook",
                before=complete_all,
            ),
        ],
    ),
]
