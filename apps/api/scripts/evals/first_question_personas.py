#!/usr/bin/env python3
# mypy: ignore-errors -- dev eval script; typing not maintained here
"""
Run `compose_first_question` over the onboarding answers we actually see.

Not a test: it calls a real model, so it goes red when the provider is down and
that would be a useless CI signal. It exists to read the copy — ten personas,
their question, their chips, and whether the validator let the model's answer
through or fell back to the static line.

Usage (from apps/api/):
    uv run python scripts/evals/first_question_personas.py
    uv run python scripts/evals/first_question_personas.py --follow

`--follow` takes each chip of the first five personas and sends it as the user's
next message to the LOCALLY RUNNING API, so you can read GAIA's actual reply and
judge whether a chip leads anywhere concrete. It needs `mise dev --agent` (or any
boot with `DEV_AUTH_BYPASS_EMAIL` set); it mints one dev user per persona, which
must be able to pass the paid-only gate.

`--turns 2` (the default) keeps going: it answers GAIA's offer with "yes" in the
SAME conversation and captures whether a tool actually ran on that turn. An offer
nobody can accept is the failure mode a single-turn read cannot see.

Every reply is then scored 0/1 by an LLM judge on the same lane against the rules
the new-user prompt block actually ships, and the script prints a per-reply table,
per-criterion totals, and the worst replies verbatim.
"""

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

try:
    from app.config.secrets import inject_infisical_secrets

    inject_infisical_secrets()
except Exception as e:
    print(f"[warn] Could not inject Infisical secrets (expected in local dev): {e}")

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

import httpx
from pydantic import BaseModel

from app.agents.llm.client import (
    LLMInvokeOptions,
    ainvoke_llm,
    background_structured_runnable,
)
from app.agents.prompts.new_user_prompts import TARGET_REPLY_EXAMPLE
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.onboarding.first_conversation import HANDOVER_WITHOUT_JOB
from app.services.onboarding.first_question import (
    QUESTION_TIMEOUT_SECONDS,
    compose_first_question,
)

DEFAULT_API_URL = os.environ.get("GAIA_API_URL", "http://localhost:8000")
#: One minted dev user per persona. Sharing a user leaked context between them
#: (a "the writing" turn answered with the previous persona's unconnected-Gmail
#: thread), which made the replies unreadable as a signal about the chip.
FOLLOW_USER_TEMPLATE = os.environ.get("GAIA_DEV_USER_TEMPLATE", "fq-{slug}@gaia.local")
FOLLOW_PERSONA_COUNT = 5
REPLY_PREVIEW_WORDS = 40
FOLLOW_TIMEOUT_SECONDS = 180.0
#: The judge is a cheap structured call and nobody is waiting on it, so it gets
#: room to succeed rather than turning a slow local lane into a scoring gap.
JUDGE_TIMEOUT_SECONDS = 180.0
#: Judging runs after every conversation is collected, so it can fan out. Kept
#: low enough not to trip provider rate limits on the cheap dev lane.
JUDGE_CONCURRENCY = 4
WORST_REPLY_COUNT = 5
#: Turn 1 is the chip; turn 2 is the "yes" that proves the offer was real.
DEFAULT_TURNS = 2
#: A stream that carried no prose at all. Never graded — see _grade_all.
NO_TEXT_REPLY = "[no text in stream]"

PERSONAS: list[tuple[str, OnboardingPreferences, str | None]] = [
    (
        "founder + inbox + calendar",
        OnboardingPreferences(
            profession="founder", needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR]
        ),
        None,
    ),
    (
        "sales + todos",
        OnboardingPreferences(profession="sales", needs=[OnboardingNeed.TODOS]),
        None,
    ),
    (
        "student + research",
        OnboardingPreferences(profession="student", needs=[OnboardingNeed.RESEARCH]),
        None,
    ),
    (
        "engineer + automation",
        OnboardingPreferences(profession="engineering", needs=[OnboardingNeed.AUTOMATION]),
        None,
    ),
    (
        'typed "marketing lead" + other "content calendar"',
        OnboardingPreferences(profession="marketing lead", other_need="content calendar"),
        None,
    ),
    (
        "executive + briefings + memory",
        OnboardingPreferences(
            profession="executive", needs=[OnboardingNeed.BRIEFINGS, OnboardingNeed.MEMORY]
        ),
        None,
    ),
    (
        'typed "I run a bakery" + other "supplier emails"',
        OnboardingPreferences(profession="I run a bakery", other_need="supplier emails"),
        None,
    ),
    (
        "creative + research",
        OnboardingPreferences(profession="creative", needs=[OnboardingNeed.RESEARCH]),
        "telegram",
    ),
    (
        "finance + calendar",
        OnboardingPreferences(profession="finance", needs=[OnboardingNeed.CALENDAR]),
        None,
    ),
    (
        'other, no needs, other "chasing invoices"',
        OnboardingPreferences(profession="other", needs=[], other_need="chasing invoices"),
        None,
    ),
]


