#!/usr/bin/env python3
# mypy: ignore-errors -- dev eval script; typing not maintained here
"""
Read GAIA's chat quality on the messages an ordinary Pro user actually sends.

Not a test: it drives a REAL running API and a REAL model, so it goes red when
the provider or the local stack is down, which is a useless CI signal. It exists
to read the copy. Fourteen short multi-turn scripts (small talk, a factual
question, a productivity ask with nothing connected, a vent, an out-of-scope
request, a draft request, a dead-end "yes") run as real conversations on fresh
dev users, and every reply is scored 0/1 by an LLM judge on the same dev lane.

Usage (from apps/api/, with the worktree API already running):
    export OPENROUTER_API_KEY=$(security find-generic-password -a "$USER" -s openrouter-api -w)
    export DEV_DEFAULT_MODEL=deepseek-v4-flash
    uv run python scripts/evals/chat_quality.py --api-url http://localhost:9330

Each scenario gets its own minted dev user (a shared user leaks one scenario's
thread into another's reply) with the same realistic onboarding profile, granted
Pro so the paid-only gate lets the turn reach the agent.
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
import time
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
from app.models.user_models import OnboardingNeed, OnboardingPreferences

DEFAULT_API_URL = os.environ.get("GAIA_API_URL", "http://localhost:9330")
# A fresh user per scenario AND per run: memory from an earlier run would leak
# into "hey" and make small talk look more informed than it is.
RUN_ID = time.strftime("%H%M%S")
USER_TEMPLATE = os.environ.get("GAIA_DEV_USER_TEMPLATE", "cq-{slug}-" + RUN_ID + "@gaia.local")
#: Delegated turns ack on the SSE stream and deliver the real answer as a later
#: bot message (executor cards on the stream, comms narration via WebSocket).
#: The user sees both, so the judge must too: poll the saved conversation.
DELIVERY_WAIT_SECONDS = 75.0
DELIVERY_POLL_SECONDS = 3.0
TURN_TIMEOUT_SECONDS = 180.0
JUDGE_TIMEOUT_SECONDS = 180.0
JUDGE_CONCURRENCY = 4
WORST_REPLY_COUNT = 8
REPLY_PREVIEW_WORDS = 30

#: One profile for every scenario: the difference we want to read is the
#: MESSAGE, so the user behind it is held constant.
PROFILE = OnboardingPreferences(
    profession="founder", needs=[OnboardingNeed.INBOX, OnboardingNeed.CALENDAR]
)

#: (label, note for the judge about what this scenario is testing, user turns).
#: Every scenario is ONE conversation; the turns are sent in order with a shared
#: conversation id so turn 2 is a follow-up, not a cold open.
SCENARIOS: list[tuple[str, str, list[str]]] = [
    (
        "small talk",
        "Pure chatting. Nothing to do, nothing to offer. A one-liner deserves a one-liner "
        "and absolutely no productivity pitch.",
        ["hey", "not much, long day"],
    ),
    (
        "factual q",
        "A general knowledge question and a follow-up about the same subject. Just answer it, "
        "short, and the follow-up should be read as being about Mongolia.",
        ["what's the capital of mongolia", "and population?"],
    ),
    (
        "check email (nothing connected)",
        "Gmail is NOT connected. The right move is to offer the connect link/card ONCE, in the "
        "same reply, and stop. Offering it twice or telling them to connect with nothing to tap "
        "are both failures.",
        ["can you check my email", "anything important in there?"],
    ),
    (
        "check email then declined",
        "Gmail is NOT connected and the user explicitly declines the connect offer. After 'not "
        "now' the offer must never be repeated, in this or any later reply.",
        ["can you check my email", "not now", "ok what else can you do without it"],
    ),
    (
        "reminder",
        "A concrete action. A reminder must ACTUALLY be created (a tool runs); describing one, "
        "or saying it is set when no tool ran, is the worst failure here.",
        ["remind me to call the dentist tomorrow at 10", "make it 10:30 actually"],
    ),
    (
        "todos",
        "A todo must actually be created, then the list actually read back. Both turns need a "
        "tool; a remembered list is a fabricated list.",
        ["add buy milk to my todos", "what's on my list"],
    ),
    (
        "plan my week (nothing connected)",
        "Nothing is connected, so there is no calendar to plan from. Be honest about that and "
        "give ONE next move, not a menu of everything GAIA could theoretically do.",
        ["plan my week", "just do what you can"],
    ),
    (
        "vent",
        "Emotional, not a task. This must NOT become a feature pitch. Listen, react, maybe ask "
        "if they want to talk or want help. Offering a workflow here is the failure.",
        ["i'm so behind on everything", "yeah it's just a lot right now"],
    ),
    (
        "out of scope",
        "GAIA cannot book flights. Say so plainly and briefly, without inventing a capability "
        "and without a consolation menu.",
        ["book me a flight to tokyo", "seriously? nothing?"],
    ),
    (
        "draft request",
        "Content creation mode: produce the actual three-line email, not a description of one "
        "and not a request for more detail first.",
        [
            "write a 3 line email declining a meeting politely",
            "make it a bit warmer",
        ],
    ),
    (
        "polite ending",
        "Conversation-closing messages. 'thanks' and 'ok cool' get a short human sign-off. "
        "Re-offering help or asking another question here is the failure.",
        ["what's the capital of mongolia", "thanks", "ok cool"],
    ),
    (
        "dangling yes",
        "A bare 'yes' with NOTHING pending. GAIA should say she is not sure what she is "
        "agreeing to, in one line, rather than inventing something to have offered.",
        ["yes", "sorry wrong chat"],
    ),
    (
        "what can you do",
        "The one place a capability list is allowed. Still short and concrete, still in her "
        "voice, not a brochure with headings.",
        ["what can you do", "ok and what needs connecting for that"],
    ),
    (
        "about yourself + follow-up on delivered content",
        "First a self-description (short, no 'I am an AI', no manifesto). Then a follow-up "
        "about content already in the thread, which must be answered FROM the thread rather "
        "than re-fetched or re-listed.",
        [
            "tell me about yourself",
            "list 4 things you'd take off my plate this week",
            "which of those matters most",
        ],
    ),
]


class Turn(BaseModel):
    """One GAIA reply plus the evidence she did a thing rather than talked about it."""

    message: str
    reply: str
    #: ``tool_name`` of every ``tool_data`` entry in the stream. A connect card
    #: arrives as ``integration_connection_required``; a created reminder as the
    #: reminder tool's own name.
    tools: list[str]


def _frame_tool_names(frame: dict) -> list[str]:
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
    """One comms turn against the running API, joined from its SSE frames."""
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
        "POST", f"{api_url}/api/v1/chat-stream", json=body, timeout=TURN_TIMEOUT_SECONDS
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
    reply = "".join(chunks).strip() or "[no text in stream]"
    delegated = "tool_calls_data" in tools
    if delegated:
        delivered, more_tools = await _await_delivery(client, api_url, conversation_id, message)
        if delivered:
            reply = reply + "\n\n[delivered later] " + delivered
            tools.extend(more_tools)
        else:
            reply = reply + "\n\n[nothing delivered within budget]"
    return Turn(message=message, reply=reply, tools=tools)


def _bot_messages_after(messages: list[dict], user_text: str) -> list[dict]:
    """Bot messages saved after the last user message equal to ``user_text``."""
    idx = None
    for i, m in enumerate(messages):
        if m.get("type") == "user" and (m.get("response") or "").strip() == user_text.strip():
            idx = i
    if idx is None:
        return []
    return [m for m in messages[idx + 1 :] if m.get("type") == "bot"]


async def _await_delivery(
    client: httpx.AsyncClient, api_url: str, conversation_id: str, user_text: str
) -> tuple[str, list[str]]:
    """Poll the saved conversation until the delegated answer lands (or the budget ends)."""
    deadline = time.monotonic() + DELIVERY_WAIT_SECONDS
    last_seen = ""
    while time.monotonic() < deadline:
        await asyncio.sleep(DELIVERY_POLL_SECONDS)
        try:
            resp = await client.get(
                f"{api_url}/api/v1/conversations/{conversation_id}", timeout=30.0
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        payload = resp.json()
        convo = payload.get("conversation", payload) if isinstance(payload, dict) else {}
        messages = convo.get("messages") or []
        bots = _bot_messages_after(messages, user_text)
        texts = [(m.get("response") or "").strip() for m in bots]
        delivered = [t for t in texts[1:] if t] if len(texts) > 1 else []
        tool_names = [
            t.get("tool_name")
            for m in bots
            for t in (m.get("tool_data") or [])
            if isinstance(t, dict)
        ]
        real_tools = [t for t in tool_names if t and t != "tool_calls_data"]
        if delivered and "\n".join(delivered) == last_seen:
            return last_seen, real_tools
        if delivered:
            last_seen = "\n".join(delivered)
        elif real_tools:
            return "", real_tools
    return last_seen, []


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40]


async def _provision(api_url: str, email: str) -> None:
    """A fresh Pro dev user carrying the shared onboarding profile."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        await client.post(f"{api_url}/api/v1/dev/users", json={"email": email, "name": "Alex"})
        # The API is paid-only: a turn from a free user is a 402 before it ever
        # reaches the agent.
        await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "scripts/grant_pro_access.py", "--email", email],
            check=True,
            capture_output=True,
        )
        await client.patch(
            f"{api_url}/api/v1/onboarding/preferences",
            headers={"X-Dev-User": email},
            json=PROFILE.model_dump(mode="json", exclude_none=True),
        )


