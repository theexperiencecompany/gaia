"""Drive every analytics journey on a local sim stack, then assert what reached the gaia-test project.

For each journey the expected events must arrive exactly once, on the run
user's Mongo id, with valid catalog properties, the right actor/trigger/surface
and, for browser requests, the browser's $session_id; any other event is a
failure. PostHog is polled until the expected set is complete and stable.
`mise analytics:e2e` boots the stack with POSTHOG_PROJECT_TOKEN set to the
gaia-test token, so nothing reaches the dev or prod project.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
import time

from pydantic import ValidationError

from app.constants.chat import ConversationSource
from shared.py.analytics.catalog import CATALOG
from shared.py.analytics.catalog.agents import AgentRunCompleted, AgentRunStarted
from shared.py.analytics.catalog.attribution import Actor, Attribution, EntrySurface, Trigger
from shared.py.analytics.catalog.auth import UserActive, UserLoggedIn, UserLoggedOut, UserSignedUp
from shared.py.analytics.catalog.billing import (
    PaymentSucceeded,
    PaywallBlocked,
    SubscriptionActivated,
)
from shared.py.analytics.catalog.bots import BotChatCompleted, BotChatStarted, BotMessageReceived
from shared.py.analytics.catalog.chat import (
    ChatConversationCreated,
    ChatConversationRenamed,
    ChatMessageCompleted,
    ChatMessageSubmitted,
)
from shared.py.analytics.catalog.onboarding import OnboardingCompleted, OnboardingPhaseCompleted
from shared.py.analytics.catalog.workflows import WorkflowCreated, WorkflowExecuted
from shared.py.analytics.context import POSTHOG_SESSION_PROPERTY

from . import e2e_journeys as journeys
from .mongo import ground_truth_db
from .posthog_api import (
    ENVELOPE_PROPERTIES,
    TARGETS,
    PostHogReader,
    TargetName,
    hogql_complete,
    reader,
)

DEFAULT_EMAIL = "analytics-e2e@gaia.local"
DEFAULT_TIMEOUT_S = 300
POLL_INTERVAL_S = 10
SDK_PREFIX = "$"
# user:active is stamped at the start of the IST day, up to a day before the run.
LOOKBACK = timedelta(days=1)
EXIT_NOT_ASSERTED = 2

BROWSER = Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.WEB)
WEBHOOK = Attribution(actor=Actor.AGENT, trigger=Trigger.WEBHOOK, surface=EntrySurface.WORKER)
BOT = Attribution(actor=Actor.USER, trigger=Trigger.INTERACTIVE, surface=EntrySurface.BOT)

RUN_EVENTS_HOGQL = (
    "SELECT toString(uuid), event, distinct_id, toString(timestamp), properties FROM events "
    "WHERE timestamp >= toDateTime({since}, 'UTC') "
    "AND (distinct_id = {user} OR properties.$session_id = {session}) "
    "ORDER BY timestamp LIMIT {limit}"
)
STRAY_EVENTS_HOGQL = (
    "SELECT event, distinct_id, count() FROM events "
    "WHERE timestamp >= toDateTime({since}, 'UTC') AND distinct_id != {user} "
    "AND NOT startsWith(event, '$') "
    "GROUP BY event, distinct_id LIMIT {limit}"
)

# Journeys a dev-bypass stack cannot reach, and why; printed on every run, never silently skipped.
NOT_DRIVABLE = (
    f"{UserSignedUp.event}: /dev/users mints through store_user_info with external side "
    "effects off; only the WorkOS callback emits it",
    f"{UserLoggedIn.event}: emitted only by the WorkOS callbacks, which need a real code exchange",
    f"{UserLoggedOut.event}: POST /user/logout needs a sealed WorkOS session cookie",
    "ai:llm_call_completed: the sim stub reports zero tokens, and one-shot calls skip zero usage; "
    "the ledger row is asserted in Mongo instead",
)


# Compared by identity: two journeys may expect the same event, and each needs its own slot.
@dataclass(frozen=True, eq=False)
class Expect:
    """One event a journey must produce exactly count times."""

    event: str
    attribution: Attribution | None
    in_browser_session: bool
    where: tuple[tuple[str, object], ...] = ()
    count: int = 1

    def matches(self, received: Received) -> bool:
        """Whether received is this event, discriminated by where."""
        return received.event == self.event and all(
            received.properties.get(key) == value for key, value in self.where
        )

    def label(self) -> str:
        """Return the event and its discriminator."""
        where = ", ".join(f"{key}={value}" for key, value in self.where)
        return f"{self.event}" + (f" [{where}]" if where else "")


@dataclass(frozen=True)
class Received:
    """One event as PostHog stored it."""

    uuid: str
    event: str
    distinct_id: str
    timestamp: str
    properties: dict[str, object]


@dataclass(frozen=True)
class Journey:
    """A user journey: how to drive it and what it must emit."""

    name: str
    drive: Callable[[journeys.Stack], None]
    expects: tuple[Expect, ...]


@dataclass
class Verdict:
    """Every failure the run found, grouped for the report."""

    failures: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        """Record one failure."""
        self.failures.append(message)


def _agent_turn(attribution: Attribution, in_session: bool, source: str) -> tuple[Expect, ...]:
    """Return what one agent turn emits after its submit: the conversation, the run, the completion."""
    surface = (("surface", attribution.surface.value),)
    return (
        Expect(ChatConversationCreated.event, attribution, in_session, surface),
        Expect(AgentRunStarted.event, attribution, in_session, surface),
        Expect(AgentRunCompleted.event, attribution, in_session, surface),
        Expect(ChatMessageCompleted.event, attribution, in_session, (("source", source),)),
    )


def build_journeys(transcript: Path) -> list[Journey]:
    """Return the journeys in the order they must run: paid routes need the payment first."""
    web = ConversationSource.WEB.value
    telegram = ConversationSource.TELEGRAM.value
    browser_surface = (("surface", BROWSER.surface.value),)
    return [
        Journey("signup", journeys.mint, ()),
        Journey(
            "onboarding",
            journeys.onboarding,
            (
                Expect(OnboardingCompleted.event, BROWSER, True),
                Expect(OnboardingPhaseCompleted.event, BROWSER, True),
                Expect(UserActive.event, BROWSER, True),
                # Onboarding opens the user's first conversation.
                Expect(ChatConversationCreated.event, BROWSER, True, browser_surface),
            ),
        ),
        Journey("paywall", journeys.paywall, (Expect(PaywallBlocked.event, BROWSER, True),)),
        Journey(
            "payment webhook",
            journeys.payment,
            (
                Expect(SubscriptionActivated.event, WEBHOOK, False),
                Expect(PaymentSucceeded.event, WEBHOOK, False),
            ),
        ),
        Journey(
            "web chat turn",
            journeys.chat,
            (
                Expect(ChatMessageSubmitted.event, BROWSER, True, (("source", web),)),
                Expect(ChatConversationRenamed.event, BROWSER, True),
                *_agent_turn(BROWSER, True, web),
            ),
        ),
        Journey(
            "workflow",
            journeys.workflow,
            (
                Expect(WorkflowCreated.event, BROWSER, True),
                Expect(WorkflowExecuted.event, BROWSER, True),
            ),
        ),
        Journey(
            "bot message",
            lambda stack: journeys.bot(stack, transcript),
            (
                Expect(ChatMessageSubmitted.event, BOT, False, (("source", telegram),)),
                *_agent_turn(BOT, False, telegram),
                Expect(BotMessageReceived.event, None, False),
                Expect(BotChatStarted.event, None, False),
                Expect(BotChatCompleted.event, None, False),
            ),
        ),
    ]


def _properties(raw: object) -> dict[str, object]:
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, dict):
        raise TypeError(f"event properties are not an object: {type(parsed)}")
    return parsed


def fetch(read: PostHogReader, stack: journeys.Stack, since: datetime) -> list[Received]:
    """Return every event on the run's user or browser session since since."""
    rows = hogql_complete(
        read,
        RUN_EVENTS_HOGQL,
        {
            "since": (since - LOOKBACK).strftime("%Y-%m-%d %H:%M:%S"),
            "user": stack.owner().distinct_id,
            "session": stack.session_id,
        },
    )
    return [
        Received(str(uuid), str(event), str(distinct_id), str(timestamp), _properties(properties))
        for uuid, event, distinct_id, timestamp, properties in rows
    ]