async def run_personas(timeout_seconds: float) -> list[tuple[str, object]]:
    """One model call per persona, concurrently — they share nothing."""
    results = await asyncio.gather(
        *(
            compose_first_question(prefs, platform, timeout_seconds=timeout_seconds)
            for _, prefs, platform in PERSONAS
        )
    )
    return list(zip([label for label, _, _ in PERSONAS], results, strict=True))


def print_personas(rows: list[tuple[str, object]]) -> None:
    fallbacks = 0
    for label, result in rows:
        print(f"\n=== {label}")
        if result is None:
            fallbacks += 1
            print("  outcome: fallback (static line kept)")
            continue
        print("  outcome: llm")
        print(f"  chips: {result.chips}")
        print(f"  chips:    {result.chips}")
    print(f"\nfallbacks: {fallbacks}/{len(rows)}")


class Turn(BaseModel):
    """One GAIA reply plus the evidence that she did something, not just talked."""

    message: str
    reply: str
    #: ``tool_name`` of every ``tool_data`` entry the stream carried. A connect
    #: card arrives as ``integration_connection_required``, a created list as the
    #: todo tool's own name — either way the turn did a thing.
    tools: list[str]


def _frame_tool_names(frame: dict) -> list[str]:
    """The tool names in one SSE frame's ``tool_data``, which is an entry or a list."""
    payload = frame.get("tool_data")
    entries = payload if isinstance(payload, list) else [payload]
    return [
        entry["tool_name"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("tool_name"), str)
    ]


async def _send_turn(
    client: httpx.AsyncClient,
    api_url: str,
    message: str,
    conversation_id: str,
    history: list[dict[str, str]],
) -> Turn:
    """One comms turn against the running API, joined from its SSE frames.

    ``history`` is the prior turns of THIS conversation in the shape the endpoint
    expects; the new user message is appended to it. Sharing the conversation id
    across turns is what makes turn 2 a follow-up rather than a second cold open.
    """
    messages = [*history, {"role": "user", "content": message}]
    body = {
        "message": message,
        "messages": messages,
        "conversation_id": conversation_id,
        "turn_id": str(uuid4()),
    }
    chunks: list[str] = []
    tools: list[str] = []
    async with client.stream(
        "POST", f"{api_url}/api/v1/chat-stream", json=body, timeout=FOLLOW_TIMEOUT_SECONDS
    ) as response:
        if response.status_code != 200:
            await response.aread()
            return Turn(
                message=message,
                reply=f"[HTTP {response.status_code}] {response.text[:300]}",
                tools=[],
            )
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                frame = json.loads(line[len("data: ") :])
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            if isinstance(frame.get("response"), str):
                chunks.append(frame["response"])
            tools.extend(_frame_tool_names(frame))
    return Turn(
        message=message,
        reply="".join(chunks).strip() or NO_TEXT_REPLY,
        tools=tools,
    )


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]