#: 0/1 criteria, in report order. Key is the column header; value is the ask.
CRITERIA: dict[str, str] = {
    "a_human": (
        "Sounds like a person texting. Coherent sentences with a subject and a verb, a natural "
        'opener. Score 0 for "Great question", "Certainly!", "I\'m just an AI", "I can help '
        'with that", "Here\'s what I can do", for an em dash, or for stacked telegraphic '
        "fragments used as sentences."
    ),
    "b_length": (
        "Right length for the message received. A one-line message gets a one-line reply. Score "
        "0 for a paragraph answering 'hey' or 'thanks'. A request to WRITE something is the "
        "exception: there the full deliverable is correct and a stub is the failure."
    ),
    "c_does_it": (
        "Does the thing when it can. If the message names a concrete action or a lookup of the "
        "user's own data, a tool must actually have run this turn (see the tool list). Score 0 "
        "when the reply describes, promises, or narrates the action with no tool. Score 1 when "
        "the message needed no tool at all (chat, general knowledge, writing)."
    ),
    "d_one_move": (
        "When she cannot do it, she gives the ONE right next move, once, with the link or card "
        "in the same reply. Score 0 for telling the user to connect something with nothing to "
        "tap, for a menu of three alternatives where one move was needed, or for repeating an "
        "offer already made earlier in this conversation. Score 1 when she could do it."
    ),
    "e_invited": (
        "Suggests a productivity setup ONLY when the message invites it. Small talk, a vent, a "
        "thanks, or a general knowledge question must get NO list, no pitch, no connect card. "
        'A gentle one-line offer after acknowledging how they feel ("want to vent, or should I '
        'help lighten tomorrow?") is FINE and scores 1. Score 0 for a menu, a workflow idea, '
        "or a card on those messages."
    ),
    "f_no_reoffer": (
        "Does not re-offer something the user already declined or already has. Score 0 if an "
        "earlier turn in this conversation shows the user said no, not now, or already "
        "answered, and this reply raises it again."
    ),
    "g_leads_on": (
        "Leads somewhere. When the user is blocked (nothing connected, nothing to plan), the "
        'reply ends on the ONE concrete next step with its link or card ("want me to connect '
        'your calendar?" plus the card), never on a shrug. Never interrogates, never asks '
        "something she could answer herself or that was already answered, and never ends a "
        "closing message (thanks, ok cool) with a question. Score 1 when it either does the "
        "thing or leads to the one next step."
    ),
    "k_no_dash_no_leak": (
        "No em dash or en dash anywhere (hard 0). No leaked working notes: third person about "
        'the user ("I\'ll plan Alex\'s week"), "let me start by gathering context", names '
        "of internal machinery, or two drafts glued together in one reply (hard 0)."
    ),
    "h_formatting": (
        "Formatting fits the content. Prose when it is prose; bullets, headings, or bold only "
        "when there really are parallel items to scan. Score 0 for bullets or headings in a "
        "short conversational reply, and 0 for a wall of prose where a list was needed."
    ),
    "i_honest": (
        "Honest. Never claims to have done, sent, created, scheduled, or checked something that "
        "the tool list does not confirm, and never claims work is still running in the "
        "background. Score 0 for any such claim."
    ),
    "j_no_repeat": (
        "No repeated phrasing across this conversation. Score 0 if this reply reuses an opener, "
        "a sentence shape, or a stock line already used in an earlier reply above."
    ),
}