def assign(
    expects: list[Expect], received: list[Received]
) -> tuple[dict[Expect, list[Received]], list[Received]]:
    """Give each received catalog event to the expectation it matches; the rest are unexpected."""
    assigned: dict[Expect, list[Received]] = {expect: [] for expect in expects}
    unexpected: list[Received] = []
    for event in received:
        if event.event.startswith(SDK_PREFIX):
            continue
        candidates = [expect for expect in expects if expect.matches(event)]
        if not candidates:
            unexpected.append(event)
            continue
        # Identical expectations in two journeys fill in order; a surplus lands on the first.
        open_slots = [expect for expect in candidates if len(assigned[expect]) < expect.count]
        assigned[(open_slots or candidates)[0]].append(event)
    return assigned, unexpected


def poll(
    read: PostHogReader,
    stack: journeys.Stack,
    since: datetime,
    expects: list[Expect],
    timeout_s: int,
) -> list[Received]:
    """Poll until every expectation has arrived and two polls in a row return the same events."""
    deadline = time.monotonic() + timeout_s
    previous: set[str] | None = None
    while True:
        received = fetch(read, stack, since)
        assigned, _ = assign(expects, received)
        complete = all(len(assigned[expect]) >= expect.count for expect in expects)
        uuids = {event.uuid for event in received}
        if complete and uuids == previous:
            return received
        if time.monotonic() >= deadline:
            print(f"ingestion timeout after {timeout_s}s; asserting what arrived")
            return received
        previous = uuids if complete else None
        time.sleep(POLL_INTERVAL_S)