async def _provision(api_url: str, email: str, preferences: OnboardingPreferences) -> None:
    """A fresh dev user carrying this persona's answers.

    The answers are saved through the real PATCH, so the same prewarm that runs
    in the product writes this persona's question and chips into the cache the
    agent's new-user guidance reads them back from.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        await client.post(f"{api_url}/api/v1/dev/users", json={"email": email, "name": "Persona"})
        # The API is paid-only: a follow turn from a free user is a 402 before it
        # reaches the agent, so each persona gets a dev subscription first.
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/grant_pro_access.py", "--email", email],
            check=True,
            capture_output=True,
        )
        await client.patch(
            f"{api_url}/api/v1/onboarding/preferences",
            headers={"X-Dev-User": email},
            json=preferences.model_dump(mode="json", exclude_none=True),
        )


def _preview(reply: str) -> str:
    words = reply.split()
    trimmed = " ".join(words[:REPLY_PREVIEW_WORDS])
    return trimmed + ("..." if len(words) > REPLY_PREVIEW_WORDS else "")


#: The user's second message. A bare "yes" is the cheapest possible accept, and
#: it is what the offer's own closing question asks for — if GAIA cannot act on
#: it she has offered something she cannot do.
ACCEPT_MESSAGE = "yes"

#: 0/1 criteria, in report order. The key is the column header; the value is what
#: the judge is asked. (i) is scored on accept turns only — a chip turn is an
#: offer by design, so grading it for action would mark correct behaviour wrong.
CRITERIA: dict[str, str] = {
    "a_choice": (
        "Treats the user's message as a CHOICE they made and runs with it. Score 0 if the "
        "reply asks what they meant, asks them to clarify or expand the message, or treats "
        "it as a search term."
    ),
    "b_concrete": (
        "OFFER TURNS ONLY. Proposes two or three CONCRETE things GAIA can set up now (a "
        "connect link, a scheduled workflow, a list she holds, a reminder). Score 0 for "
        "vague capability talk, a single vague offer, or more than three."
    ),
    "c_formatting": (
        "Formatting fits the content. Prose when it is prose, a list only when there really "
        "is a list. Markdown is allowed and correct when there are three or more parallel "
        "items the eye needs to scan, each with its own detail. Score 0 when two or three "
        "offers that would fit in a sentence are broken into bullets or numbered items, and "
        "score 0 for headings or decorative bold in a short reply."
    ),
    "d_no_narration": (
        "Never claims to have already done something that did not happen. Score 0 for "
        '"I\'ve started", "I\'ve got X ready", "that\'s set up", "I\'ve created" when no '
        "tool actually ran this turn."
    ),
    "e_no_leadin": (
        'No stock lead-in. Score 0 for openers like "Here\'s what I can set up", "Here are '
        'a few things", "I can help with that", "Great choice".'
    ),
    "f_one_question": (
        "OFFER TURNS ONLY. Ends on exactly ONE easy question. Score 0 for zero questions, "
        "for two or more question marks, or for a question that demands work from the user."
    ),
    "g_short": "Under about 90 words. Score 0 if noticeably longer.",
    "h1_sentences": (
        "Coherent sentences a person would actually type. Every sentence has a subject and "
        'a verb, carries one idea, and joins to the next the way speech joins them ("and", '
        '"then", "once that\'s in"). Score 0 for stacked fragments and clipped noun phrases '
        'used as sentences, e.g. "Fill it, got it. Tracking your pipeline follow-ups so a '
        'lead never goes quiet." Score 0 for telegraphic notes rather than writing.'
    ),
    "h2_opener": (
        "The opener is a natural way a person would start this reply. Score 0 for the "
        "echo-and-TAG formula that repeats their word back and appends an acknowledgement "
        'tag ("Growth, got it.", "Reading and marking, got it.", "The intro, noted.") and 0 '
        'for a canned acknowledgement standing alone ("On it.", "Sure thing.", '
        '"Absolutely."). Naming the topic plainly to orient the reader is FINE and is what '
        'the target example does ("Okay, pipeline."): the tag is the failure, not the topic.'
    ),
    "i_acts": (
        "ACCEPT TURNS ONLY. After the user said yes, the reply either DID one thing (a tool "
        "ran, a connect card was shown, a list was created) or asked for the single missing "
        "detail needed to do it. Score 0 if it merely re-offers the same menu again."
    ),
}

ACCEPT_ONLY_CRITERIA = {"i_acts"}
#: Proposing a menu is the RIGHT move on the chip turn and the WRONG move once the
#: user has said yes, so grading (b) on an accept turn would mark correct behaviour
#: down and put its own target permanently out of reach.
#: ``f_one_question`` joined them for the same reason: a turn that correctly DOES
#: the thing has nothing left to ask, and "Gmail connect link is on its way, tap
#: it and I'll take the inbox from there." was being marked down for ending
#: without a question mark.
OFFER_ONLY_CRITERIA = {"b_concrete", "f_one_question"}


class _Verdict(BaseModel):
    """One reply's scores. Every field is 0 or 1; the schema forces all of them."""

    a_choice: int
    b_concrete: int
    c_formatting: int
    d_no_narration: int
    e_no_leadin: int
    f_one_question: int
    g_short: int
    h1_sentences: int
    h2_opener: int
    i_acts: int


JUDGE_PROMPT = """\
You are grading ONE reply from GAIA, an AI assistant, to a brand-new user.

Context. GAIA seeded an opening conversation ending in this question:
  "{question}"
The user answered by tapping a chip. This is turn {turn_number} of that thread.

The user's message on this turn:
  "{message}"

GAIA's reply:
  \"\"\"{reply}\"\"\"

Tools that actually ran on this turn: {tools}

This is the register to grade against. A reply in this voice scores 1 on the writing
criteria; the further from it, the more of them are 0:
  \"\"\"{target}\"\"\"

Score each criterion 1 (met) or 0 (not met). Be strict: when in doubt, score 0.
{criteria}

{accept_note}"""

