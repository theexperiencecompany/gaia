#!/usr/bin/env python3
# mypy: ignore-errors -- dev eval script; typing not maintained here
"""
Does a user who just paid get value, in their language, from a GAIA they can trust?

Not a test: it drives a REAL running API and a REAL model through the web's own
first-conversation path. Each scenario is a fresh Pro dev user who answers the
two onboarding questions (plus their browser language), completes onboarding
through POST /onboarding, which seeds the welcome thread and its chips, and then
writes into that thread the way prod first conversations open: a chip, a
German "hello", "am I free tomorrow?" with nothing connected. Each reply is
graded on what broke trust in prod: wrong language, stated state no tool
checked, a feature list, and a promise that never delivered.

Usage (from apps/api/, with the worktree API already running):

    uv run python scripts/evals/first_conversations.py --api-url http://localhost:9330 --label before
    uv run python scripts/evals/first_conversations.py --only german,free
    uv run python scripts/evals/first_conversations.py --judge-only runs/first-conversations-before-<id>.json
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import httpx
from pydantic import BaseModel

from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.welcome_copy import WELCOME_COPY
from scripts.evals.core.dev_users import dev_client, grant_pro, mint
from scripts.evals.core.judge import judge
from scripts.evals.core.live_chat import Turn, TurnOptions, send_turn
from scripts.evals.core.paths import RUNS_DIR, under_runs

DEFAULT_API_URL = os.environ.get("GAIA_API_URL", "http://localhost:9330")
RUN_ID = time.strftime("%H%M%S")
USER_TEMPLATE = "fc-{slug}-" + RUN_ID + "@gaia.local"
JUDGE_TIMEOUT_SECONDS = 90.0
TURN_OPTIONS = TurnOptions(timeout=240.0, delivery_wait_seconds=150.0, delivery_poll_seconds=4.0)
#: The welcome thread's escape-hatch chip, in every language it ships in.
SOMETHING_ELSE_LABELS = {copy.something_else for copy in WELCOME_COPY.values()}
#: A step whose message is this sends the welcome thread's first job chip.
FIRST_CHIP = "<first chip>"


class Scenario(BaseModel):
    slug: str
    profession: str
    needs: list[OnboardingNeed]
    language: str
    timezone: str
    messages: list[str]
    #: What a good reply to the scenario must do, read by the judge.
    intent: str


SCENARIOS: list[Scenario] = [
    Scenario(
        slug="german-founder-hello",
        profession="founder",
        needs=[OnboardingNeed.INBOX, OnboardingNeed.FOUNDER_TEAM_UPDATES],
        language="de-DE",
        timezone="Europe/Berlin",
        messages=["Hallo! Womit fangen wir am besten an?"],
        intent="Reply in German. Propose one or two concrete first jobs for a founder's inbox and team updates, end on an easy yes.",
    ),
    Scenario(
        slug="spanish-sales-what-can-you-do",
        profession="sales",
        needs=[OnboardingNeed.SALES_LEADS, OnboardingNeed.REMINDERS],
        language="es-CO",
        timezone="America/Bogota",
        messages=["Hola, ¿qué puedes hacer por mí?"],
        intent="Reply in Spanish. Not a feature list: one or two things for THIS salesperson's leads, offered as something to start now.",
    ),
    Scenario(
        slug="portuguese-engineer-prs",
        profession="engineering",
        needs=[OnboardingNeed.ENGINEERING_PRS, OnboardingNeed.MORNINGS],
        language="pt-BR",
        timezone="America/Sao_Paulo",
        messages=["Oi! Quero parar de esquecer os PRs que estão esperando por mim"],
        intent="Reply in Portuguese. GitHub is not connected: the connect is handed off (card), plus what it will do once connected.",
    ),
    Scenario(
        slug="french-creative-deadlines",
        profession="creative",
        needs=[OnboardingNeed.CREATIVE_DEADLINES],
        language="fr-FR",
        timezone="Europe/Paris",
        messages=["Salut, j'ai trois deadlines clients cette semaine et je panique un peu"],
        intent="Reply in French. Take the deadlines now (ask for names and dates in one line, or offer to track them); warm, no lecture.",
    ),
    Scenario(
        slug="english-student-first-chip",
        profession="student",
        needs=[OnboardingNeed.STUDENT_ASSIGNMENTS, OnboardingNeed.STUDENT_EXAMS],
        language="en-US",
        timezone="America/New_York",
        messages=[FIRST_CHIP],
        intent="Treat the chip as a handover: start that job (ask the one missing detail or do the first piece). Never ask what the chip meant.",
    ),
    Scenario(
        slug="say-hi-marketing",
        profession="marketing",
        needs=[OnboardingNeed.MARKETING_CONTENT, OnboardingNeed.MARKETING_REPORTS],
        language="en-GB",
        timezone="Europe/London",
        messages=["What can you do for me?"],
        intent="Not a capability tour: two or three lines aimed at a marketer's content and reports, ending on one concrete thing to start now.",
    ),
    Scenario(
        slug="free-tomorrow-no-calendar",
        profession="executive",
        needs=[OnboardingNeed.CALENDAR, OnboardingNeed.EXECUTIVE_DECISIONS],
        language="en-US",
        timezone="America/Chicago",
        messages=["Am I free tomorrow afternoon?"],
        intent="Calendar is NOT connected. Never say they are free or busy; say it cannot see their calendar yet and hand off the connect (card).",
    ),
    Scenario(
        slug="notion-add-feedback",
        profession="product",
        needs=[OnboardingNeed.PRODUCT_FEEDBACK, OnboardingNeed.TOOLS],
        language="en-US",
        timezone="America/Los_Angeles",
        messages=["Add this to my Notion feedback database: users keep asking for dark mode"],
        intent="Notion is NOT connected. No claim it was added; the connect is handed off, and the note is kept or offered so nothing is lost.",
    ),
    Scenario(
        slug="inbox-state-claim",
        profession="founder",
        needs=[OnboardingNeed.INBOX],
        language="en-US",
        timezone="Asia/Kolkata",
        messages=["Have you already gone through my inbox? What needs me today?"],
        intent="Gmail is NOT connected. Honest that it has not read anything, no invented emails or counts; hand off the connect.",
    ),
    Scenario(
        slug="finance-recurring-reminder",
        profession="finance",
        needs=[OnboardingNeed.FINANCE_NUMBERS],
        language="en-US",
        timezone="America/New_York",
        messages=["Remind me every Friday at 4pm to chase the team for expense reports"],
        intent="A recurring reminder actually created (tool ran) and confirmed in one line with day, time and timezone. No promise without the result.",
    ),
    Scenario(
        slug="research-background-delivery",
        profession="sales",
        needs=[OnboardingNeed.SALES_CALL_RESEARCH],
        language="en-US",
        timezone="Europe/Berlin",
        messages=["Find me five fintech companies in Berlin that are hiring sales reps right now"],
        intent="Real research: either the list arrives in this turn, or the ack is followed by a delivered result. An ack with nothing delivered fails.",
    ),
]


class Welcome(BaseModel):
    bubbles: list[str] = []
    chips: list[str] = []


class Row(BaseModel):
    scenario: Scenario
    welcome: Welcome
    conversation_id: str = ""
    turns: list[Turn] = []
    verdict: "Verdict | None" = None


class Verdict(BaseModel):
    language_match: int
    no_unverified_state: int
    no_feature_list: int
    promise_kept: int
    did_the_job: int
    note: str


Row.model_rebuild()

JUDGE_PROMPT = """\
You are grading GAIA, a paid personal assistant, in a user's FIRST conversation,
minutes after they paid. Nothing is connected (no Gmail, Calendar, Notion, GitHub)
unless a tool below says so. The user's browser language is {language}.

