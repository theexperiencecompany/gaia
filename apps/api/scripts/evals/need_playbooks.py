#!/usr/bin/env python3
# mypy: ignore-errors -- dev eval script; typing not maintained here
"""
Does GAIA's first reply act on each Q2 pain the way its playbook says?

Not a test: it drives a REAL running API and a REAL model. One fresh Pro dev
user per need, carrying that need (and the role that unlocks it), sends the
exact opener the bots send after linking (``compose_first_message``), and the
reply is judged against the need's playbook: does it propose THAT job, does it
hand the connect to the executor when it talks about connecting, does it end on
an easy yes without narrating work that never ran.

Usage (from apps/api/, with the worktree API already running):

    uv run python scripts/evals/need_playbooks.py --api-url http://localhost:9330
    uv run python scripts/evals/need_playbooks.py --only student,inbox
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from pydantic import BaseModel

from app.agents.prompts.new_user_prompts import NEED_PLAYBOOKS
from app.models.user_models import OnboardingNeed, OnboardingPreferences, role_of_need
from app.services.onboarding.first_message import compose_first_message
from scripts.evals.core.dev_users import dev_client, provision
from scripts.evals.core.judge import judge
from scripts.evals.core.live_chat import Turn, TurnOptions, send_turn

DEFAULT_API_URL = os.environ.get("GAIA_API_URL", "http://localhost:9330")
RUN_ID = time.strftime("%H%M%S")
USER_TEMPLATE = "np-{slug}-" + RUN_ID + "@gaia.local"
#: The role a shared need is evaluated under; any listed role would do.
SHARED_ROLE = "founder"
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


class _Verdict(BaseModel):
    proposes_the_job: int
    easy_yes: int
    no_narration: int
    short: int
    note: str


class Graded(BaseModel):
    need: OnboardingNeed
    role: str
    opener: str
    turn: Turn
    mentions_connecting: bool
    has_connect_card: bool
    verdict: _Verdict | None = None


JUDGE_PROMPT = """\
You are grading GAIA's FIRST reply to a brand-new paid user. Nothing is connected
yet (no Gmail, no Calendar, no other tool). GAIA knows two things: the user's role
and the one pain they picked during onboarding.

The pain, and the playbook GAIA was given for it:
  {playbook}

The user's opener (sent automatically after linking):
  "{opener}"

GAIA's reply:
  \"\"\"{reply}\"\"\"

Tools that actually ran on this turn: {tools}
(A connect card shows up as integration_connection_required. An empty list means
nothing happened beyond text.)

Score 1 or 0, strictly:
- proposes_the_job: the reply proposes the specific job in the playbook (not a
  generic "I can help with lots of things", not a different job), in a way a
  person could say yes to.
- easy_yes: ends on one clear yes/no question or one clear next step; not a menu
  of questions, not an interrogation about their life.
- no_narration: nothing is described as done, started, running or "on it"
  unless a tool in the list actually did it.
- short: at most ~90 words, reads like a text, no headings or bullet lists.
note: one line on the biggest problem, or "fine".
"""


async def _one(api_url: str, need: OnboardingNeed) -> Graded:
    role = role_of_need(need) or SHARED_ROLE
    prefs = OnboardingPreferences(profession=role, needs=[need])
    email = USER_TEMPLATE.format(slug=need.value.replace("_", "-"))
    await provision(api_url, email, prefs)
    opener = compose_first_message(prefs)
    conversation_id = str(uuid4())
    async with dev_client(email) as client:
        await client.post(
            f"{api_url}/api/v1/conversations",
            json={"conversation_id": conversation_id, "description": "need playbook eval"},
            timeout=30.0,
        )
        turn = await send_turn(client, api_url, opener, conversation_id, [], TURN_OPTIONS)
    lowered = turn.reply.lower()
    return Graded(
        need=need,
        role=role,
        opener=opener,
        turn=turn,
        mentions_connecting="connect" in lowered,
        has_connect_card=any(name in turn.tools for name in CONNECT_TOOLS),
    )


async def _judge(row: Graded) -> _Verdict:
    prompt = JUDGE_PROMPT.format(
        playbook=NEED_PLAYBOOKS[row.need],
        opener=row.opener,
        reply=row.turn.reply,
        tools=", ".join(row.turn.tools) or "none",
    )
    return await judge(
        _Verdict, prompt, label="need_playbooks_judge", timeout=JUDGE_TIMEOUT_SECONDS
    )


def _report(rows: list[Graded]) -> None:
    cols = ("proposes_the_job", "easy_yes", "no_narration", "short", "card_ok")
    print("\n======== need playbooks: first reply per Q2 pick\n")
    print(f"{'need':<28} {'role':<11} " + " ".join(f"{c[:8]:>8}" for c in cols))
    totals = dict.fromkeys(cols, 0)
    for row in rows:
        card_ok = int(row.has_connect_card or not row.mentions_connecting)
        scores = (
            *(getattr(row.verdict, c) if row.verdict else 0 for c in cols[:-1]),
            card_ok,
        )
        for c, s in zip(cols, scores, strict=True):
            totals[c] += s
        print(f"{row.need.value:<28} {row.role:<11} " + " ".join(f"{s:>8}" for s in scores))
    print(f"\n{'TOTAL /' + str(len(rows)):<40} " + " ".join(f"{totals[c]:>8}" for c in cols))
    print("\n---- replies\n")
    for row in rows:
        flag = "" if row.verdict and all(getattr(row.verdict, c) for c in cols[:-1]) else " <-- "
        print(f"[{row.need.value}] {row.role}{flag}")
        print(f"  opener: {row.opener}")
        print(f"  tools:  {', '.join(row.turn.tools) or 'none'}")
        print(f"  note:   {row.verdict.note if row.verdict else 'unjudged'}")
        print("  reply:  " + row.turn.reply.replace("\n", "\n          ")[:900])
        print()


async def run(api_url: str, only: str | None) -> None:
    needs = list(OnboardingNeed)
    if only:
        keys = [k.strip() for k in only.split(",") if k.strip()]
        needs = [n for n in needs if any(k in n.value for k in keys)]
    rows: list[Graded] = []
    for need in needs:
        print(f"... {need.value}", flush=True)
        rows.append(await _one(api_url, need))
    for row in rows:
        row.verdict = await _judge(row)
    _report(rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--only", default=None, help="Comma-separated substrings of need values.")
    args = parser.parse_args()
    await run(args.api_url.rstrip("/"), args.only)


if __name__ == "__main__":
    asyncio.run(main())