ACCEPT_NOTE_OFFER = (
    "This is an OFFER turn, not an accept turn. Score i_acts as 1 always: it is not "
    "graded on offer turns."
)
ACCEPT_NOTE_ACCEPT = (
    "This IS the accept turn: the user said yes to what GAIA offered. Grade i_acts "
    "strictly against the tools listed above."
)


async def _judge(turn: Turn, question: str, turn_number: int) -> _Verdict:
    """One structured grading call on the same dev lane the rest of the script uses."""
    criteria = "\n".join(f"- {key}: {text}" for key, text in CRITERIA.items())
    prompt = JUDGE_PROMPT.format(
        question=question,
        turn_number=turn_number,
        message=turn.message,
        reply=turn.reply,
        tools=", ".join(turn.tools) or "none",
        target=TARGET_REPLY_EXAMPLE,
        criteria=criteria,
        accept_note=ACCEPT_NOTE_ACCEPT if turn_number > 1 else ACCEPT_NOTE_OFFER,
    )
    return await ainvoke_llm(
        background_structured_runnable(_Verdict, temperature=0.0),
        prompt,
        label="first_question_eval_judge",
        options=LLMInvokeOptions(max_attempts=2, timeout=JUDGE_TIMEOUT_SECONDS),
    )


class Graded(BaseModel):
    """A reply, what produced it, and its scores — one row of the report."""

    persona: str
    chip: str
    turn_number: int
    question: str
    turn: Turn
    verdict: _Verdict | None = None


async def run_follow(rows: list[tuple[str, object]], api_url: str, turns: int) -> None:
    """Each chip of the first personas, replayed as a real thread of ``turns`` turns.

    Every persona gets its own minted dev user, so one persona's threads can
    never surface in another's reply, and every chip gets its own conversation id
    so the accept turn lands in the thread that made the offer.

    Every conversation is collected BEFORE any judging: the replies are the
    expensive, unrepeatable part, and a slow judge must not be able to cost a
    ten-minute run of them.
    """
    collected: list[Graded] = []
    for index, (label, result) in enumerate(rows[:FOLLOW_PERSONA_COUNT]):
        print(f"\n\n######## follow: {label}")
        if result is None:
            print("  skipped (no chips were composed)")
            continue
        email = FOLLOW_USER_TEMPLATE.format(slug=f"{index}-{_slug(label)}")
        await _provision(api_url, email, PERSONAS[index][1])
        print(f"  user: {email}")
        print(f"  chips: {result.chips}")
        async with httpx.AsyncClient(
            headers={"X-Dev-User": email}, cookies={"dev_bypass_user": email}
        ) as client:
            for chip in result.chips:
                # The cheap dev lane sometimes returns a degenerate draft — a "."
                # question with four EMPTY chips. Replaying one sends an empty
                # message, gets "[no text in stream]" back, and the judge scored
                # that silence a straight pass, which quietly inflated every
                # total. A chip with no words is a composer failure, not a reply
                # worth grading.
                if not chip.strip():
                    print("\n  --- chip: <empty> — skipped (degenerate composer output)")
                    continue
                conversation_id = str(uuid4())
                history: list[dict[str, str]] = []
                print(f"\n  --- chip: {chip}")
                for turn_number in range(1, turns + 1):
                    message = chip if turn_number == 1 else ACCEPT_MESSAGE
                    turn = await _send_turn(client, api_url, message, conversation_id, history)
                    history.append({"role": "user", "content": message})
                    history.append({"role": "assistant", "content": turn.reply})
                    collected.append(
                        Graded(
                            persona=label,
                            chip=chip,
                            turn_number=turn_number,
                            question=HANDOVER_WITHOUT_JOB,
                            turn=turn,
                        )
                    )
                    tools = ", ".join(turn.tools) or "none"
                    print(f"  [t{turn_number}] user: {message}")
                    print(f"  [t{turn_number}] tools: {tools}")
                    print(f"  [t{turn_number}] GAIA: {_preview(turn.reply)}")

    print(f"\n\n######## judging {len(collected)} replies")
    await _grade_all(collected)
    print_scores(collected)