class _Verdict(BaseModel):
    """One reply's scores. Every field is 0 or 1; the schema forces all of them."""

    a_human: int
    b_length: int
    c_does_it: int
    d_one_move: int
    e_invited: int
    f_no_reoffer: int
    g_leads_on: int
    k_no_dash_no_leak: int
    h_formatting: int
    i_honest: int
    j_no_repeat: int


JUDGE_PROMPT = """\
You are grading ONE reply from GAIA, a personal AI assistant that talks to its user
like a sharp, warm friend who texts. The user is a founder on a paid plan. NOTHING
is connected yet: no Gmail, no calendar, no other integration.

Scenario: {label}
What this scenario is testing: {note}

The conversation SO FAR (earlier turns of the same thread):
{history}

The user's message on THIS turn:
  "{message}"

GAIA's reply on THIS turn:
  \"\"\"{reply}\"\"\"

Tools that actually ran on THIS turn: {tools}
(An empty list means nothing happened beyond text. A connect card shows up as a
tool named like integration_connection_required.)

Score each criterion 1 (met) or 0 (not met). Be strict: when in doubt, score 0.
Judge only THIS reply, but use the history to spot repetition and re-offers.
{criteria}"""


async def _judge(row: "Graded") -> _Verdict:
    criteria = "\n".join(f"- {key}: {text}" for key, text in CRITERIA.items())
    history = (
        "\n".join(f"  user: {t.message}\n  GAIA: {t.reply}" for t in row.history)
        or "  (this is the first turn)"
    )
    prompt = JUDGE_PROMPT.format(
        label=row.scenario,
        note=row.note,
        history=history,
        message=row.turn.message,
        reply=row.turn.reply,
        tools=", ".join(row.turn.tools) or "none",
        criteria=criteria,
    )
    return await ainvoke_llm(
        background_structured_runnable(_Verdict, temperature=0.0),
        prompt,
        label="chat_quality_judge",
        options=LLMInvokeOptions(max_attempts=2, timeout=JUDGE_TIMEOUT_SECONDS),
    )


