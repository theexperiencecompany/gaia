#!/usr/bin/env python3
# mypy: ignore-errors -- dev eval script; typing not maintained here
"""
Does a new paid user see the value and set things up without friction?

Not a test: it drives a REAL running API and a REAL model. Each journey is a
fresh Pro dev user with a role and Q2 picks who starts from the exact opener
the bots send after linking, then plays a short realistic script: taps a
chip, says yes, asks what a workflow is, asks for a watcher, a schedule, an
integration, a public workflow, changes their mind. Every GAIA turn is scored
by an LLM judge against what THAT turn was for, and each journey gets two
0-5 marks: did the value show, and was setup seamless.

Usage (from apps/api/, with the worktree API already running):

    uv run python scripts/evals/activation_journeys.py --api-url http://localhost:9330
    uv run python scripts/evals/activation_journeys.py --only student,founder
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from pydantic import BaseModel

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_message import compose_first_message
from scripts.evals.core.dev_users import dev_client, provision
from scripts.evals.core.judge import judge
from scripts.evals.core.live_chat import Turn, TurnOptions, send_turn
from scripts.evals.core.paths import RUNS_DIR, under_runs

DEFAULT_API_URL = os.environ.get("GAIA_API_URL", "http://localhost:9330")
RUN_ID = time.strftime("%H%M%S")
USER_TEMPLATE = "aj-{slug}-" + RUN_ID + "@gaia.local"
#: A connect is delegated now, so either the executor handoff or the card the
#: executor puts on the stream counts as the ask being actionable.
CONNECT_TOOLS = ("integration_connection_required", "call_executor")
JUDGE_TIMEOUT_SECONDS = 90.0
#: Was inherited from chat_quality when this script imported its ``_send_turn``;
#: named here now that the shared helper takes it as an argument.
TURN_TIMEOUT_SECONDS = 180.0
DELIVERY_WAIT_SECONDS = 75.0
DELIVERY_POLL_SECONDS = 3.0
TURN_OPTIONS = TurnOptions(
    timeout=TURN_TIMEOUT_SECONDS,
    delivery_wait_seconds=DELIVERY_WAIT_SECONDS,
    delivery_poll_seconds=DELIVERY_POLL_SECONDS,
)


class Step(BaseModel):
    """One user message and what a good reply to it must do."""

    message: str
    intent: str


class Journey(BaseModel):
    slug: str
    role: str
    needs: list[OnboardingNeed]
    steps: list[Step]


JOURNEYS: list[Journey] = [
    Journey(
        slug="student-assignments",
        role="student",
        needs=[OnboardingNeed.STUDENT_ASSIGNMENTS, OnboardingNeed.REMINDERS],
        steps=[
            Step(
                message="yes",
                intent="Take the yes: ask for the assignments and dates in ONE line, or start the tracker; no re-pitch.",
            ),
            Step(
                message="biology essay friday, stats problem set monday, group project on the 20th",
                intent="Create the items (todos/reminders) NOW with real tool calls and confirm in one short line each; no plan for a plan.",
            ),
            Step(
                message="wait what's a workflow anyway",
                intent="Explain workflow vs reminder vs tracked todo in plain words from the capability block, two or three lines, no brochure.",
            ),
            Step(
                message="remind me every sunday 6pm to plan the week",
                intent="A recurring reminder created with a tool, confirmed in one line with the cadence and timezone.",
            ),
        ],
    ),
    Journey(
        slug="founder-inbox",
        role="founder",
        needs=[OnboardingNeed.INBOX, OnboardingNeed.FOUNDER_TEAM_UPDATES],
        steps=[
            Step(
                message="yes do the inbox",
                intent="The Gmail connect is handed to the executor, plus one line on what happens after the tap. No 'want me to send the link'.",
            ),
            Step(
                message="ok connected it",
                intent="Check the real connection status once (tool), report honestly (it is NOT connected in this eval), offer the card again once, no loop.",
            ),
            Step(
                message="is there a notion integration?",
                intent="Answer from a real search or the registry: yes/no and what it unlocks, handing the connect to the executor if yes. No guessing.",
            ),
            Step(
                message="any ready-made workflow for a weekly investor update?",
                intent="Search public workflows or offer to build one as a scheduled workflow; concrete, one question at most.",
            ),
        ],
    ),
    Journey(
        slug="engineer-watchers",
        role="engineering",
        needs=[OnboardingNeed.ENGINEERING_PRS, OnboardingNeed.TOOLS],
        steps=[
            Step(
                message="what can you actually do for me day to day",
                intent="Two or three plain lines aimed at an engineer's week from the capability block; not a list of features, no headings.",
            ),
            Step(
                message="watch the react repo releases for me",
                intent="Map to a trigger/watch workflow: say what will run and when, and what it needs (GitHub connect or a web watcher); one clear next step.",
            ),
            Step(
                message="every monday 9am summarise my week's PRs",
                intent="A scheduled workflow proposed or created with the cadence stated; needs GitHub, so the card or an honest 'once GitHub is connected'.",
            ),
            Step(
                message="actually stop, don't set anything up yet",
                intent="Accept immediately in one line, undo nothing that was not done, no re-offer, no guilt.",
            ),
        ],
    ),
    Journey(
        slug="sales-quiet-prospects",
        role="sales",
        needs=[OnboardingNeed.SALES_LEADS],
        steps=[
            Step(
                message="acme and globex, both went quiet about a week ago",
                intent="Hold the two names as tracked items or a list with a tool call, and offer the nudge draft; one question at most.",
            ),
            Step(
                message="draft the nudge for acme",
                intent="A real short draft in the reply, in a human voice; no 'I'll draft it'.",
            ),
            Step(
                message="ok send it",
                intent="Honest: nothing is connected so it cannot send; the Gmail card in this reply, or copy-to-send guidance. No pretending it went.",
            ),
        ],
    ),
    Journey(
        slug="capability-questions",
        role="product",
        needs=[OnboardingNeed.PRODUCT_FEEDBACK],
        steps=[
            Step(
                message="what's the difference between a workflow and a reminder",
                intent="Correct, plain, two or three lines, matches the capability block.",
            ),
            Step(
                message="do you do things on your own or only when i ask",
                intent="Explain proactive behaviour correctly: tracked todos, scheduled and triggered workflows, built-in workflows after connecting; no invented abilities.",
            ),
            Step(
                message="so if i connect gmail what happens automatically",
                intent="Name the real built-in workflow(s) for Gmail and when they run; offer the card.",
            ),
            Step(
                message="cool. and where do you send stuff, here or telegram?",
                intent="Correct channel answer: web plus any linked bot; one line; offer the link flow only if not linked.",
            ),
        ],
    ),
]


class _TurnVerdict(BaseModel):
    did_the_job: int
    no_narration: int
    no_repeat: int
    short: int
    no_menu: int
    note: str


class _JourneyVerdict(BaseModel):
    value_visible: int
    setup_seamless: int
    note: str


class GradedTurn(BaseModel):
    step: Step
    turn: Turn
    card_ok: bool
    verdict: _TurnVerdict | None = None


class GradedJourney(BaseModel):
    journey: Journey
    opener: str
    turns: list[GradedTurn] = []
    verdict: _JourneyVerdict | None = None


TURN_PROMPT = """\
You are grading ONE reply from GAIA, a paid personal AI assistant that texts like a
sharp, warm friend. The user is a {role} who just finished onboarding. Nothing is
connected (no Gmail, Calendar or other tool) unless a tool in the list says so.