async def _grade_all(collected: list[Graded]) -> None:
    """Judge every collected reply, a few at a time, writing verdicts in place.

    A judge that fails leaves ``verdict`` as None and is reported as ungraded
    rather than scored zero: a provider blip is not the agent getting it wrong,
    and averaging it in as a 0 would understate the prompt.
    """
    semaphore = asyncio.Semaphore(JUDGE_CONCURRENCY)

    async def grade(row: Graded) -> None:
        # A turn that produced no prose is an infrastructure failure, not an
        # answer. Grading it lets an empty reply collect points for every rule
        # it did not break.
        if row.turn.reply == NO_TEXT_REPLY or not row.turn.reply.strip():
            print(f"  [no reply] {row.persona} | {row.chip} | t{row.turn_number}")
            return
        async with semaphore:
            try:
                row.verdict = await _judge(row.turn, row.question, row.turn_number)
            except Exception as e:
                print(f"  [judge failed] {row.persona} | {row.chip} | t{row.turn_number}: {e!r}")

    await asyncio.gather(*(grade(row) for row in collected))
    ungraded = sum(1 for row in collected if row.verdict is None)
    if ungraded:
        print(f"  ungraded (judge failed): {ungraded}/{len(collected)}")


def _scored_criteria(row: Graded) -> dict[str, int]:
    """The criteria that actually apply to this row.

    Offer turns are not graded on acting, and accept turns are not graded on
    offering: scoring either everywhere would report correct behaviour as a miss.
    """
    if row.verdict is None:
        return {}
    scores = row.verdict.model_dump()
    skip = ACCEPT_ONLY_CRITERIA if row.turn_number == 1 else OFFER_ONLY_CRITERIA
    for key in skip:
        scores.pop(key)
    return scores


def _opener(reply: str) -> str:
    """The first few words, lowercased — the unit repetition is visible in."""
    return " ".join(reply.split()[:3]).lower().strip(".,:")


def print_scores(graded: list[Graded]) -> None:
    """Per-reply table, per-criterion totals, and the worst replies verbatim."""
    if not graded:
        return
    keys = list(CRITERIA)
    print("\n\n======== per-reply scores")
    header = f"{'persona':<28} {'chip':<22} t  " + " ".join(f"{k[:1]}" for k in keys)
    print(header)
    for row in graded:
        scores = _scored_criteria(row)
        cells = " ".join("." if k not in scores else str(scores[k]) for k in keys)
        print(f"{row.persona[:27]:<28} {row.chip[:21]:<22} {row.turn_number}  {cells}")

    print("\n======== totals per criterion")
    for key in keys:
        applicable = [row for row in graded if key in _scored_criteria(row)]
        if not applicable:
            continue
        met = sum(_scored_criteria(row)[key] for row in applicable)
        pct = 100.0 * met / len(applicable)
        print(f"  {key:<16} {met:>3}/{len(applicable):<3} {pct:5.1f}%")

    # h2 is judged per reply, but "varies across replies" is only visible in the
    # set, so the repetition is measured mechanically rather than asked of a judge
    # that sees one reply at a time.
    openers = [_opener(row.turn.reply) for row in graded if row.turn_number == 1]
    if openers:
        counts = Counter(openers)
        distinct = 100.0 * len(counts) / len(openers)
        print(f"\n======== opener variety (offer turns): {len(counts)}/{len(openers)} distinct")
        for opener, count in counts.most_common(5):
            if count > 1:
                print(f"  {count}x {opener!r}")
        print(f"  distinct: {distinct:5.1f}%")

    scored = [row for row in graded if row.verdict is not None]
    worst = sorted(scored, key=lambda row: sum(_scored_criteria(row).values()))[:WORST_REPLY_COUNT]
    print(f"\n======== worst {len(worst)} replies (verbatim)")
    for row in worst:
        scores = _scored_criteria(row)
        failed = ", ".join(key for key, value in scores.items() if not value) or "none"
        print(f"\n--- {row.persona} | chip {row.chip!r} | turn {row.turn_number}")
        print(f"    user: {row.turn.message}")
        print(f"    tools: {', '.join(row.turn.tools) or 'none'}")
        print(f"    failed: {failed}")
        print(f"    reply: {row.turn.reply}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Replay each chip through the running API's comms agent.",
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument(
        "--timeout",
        type=float,
        default=QUESTION_TIMEOUT_SECONDS,
        help="Override the 4s production ceiling when the local lane is slower.",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=DEFAULT_TURNS,
        help='Turns per chip thread. Turn 1 is the chip; every turn after it is "yes".',
    )
    args = parser.parse_args()

    rows = await run_personas(args.timeout)
    print_personas(rows)
    if args.follow:
        await run_follow(rows, args.api_url.rstrip("/"), args.turns)


if __name__ == "__main__":
    asyncio.run(main())