class Graded(BaseModel):
    """A reply, what produced it, and its scores: one row of the report."""

    scenario: str
    note: str
    turn_number: int
    turn: Turn
    history: list[Turn] = []
    verdict: _Verdict | None = None


SUGGEST_PATTERNS = re.compile(
    r"\b(connect|link (?:your|it)|set (?:it|that|this) up|set up|hook (?:up|it)|"
    r"i can (?:set|wire|build)|workflow|automat|want me to)\b",
    re.IGNORECASE,
)


def _preview(reply: str) -> str:
    words = reply.split()
    return " ".join(words[:REPLY_PREVIEW_WORDS]) + (
        "..." if len(words) > REPLY_PREVIEW_WORDS else ""
    )


def _ends_with_question(reply: str) -> bool:
    return reply.rstrip().endswith("?")


def _words(reply: str) -> int:
    return len(reply.split())


async def run(api_url: str, only: str | None) -> None:
    collected: list[Graded] = []
    scenarios = [s for s in SCENARIOS if not only or only in s[0]]
    for index, (label, note, turns) in enumerate(scenarios):
        email = USER_TEMPLATE.format(slug=f"{index}-{_slug(label)}")
        print(f"\n\n######## {label}  ({email})")
        await _provision(api_url, email)
        conversation_id = str(uuid4())
        history: list[dict[str, str]] = []
        prior: list[Turn] = []
        async with httpx.AsyncClient(
            headers={"X-Dev-User": email}, cookies={"dev_bypass_user": email}
        ) as client:
            # The stream persists into an existing conversation; without this the
            # save 404s and the delegated answer has nowhere to land.
            await client.post(
                f"{api_url}/api/v1/conversations",
                json={"conversation_id": conversation_id, "description": label},
                timeout=30.0,
            )
            for turn_number, message in enumerate(turns, start=1):
                turn = await _send_turn(client, api_url, message, conversation_id, history)
                history.append({"role": "user", "content": message})
                history.append({"role": "assistant", "content": turn.reply})
                collected.append(
                    Graded(
                        scenario=label,
                        note=note,
                        turn_number=turn_number,
                        turn=turn,
                        history=list(prior),
                    )
                )
                prior.append(turn)
                print(f"  [t{turn_number}] user:  {message}")
                print(f"  [t{turn_number}] tools: {', '.join(turn.tools) or 'none'}")
                print(f"  [t{turn_number}] GAIA:  {_preview(turn.reply)}")

    print(f"\n\n######## judging {len(collected)} replies")
    await _grade_all(collected)
    print_report(collected)