Conversation so far:
{history}

The user's message on THIS turn:
  "{message}"
What a good reply to THIS turn must do:
  {intent}

GAIA's reply:
  \"\"\"{reply}\"\"\"

Tools that actually ran on this turn: {tools}
(A connect card shows up as integration_connection_required; created reminders,
todos and workflows show up under their tool names. call_executor means a real
background job was handed off on this turn: saying it was handed off and that
the result will land here is honest; claiming it is done, live, sent or set up
before a result came back is not. Empty means text only.)

Score 1 or 0, strictly:
- did_the_job: the reply does what the intent line says, correctly.
- no_narration: nothing described as done, started or running unless a tool in the
  list did it; no "on it", no "I'll have that ready".
- no_repeat: does not re-offer something already declined or already offered in the
  history, and does not repeat its own earlier sentences.
- short: reads like a text; at most ~90 words; no headings or bullet lists.
- no_menu: does not end on a menu of options or a recap line ("Short version:",
  "To summarise"); ending on the answer itself, or on ONE next step or question, is fine.
note: one line on the biggest problem, or "fine".
"""

JOURNEY_PROMPT = """\
You are judging a whole first conversation between a new paid user ({role}) and
GAIA, a personal AI assistant, right after onboarding. Read it as the user.

{transcript}