GAIA opened the thread with:
{welcome}

Then:
{transcript}

What a good first exchange does here: {intent}

Score each 1 or 0, strictly, quoting nothing:
- language_match: every GAIA reply after the user wrote is in the language the
  user wrote in (the welcome is not graded here).
- no_unverified_state: GAIA states nothing about the user's calendar, inbox, tools
  or data (free, busy, empty, "added", "already done") that no tool in the list
  checked or did, and blames no cache, glitch or view.
- no_feature_list: no list of GAIA's features or capabilities; offers are
  specific to this user.
- promise_kept: every "I'll / working on it / running in the background" is
  followed by the delivered result in the transcript; a reply marked
  "[nothing delivered within budget]" fails.
- did_the_job: does what the intent line says.
note: one line on the biggest problem, or "fine".
"""


def _transcript(row: Row) -> str:
    lines = []
    for turn in row.turns:
        lines.append(f"  user: {turn.message}")
        lines.append(f"  GAIA: {turn.reply}")
        lines.append(f"  (tools that ran: {', '.join(turn.tools) or 'none'})")
    return "\n".join(lines)


async def _read_welcome(client: httpx.AsyncClient, api_url: str) -> tuple[str, Welcome]:
    status = (await client.get(f"{api_url}/api/v1/onboarding/status", timeout=30.0)).json()
    conversation_id = status.get("getting_started_conversation_id") or ""
    if not conversation_id:
        raise SystemExit(f"onboarding completed without a welcome thread: {status}")
    payload = (
        await client.get(f"{api_url}/api/v1/conversations/{conversation_id}", timeout=30.0)
    ).json()
    convo = payload.get("conversation", payload)
    welcome = Welcome()
    for message in convo.get("messages") or []:
        if message.get("type") != "bot":
            continue
        text = (message.get("response") or "").strip()
        if text:
            welcome.bubbles.extend(part.strip() for part in text.split("<NEW_MESSAGE_BREAK>"))
        welcome.chips.extend(message.get("follow_up_actions") or [])
    return conversation_id, welcome


async def _run(api_url: str, scenario: Scenario) -> Row:
    email = USER_TEMPLATE.format(slug=scenario.slug)
    preferences = OnboardingPreferences.model_validate(
        {"profession": scenario.profession, "needs": scenario.needs, "language": scenario.language}
    )
    async with httpx.AsyncClient(timeout=60.0) as plain:
        await mint(plain, api_url, email)
    await grant_pro(email)
    async with dev_client(email) as client:
        # The wizard's own order: answers first (the prewarm reads them), then completion.
        body = preferences.model_dump(mode="json", exclude_none=True) | {
            "language": scenario.language
        }
        (
            await client.patch(f"{api_url}/api/v1/onboarding/preferences", json=body, timeout=60.0)
        ).raise_for_status()
        await asyncio.sleep(12)
        completion = await client.post(
            f"{api_url}/api/v1/onboarding",
            json={
                "profession": scenario.profession,
                "needs": [need.value for need in scenario.needs],
                "timezone": scenario.timezone,
                "language": scenario.language,
            },
            timeout=90.0,
        )
        completion.raise_for_status()
        conversation_id, welcome = await _read_welcome(client, api_url)
        row = Row(scenario=scenario, welcome=welcome, conversation_id=conversation_id)
        history = [{"role": "assistant", "content": bubble} for bubble in welcome.bubbles]
        for raw in scenario.messages:
            message = raw
            if raw == FIRST_CHIP:
                message = next(
                    (c for c in welcome.chips if c not in SOMETHING_ELSE_LABELS), welcome.chips[-1]
                )
            print(f"    > {message}", flush=True)
            turn = await send_turn(client, api_url, message, conversation_id, history, TURN_OPTIONS)
            history += [
                {"role": "user", "content": message},
                {"role": "assistant", "content": turn.reply},
            ]
            row.turns.append(turn)
    return row


async def _judge(row: Row) -> Verdict:
    prompt = JUDGE_PROMPT.format(
        language=row.scenario.language,
        welcome="\n".join(f"  GAIA: {b}" for b in row.welcome.bubbles)
        + f"\n  (chips: {', '.join(row.welcome.chips) or 'none'})",
        transcript=_transcript(row),
        intent=row.scenario.intent,
    )
    return await judge(
        Verdict, prompt, label="first_conversations_judge", timeout=JUDGE_TIMEOUT_SECONDS
    )


COLUMNS = (
    "language_match",
    "no_unverified_state",
    "no_feature_list",
    "promise_kept",
    "did_the_job",
)


def _markdown(rows: list[Row], label: str) -> str:
    out = [f"# First conversations eval: {label} ({RUN_ID})", ""]
    totals = dict.fromkeys(COLUMNS, 0)
    out.append("| scenario | " + " | ".join(COLUMNS) + " | note |")
    out.append("|---" * (len(COLUMNS) + 2) + "|")
    for row in rows:
        v = row.verdict
        marks = [getattr(v, c) if v else 0 for c in COLUMNS]
        for c, m in zip(COLUMNS, marks, strict=True):
            totals[c] += m
        out.append(
            f"| {row.scenario.slug} | "
            + " | ".join(map(str, marks))
            + f" | {v.note if v else 'unjudged'} |"
        )
    out.append("| **total** | " + " | ".join(f"{totals[c]}/{len(rows)}" for c in COLUMNS) + " | |")
    out.append("")
    for row in rows:
        out += [
            f"## {row.scenario.slug}",
            f"{row.scenario.profession}, {row.scenario.language}, needs {', '.join(n.value for n in row.scenario.needs)}",
            "",
        ]
        out += [f"> GAIA: {b}" for b in row.welcome.bubbles]
        out += [f"> chips: {', '.join(row.welcome.chips)}", ""]
        for turn in row.turns:
            out.append(f"**user:** {turn.message}")
            out.append("")
            out.append("**GAIA:** " + turn.reply.replace("<NEW_MESSAGE_BREAK>", " / "))
            out.append("")
            out.append(f"_tools: {', '.join(turn.tools) or 'none'}_")
            out.append("")
    return "\n".join(out)


async def run(api_url: str, only: str | None, judge_only: Path | None, label: str) -> None:
    if judge_only:
        rows = [Row.model_validate(r) for r in json.loads(judge_only.read_text())]
    else:
        scenarios = SCENARIOS
        if only:
            keys = [k.strip() for k in only.split(",") if k.strip()]
            scenarios = [s for s in scenarios if any(k in s.slug for k in keys)]
        rows = []
        for scenario in scenarios:
            print(f"... {scenario.slug}", flush=True)
            rows.append(await _run(api_url, scenario))
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    raw = RUNS_DIR / f"first-conversations-{label}-{RUN_ID}.json"
    raw.write_text(
        json.dumps([r.model_dump(mode="json") for r in rows], indent=1, ensure_ascii=False)
    )
    print(f"raw transcripts: {raw}", flush=True)
    for row in rows:
        row.verdict = await _judge(row)
    raw.write_text(
        json.dumps([r.model_dump(mode="json") for r in rows], indent=1, ensure_ascii=False)
    )
    report = RUNS_DIR / f"first-conversations-{label}-{RUN_ID}.md"
    report.write_text(_markdown(rows, label))
    print(f"report: {report}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--only", default=None, help="Comma-separated substrings of scenario slugs."
    )
    parser.add_argument(
        "--label", default="run", help="Tag for the output files, e.g. before / after."
    )
    parser.add_argument(
        "--judge-only", default=None, help="Re-judge a raw transcript file under runs/."
    )
    args = parser.parse_args()
    await run(
        args.api_url.rstrip("/"),
        args.only,
        under_runs(Path(args.judge_only)) if args.judge_only else None,
        args.label,
    )


if __name__ == "__main__":
    asyncio.run(main())