async def _grade_all(collected: list[Graded]) -> None:
    """A judge that fails leaves ``verdict`` None: a provider blip is not a
    behavioural miss, and averaging it in as 0 would understate the prompt."""
    semaphore = asyncio.Semaphore(JUDGE_CONCURRENCY)

    async def grade(row: Graded) -> None:
        async with semaphore:
            try:
                row.verdict = await _judge(row)
            except Exception as e:
                print(f"  [judge failed] {row.scenario} t{row.turn_number}: {e!r}")

    await asyncio.gather(*(grade(row) for row in collected))
    ungraded = sum(1 for row in collected if row.verdict is None)
    if ungraded:
        print(f"  ungraded (judge failed): {ungraded}/{len(collected)}")


def print_report(graded: list[Graded]) -> None:
    if not graded:
        return
    keys = list(CRITERIA)

    print("\n\n======== per-reply scores")
    print(f"{'scenario':<38} t  " + " ".join(k[:1] for k in keys) + "   words  ?end  sugg")
    for row in graded:
        scores = row.verdict.model_dump() if row.verdict else {}
        cells = " ".join(str(scores.get(k, ".")) for k in keys)
        reply = row.turn.reply
        print(
            f"{row.scenario[:37]:<38} {row.turn_number}  {cells}   "
            f"{_words(reply):>5}  {'Y' if _ends_with_question(reply) else '.':>4}  "
            f"{'Y' if SUGGEST_PATTERNS.search(reply) else '.':>4}"
        )

    print("\n======== per-scenario rates")
    print(f"{'scenario':<38} {'replies':>7} {'score':>7} {'sugg%':>6} {'?end%':>6} {'avgwd':>6}")
    for label in dict.fromkeys(row.scenario for row in graded):
        rows = [r for r in graded if r.scenario == label]
        scored = [r for r in rows if r.verdict]
        met = sum(sum(r.verdict.model_dump().values()) for r in scored)
        total = len(scored) * len(keys)
        sugg = 100.0 * sum(bool(SUGGEST_PATTERNS.search(r.turn.reply)) for r in rows) / len(rows)
        qend = 100.0 * sum(_ends_with_question(r.turn.reply) for r in rows) / len(rows)
        avgwd = sum(_words(r.turn.reply) for r in rows) / len(rows)
        pct = f"{100.0 * met / total:5.0f}%" if total else "   n/a"
        print(f"{label[:37]:<38} {len(rows):>7} {pct:>7} {sugg:>5.0f}% {qend:>5.0f}% {avgwd:>6.0f}")

    print("\n======== totals per criterion")
    scored = [r for r in graded if r.verdict]
    for key in keys:
        met = sum(r.verdict.model_dump()[key] for r in scored)
        pct = 100.0 * met / len(scored) if scored else 0.0
        print(f"  {key:<16} {met:>3}/{len(scored):<3} {pct:5.1f}%")

    openers = [" ".join(r.turn.reply.split()[:3]).lower().strip(".,:") for r in graded]
    counts = Counter(openers)
    print(f"\n======== opener variety: {len(counts)}/{len(openers)} distinct")
    for opener, count in counts.most_common(5):
        if count > 1:
            print(f"  {count}x {opener!r}")

    worst = sorted(scored, key=lambda r: sum(r.verdict.model_dump().values()))[:WORST_REPLY_COUNT]
    print(f"\n======== worst {len(worst)} replies (verbatim)")
    for row in worst:
        scores = row.verdict.model_dump()
        failed = ", ".join(k for k, v in scores.items() if not v) or "none"
        print(
            f"\n--- {row.scenario} | turn {row.turn_number} | score {sum(scores.values())}/{len(keys)}"
        )
        print(f"    user:   {row.turn.message}")
        print(f"    tools:  {', '.join(row.turn.tools) or 'none'}")
        print(f"    failed: {failed}")
        print(f"    reply:  {row.turn.reply}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--only", default=None, help="Substring filter over scenario labels.")
    args = parser.parse_args()
    await run(args.api_url.rstrip("/"), args.only)


if __name__ == "__main__":
    asyncio.run(main())