Score 0-5 each:
- value_visible: by the end, would this user believe GAIA will actually take work off
  their plate this week? 5 = clearly yes with something concrete already set up or
  ready; 0 = it was all talk.
- setup_seamless: how little friction to get something running? 5 = one tap or one
  yes did it, cards and confirmations in the right place; 0 = loops, re-asks, dead
  ends, promises without artifacts.
note: two lines max on what most helped and most hurt.
"""


def _history(turns: list[GradedTurn], opener: str) -> str:
    lines = [f"  user: {opener}"]
    for t in turns:
        lines.append(f"  GAIA: {t.turn.reply}")
        lines.append(f"  user: {t.turn.message}")
    return "\n".join(lines)


async def _judge_turn(role: str, graded: GradedTurn, history: str) -> _TurnVerdict:
    prompt = TURN_PROMPT.format(
        role=role,
        history=history or "  (this is the first turn)",
        message=graded.turn.message,
        intent=graded.step.intent,
        reply=graded.turn.reply,
        tools=", ".join(graded.turn.tools) or "none",
    )
    return await judge(
        _TurnVerdict, prompt, label="activation_journeys_turn_judge", timeout=JUDGE_TIMEOUT_SECONDS
    )


async def _judge_journey(row: GradedJourney) -> _JourneyVerdict:
    transcript = "\n".join(
        [f"  user: {row.opener}"]
        + [
            line
            for t in row.turns
            for line in (f"  GAIA: {t.turn.reply}", f"  user: {t.turn.message}")
        ]
        + ([f"  GAIA: {row.turns[-1].turn.reply}"] if row.turns else [])
    )
    prompt = JOURNEY_PROMPT.format(role=row.journey.role, transcript=transcript)
    return await judge(
        _JourneyVerdict,
        prompt,
        label="activation_journeys_journey_judge",
        timeout=JUDGE_TIMEOUT_SECONDS,
    )


async def _run_journey(api_url: str, journey: Journey) -> GradedJourney:
    prefs = OnboardingPreferences(profession=journey.role, needs=journey.needs)
    email = USER_TEMPLATE.format(slug=journey.slug)
    await provision(api_url, email, prefs)
    opener = compose_first_message(prefs)
    row = GradedJourney(journey=journey, opener=opener)
    conversation_id = str(uuid4())
    history: list[dict[str, str]] = []
    async with dev_client(email) as client:
        await client.post(
            f"{api_url}/api/v1/conversations",
            json={"conversation_id": conversation_id, "description": "activation journey eval"},
            timeout=30.0,
        )
        first = await send_turn(client, api_url, opener, conversation_id, history, TURN_OPTIONS)
        history += [
            {"role": "user", "content": opener},
            {"role": "assistant", "content": first.reply},
        ]
        # The opener's reply is judged by need_playbooks.py; here it is context.
        row.turns.append(
            GradedTurn(
                step=Step(message=opener, intent="(opener, not scored)"),
                turn=first,
                card_ok=True,
            )
        )
        for step in journey.steps:
            print(f"    > {step.message}", flush=True)
            turn = await send_turn(
                client, api_url, step.message, conversation_id, history, TURN_OPTIONS
            )
            history += [
                {"role": "user", "content": step.message},
                {"role": "assistant", "content": turn.reply},
            ]
            lowered = turn.reply.lower()
            row.turns.append(
                GradedTurn(
                    step=step,
                    turn=turn,
                    card_ok=any(n in turn.tools for n in CONNECT_TOOLS)
                    or ("connect" not in lowered),
                )
            )
    return row


def _report(rows: list[GradedJourney]) -> None:
    cols = ("did_the_job", "no_narration", "no_repeat", "short", "no_menu", "card_ok")
    print("\n======== activation journeys\n")
    totals = dict.fromkeys(cols, 0)
    scored = 0
    for row in rows:
        print(
            f"[{row.journey.slug}] {row.journey.role}  value={row.verdict.value_visible if row.verdict else '?'}/5  seamless={row.verdict.setup_seamless if row.verdict else '?'}/5"
        )
        if row.verdict:
            print(f"  {row.verdict.note}")
        for t in row.turns[1:]:
            v = t.verdict
            marks = [getattr(v, c) if v else 0 for c in cols[:-1]] + [int(t.card_ok)]
            for c, m in zip(cols, marks, strict=True):
                totals[c] += m
            scored += 1
            flag = "" if all(marks) else " <--"
            print(
                f"  {' '.join(str(m) for m in marks)}  {t.step.message[:48]!r}{flag}  {v.note if v else ''}"
            )
        print()
    print(f"TOTAL over {scored} turns: " + "  ".join(f"{c}={totals[c]}" for c in cols))
    if rows:
        v = [r.verdict for r in rows if r.verdict]
        if v:
            print(
                f"value_visible avg={sum(x.value_visible for x in v) / len(v):.1f}/5  "
                f"setup_seamless avg={sum(x.setup_seamless for x in v) / len(v):.1f}/5"
            )
    print("\n---- transcripts\n")
    for row in rows:
        print(f"[{row.journey.slug}]")
        print(f"  user: {row.opener}")
        for t in row.turns:
            print(f"  GAIA: {t.turn.reply.replace(chr(10), chr(10) + '        ')[:700]}")
            print(f"        tools: {', '.join(t.turn.tools) or 'none'}")
            if t is not row.turns[-1]:
                nxt = row.turns[row.turns.index(t) + 1]
                print(f"  user: {nxt.turn.message}")
        print()


RAW_DIR = RUNS_DIR


def _save_raw(rows: list[GradedJourney]) -> Path:
    """Transcripts survive a judge outage: judging is the step most likely to
    die on credits, and the turns are the expensive part."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"journeys-{RUN_ID}.json"
    path.write_text(json.dumps([r.model_dump(mode="json") for r in rows], indent=1))
    return path