def property_failures(event: Received, expect: Expect, stack: journeys.Stack) -> list[str]:
    """Return what is wrong with one received event: identity, catalog shape, attribution, session."""
    failures: list[str] = []
    if event.distinct_id != stack.owner().distinct_id:
        failures.append(f"distinct_id {event.distinct_id!r}, expected the user's Mongo id")
    model = CATALOG[event.event]
    base = model.base_properties.model_fields.keys() if model.base_properties else set()
    custom = {
        key: value
        for key, value in event.properties.items()
        if not key.startswith(SDK_PREFIX) and key not in ENVELOPE_PROPERTIES
    }
    undeclared = custom.keys() - model.model_fields.keys() - base
    if undeclared:
        failures.append(f"properties not in the catalog: {sorted(undeclared)}")
    try:
        model.model_validate({key: custom[key] for key in model.model_fields if key in custom})
    except ValidationError as error:
        failures.append(f"catalog validation: {error.errors(include_url=False)}")
    attribution = {key: custom.get(key) for key in base}
    if expect.attribution is None and attribution:
        failures.append(f"unexpected attribution {attribution}")
    if expect.attribution is not None and attribution != expect.attribution.model_dump(mode="json"):
        failures.append(
            f"attribution {attribution}, expected {expect.attribution.model_dump(mode='json')}"
        )
    session = event.properties.get(POSTHOG_SESSION_PROPERTY)
    if expect.in_browser_session and session != stack.session_id:
        failures.append(f"$session_id {session!r}, expected the browser's {stack.session_id!r}")
    if not expect.in_browser_session and session is not None:
        failures.append(f"$session_id {session!r} on an event no browser caused")
    return failures


