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

`--follow` takes each chip of the first three personas and sends it as the
user's next message to the LOCALLY RUNNING API, so you can read GAIA's actual
reply and judge whether a chip leads anywhere concrete. It needs `mise dev
--agent` (or any boot with `DEV_AUTH_BYPASS_EMAIL` set); it mints one dev user per
persona, which must be able to pass the paid-only gate.
"""

import argparse
import asyncio
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

from app.models.user_models import OnboardingNeed, OnboardingPreferences
import app.services.onboarding.first_question as first_question_module
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


def _reporting_validate(question: str, chips: list[str], preferences: OnboardingPreferences):
    """The validator, plus a line on stdout when it rejects: the wide event carries
    the reason as a field the console format does not print."""
    rejection = first_question_module.validate_draft(question, chips, preferences)
    if rejection is not None:
        print(f"  rejected ({rejection.reason}): {question!r} {chips}")
    return rejection


async def run_personas(timeout_seconds: float) -> list[tuple[str, object]]:
    """One model call per persona, concurrently — they share nothing."""
    first_question_module.validate_draft = _reporting_validate  # type: ignore[assignment]
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
        print(f"  question: {result.question}")
        print(f"  chips:    {result.chips}")
    print(f"\nfallbacks: {fallbacks}/{len(rows)}")


async def _send_turn(client: httpx.AsyncClient, api_url: str, message: str) -> str:
    """One comms turn against the running API, joined from its SSE frames."""
    body = {
        "message": message,
        "messages": [{"role": "user", "content": message}],
        "conversation_id": str(uuid4()),
        "turn_id": str(uuid4()),
    }
    chunks: list[str] = []
    async with client.stream(
        "POST", f"{api_url}/api/v1/chat-stream", json=body, timeout=FOLLOW_TIMEOUT_SECONDS
    ) as response:
        if response.status_code != 200:
            await response.aread()
            return f"[HTTP {response.status_code}] {response.text[:300]}"
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                frame = json.loads(line[len("data: ") :])
            except json.JSONDecodeError:
                continue
            if isinstance(frame, dict) and isinstance(frame.get("response"), str):
                chunks.append(frame["response"])
    return "".join(chunks).strip() or "[no text in stream]"


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


async def run_follow(rows: list[tuple[str, object]], api_url: str) -> None:
    """Each chip of the first personas, replayed as the user's next message.

    Every persona gets its own minted dev user, so one persona's threads can
    never surface in another's reply.
    """
    for index, (label, result) in enumerate(rows[:FOLLOW_PERSONA_COUNT]):
        print(f"\n\n######## follow: {label}")
        if result is None:
            print("  skipped (no question was composed)")
            continue
        email = FOLLOW_USER_TEMPLATE.format(slug=f"{index}-{_slug(label)}")
        await _provision(api_url, email, PERSONAS[index][1])
        print(f"  user: {email}")
        print(f"  question: {result.question}")
        async with httpx.AsyncClient(
            headers={"X-Dev-User": email}, cookies={"dev_bypass_user": email}
        ) as client:
            for chip in result.chips:
                reply = await _send_turn(client, api_url, chip)
                print(f"\n  --- chip: {chip}")
                print(f"  GAIA: {_preview(reply)}")


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
    args = parser.parse_args()

    rows = await run_personas(args.timeout)
    print_personas(rows)
    if args.follow:
        await run_follow(rows, args.api_url.rstrip("/"))


if __name__ == "__main__":
    asyncio.run(main())