def _load_raw(path: Path) -> list[GradedJourney]:
    return [GradedJourney.model_validate(r) for r in json.loads(path.read_text())]


async def run(api_url: str, only: str | None, judge_only: Path | None) -> None:
    if judge_only:
        rows = _load_raw(judge_only)
    else:
        journeys = JOURNEYS
        if only:
            keys = [k.strip() for k in only.split(",") if k.strip()]
            journeys = [j for j in journeys if any(k in j.slug for k in keys)]
        rows = []
        for journey in journeys:
            print(f"... {journey.slug}", flush=True)
            rows.append(await _run_journey(api_url, journey))
        print(f"raw transcripts: {_save_raw(rows)}", flush=True)
    for row in rows:
        for t in row.turns[1:]:
            t.verdict = await _judge_turn(
                row.journey.role, t, _history(row.turns[: row.turns.index(t)], row.opener)
            )
        row.verdict = await _judge_journey(row)
    _report(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--only", default=None, help="Comma-separated substrings of journey slugs.")
    parser.add_argument(
        "--judge-only",
        default=None,
        help="Skip the API; judge the raw transcripts saved by an earlier run (path).",
    )
    args = parser.parse_args()
    await run(
        args.api_url.rstrip("/"),
        args.only,
        under_runs(Path(args.judge_only)) if args.judge_only else None,
    )


if __name__ == "__main__":
    asyncio.run(main())