def judge(
    journey_list: list[Journey],
    received: list[Received],
    strays: list[list[object]],
    stack: journeys.Stack,
    verdict: Verdict,
) -> None:
    """Print one line per expectation and record every failure."""
    expects = [expect for journey in journey_list for expect in journey.expects]
    assigned, unexpected = assign(expects, received)
    for journey in journey_list:
        print(f"\n{journey.name}")
        for expect in journey.expects:
            got = assigned[expect]
            problems = (
                []
                if len(got) == expect.count
                else [f"arrived {len(got)}x, expected {expect.count}x"]
            )
            problems += [
                problem for event in got for problem in property_failures(event, expect, stack)
            ]
            print(f"  {'ok' if not problems else 'XX'} {expect.label()}")
            for problem in problems:
                print(f"       {problem}")
                verdict.fail(f"{journey.name}: {expect.label()}: {problem}")
    for event in unexpected:
        verdict.fail(f"unexpected {event.event} at {event.timestamp} on {event.distinct_id}")
    for name, distinct_id, count in strays:
        verdict.fail(f"unexpected {name} x{count} on another distinct_id {distinct_id!r}")
    sdk = sum(1 for event in received if event.event.startswith(SDK_PREFIX))
    print(f"\n{sdk} SDK/person-operation events ($set, $ai_*, ...) seen and not asserted")


def ledger_failures(stack: journeys.Stack, since: datetime) -> list[str]:
    """Return a failure unless the chat turn wrote at least one llm_calls ledger row."""
    rows = ground_truth_db().llm_calls.count_documents(
        {"user_id": stack.owner().distinct_id, "created_at": {"$gte": since}}
    )
    print(f"\nLLM ledger\n  {'ok' if rows else 'XX'} llm_calls rows for the run user: {rows}")
    return [] if rows else ["LLM ledger: the chat turn wrote no llm_calls row"]


def run(args: argparse.Namespace) -> int:
    """Drive the journeys, then assert them against gaia-test."""
    target = TARGETS[TargetName.E2E]
    read: PostHogReader | None = None
    if not args.no_assert:
        read = reader(target)
        if read.project()["api_token"] != os.environ.get(target.token_env):
            raise SystemExit(f"{target.token_env} is not the token of the gaia-test project")
    stack = journeys.Stack(api_url=args.api_url, email=args.email)
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory() as scratch:
        journey_list = build_journeys(Path(scratch) / "bot-transcript.jsonl")
        for journey in journey_list:
            print(f"driving {journey.name}")
            journey.drive(stack)
    print(
        f"user {stack.owner().distinct_id}, browser session {stack.session_id}, from {started:%H:%M:%S}Z"
    )
    verdict = Verdict()
    verdict.failures += ledger_failures(stack, started)
    for line in NOT_DRIVABLE:
        print(f"NOT COVERED {line}")
    if read is None:
        print("--no-assert: journeys driven, nothing asserted")
        return EXIT_NOT_ASSERTED
    expects = [expect for journey in journey_list for expect in journey.expects]
    received = poll(read, stack, started, expects, args.timeout)
    strays = hogql_complete(
        read,
        STRAY_EVENTS_HOGQL,
        {"since": started.strftime("%Y-%m-%d %H:%M:%S"), "user": stack.owner().distinct_id},
    )
    judge(journey_list, received, strays, stack, verdict)
    print(f"\n{len(verdict.failures)} failure(s)")
    return 1 if verdict.failures else 0


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the e2e command."""
    command = sub.add_parser("e2e", help=__doc__, description=__doc__)
    command.add_argument(
        "--api-url",
        default=os.environ.get(
            "GAIA_API_URL", f"http://localhost:{os.environ.get('API_PORT', '8000')}"
        ),
        help="the local API the journeys drive",
    )
    command.add_argument("--email", default=DEFAULT_EMAIL, help="the dev user each run recreates")
    command.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="ingestion wait, seconds"
    )
    command.add_argument(
        "--no-assert",
        action="store_true",
        help=f"drive the journeys without a personal key and assert nothing (exits {EXIT_NOT_ASSERTED})",
    )
    command.set_defaults(run=run)
