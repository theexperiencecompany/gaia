"""Survey the playbook surface on a REAL model across many workflow shapes.

Unlike the scripted drive, nothing here is asserted: a real model's choices
vary, so each fire is recorded (what it decided, what it wrote, whether the
replay ran, what it cost) and the table is read by a person. Run against a
stack on the real model (no sim), as a user would: the workflow is created
through the API with model-generated steps and fired with the Run-now
endpoint, with the data changed between fires.

    cd apps/api
    uv run --group backend python -m scripts.playbook_drive.survey --worker-log <log> [--only D1 D7] [--budget-usd 1.5]
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sys
import time
from typing import Any

from .client import DEFAULT_API, DEFAULT_USER, GaiaClient
from .observe import Observation, Store, WorkerLog, fire_and_observe

Setup = Callable[[GaiaClient], None]


@dataclass(frozen=True)
class Shape:
    key: str
    title: str
    prompt: str
    fires: int = 3
    #: Run before each fire, indexed by fire number (0-based); missing = nothing.
    before: dict[int, Setup] = field(default_factory=dict)


def seed(*titles: str) -> Setup:
    def run(client: GaiaClient) -> None:
        for title in titles:
            client.create_todo(title)

    return run


def complete_all(client: GaiaClient) -> None:
    client.complete_all_pending()


SHAPES: list[Shape] = [
    Shape(
        "D1",
        "fetch-only digest",
        "Every morning, list my pending todos and send me a three-line digest of what is on my plate.",
        before={0: seed("survey: renew passport", "survey: call the bank")},
    ),
    Shape(
        "D2",
        "act on every item",
        "Every morning, list my pending todos and add the label 'today' to every one of them. Tell me how many you labelled.",
        before={
            0: seed("survey: water plants", "survey: pay rent"),
            2: seed("survey: book flights"),
        },
    ),
    Shape(
        "D3",
        "act on some items by judgement",
        "Every morning, list my pending todos and, for each one whose title mentions money or payment, create a new todo titled 'Budget check: <title>'. Tell me how many you created.",
        before={0: seed("survey: pay electricity bill", "survey: gym"), 2: complete_all},
    ),
    Shape(
        "D4",
        "create with a date placeholder",
        "Every morning, create a todo titled 'Plan for <today's date>' with the description 'Write three priorities'. Confirm the title you used.",
    ),
    Shape(
        "D5",
        "web search then a note",
        "Every morning, search the web for one recent news headline about Python the programming language and create a todo titled 'Read: <headline>'. Tell me the headline.",
    ),
    Shape(
        "D6",
        "reminder relative to now",
        "Every morning, set a reminder for tomorrow at 9am that says 'Review yesterday's plan'. Confirm when it is set for.",
    ),
    Shape(
        "D7",
        "genuinely conditional order",
        "Every morning, count my pending todos. If there are more than three, create a todo titled 'Triage the backlog'; otherwise do nothing else. Tell me the count and what you did.",
        before={0: seed("survey: a", "survey: b", "survey: c", "survey: d"), 1: complete_all},
    ),
    Shape(
        "D8",
        "needs an integration that is not connected",
        "Every morning, read my Gmail inbox and tell me how many unread emails I have.",
        fires=2,
    ),
    Shape(
        "D9",
        "quiet day",
        "Every morning, list my pending todos and, for each one that is overdue, create a todo titled 'Chase: <title>'. Tell me how many you created.",
        before={0: complete_all},
    ),
    Shape(
        "D10",
        "two-step chain into a previous result",
        "Every morning, list my pending todos, then create one todo titled 'Focus: <the title of the first pending todo>'. Tell me which one you picked.",
        before={0: seed("survey: finish the report", "survey: dentist")},
    ),
]


@dataclass(frozen=True)
class Row:
    shape: str
    fire: int
    status: str
    mode: str
    decision: str
    playbook: str
    lifecycle: str
    declines: int
    paused: str
    cost_usd: float
    seconds: float


def _decision(observation: Observation, store: Store) -> str:
    execution = store.db["workflow_executions"].find_one(
        {"execution_id": observation.execution.execution_id}
    )
    names = [
        str(call.get("tool_name"))
        for call in (execution or {}).get("trace") or []
        if "playbook" in str(call.get("tool_name"))
    ]
    kinds = [reason for reason in observation.reasons if reason not in ("no_playbook", "heal")]
    return ",".join(dict.fromkeys(names)) + (f" [{','.join(kinds)}]" if kinds else "")


def _playbook(observation: Observation) -> str:
    playbook = observation.playbook
    if playbook is None:
        return "-"
    shape = "+".join(playbook.tools)
    if playbook.has_handoff:
        shape = f"handoff({shape})"
    if playbook.has_for_each:
        shape += " for_each"
    return shape


def _cost(store: Store, user_id: str, since: datetime) -> float:
    rows = store.db["llm_calls"].find({"user_id": user_id, "created_at": {"$gte": since}})
    return float(sum(row.get("cost_usd") or 0.0 for row in rows))


def run_shape(
    shape: Shape, client: GaiaClient, store: Store, log: WorkerLog, user_id: str
) -> list[Row]:
    print(f"{time.strftime('%H:%M:%S')} {shape.key} {shape.title}", flush=True)
    rows: list[Row] = []
    workflow = None
    for index in range(shape.fires):
        if index in shape.before:
            shape.before[index](client)
        if workflow is None:
            store.reset_rate_limits(user_id)
            workflow = client.create_workflow(f"{shape.key} {shape.title}", shape.prompt)
        started = time.monotonic()
        try:
            observation = fire_and_observe(client, store, log, workflow.id, user_id=user_id)
        except (TimeoutError, RuntimeError) as error:
            print(f"  fire {index + 1}: {error}", flush=True)
            break
        lifecycle = "-"
        if observation.playbook is not None:
            playbook = observation.playbook
            lifecycle = (
                f"{playbook.last_run_status} r{playbook.revision} "
                f"s{playbook.suspect_streak} h{playbook.heal_attempts}"
            )
        row = Row(
            shape=shape.key,
            fire=index + 1,
            status=observation.execution.status,
            mode="/".join(dict.fromkeys(observation.modes)) or "-",
            decision=_decision(observation, store) or "-",
            playbook=_playbook(observation),
            lifecycle=lifecycle,
            declines=observation.workflow.playbook_declines,
            paused=""
            if observation.workflow.activated
            else f"paused:{','.join(observation.workflow.blocked_on_integrations) or observation.workflow.deactivated_reason}",
            cost_usd=_cost(store, user_id, observation.execution.started_at),
            seconds=time.monotonic() - started,
        )
        rows.append(row)
        print(
            f"  fire {row.fire}: {row.status} mode={row.mode} decision={row.decision} "
            f"playbook={row.playbook} {row.lifecycle} declines={row.declines} {row.paused} "
            f"${row.cost_usd:.4f} {row.seconds:.0f}s",
            flush=True,
        )
        if not observation.workflow.activated:
            break
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--worker-log", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[], metavar="KEY")
    parser.add_argument("--budget-usd", type=float, default=1.5)
    args = parser.parse_args(argv)

    client = GaiaClient(args.api, args.user)
    user = client.mint_user()
    store = Store()
    log = WorkerLog(args.worker_log)
    chosen = [shape for shape in SHAPES if not args.only or shape.key in args.only]

    rows: list[Row] = []
    spent = 0.0
    for shape in chosen:
        if spent >= args.budget_usd:
            print(
                f"budget of ${args.budget_usd:.2f} reached before {shape.key}; stopping", flush=True
            )
            break
        shape_rows = run_shape(shape, client, store, log, user.id)
        rows.extend(shape_rows)
        spent += sum(row.cost_usd for row in shape_rows)

    print(f"\n{len(rows)} fires, ${spent:.3f} spent")
    print(
        "shape | fire | status | mode | decision | playbook | lifecycle | declines | paused | cost | s"
    )
    for row in rows:
        values: Sequence[Any] = (
            row.shape,
            row.fire,
            row.status,
            row.mode,
            row.decision,
            row.playbook,
            row.lifecycle,
            row.declines,
            row.paused or "-",
            f"${row.cost_usd:.4f}",
            f"{row.seconds:.0f}",
        )
        print(" | ".join(str(value) for value in values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
