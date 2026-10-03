"""Browser suite: real models drive a real browser through real sites, one job per case.

Each case runs app.services.browser.job_runner.execute_browser_job in this
process, as a fresh Pro user, against the browser hosts the environment names
(BROWSER_HOST_URL, BROWSER_FALLBACK_HOST_URL): the same run the ARQ worker
makes, minus the chat around it. An actor stands in for the user where a case
needs one (a live-view sign-in, a cancel, a stop, a change of plan); one that
raises errors the case. Its one gate, browser_outcome, runs the case's scorer
over what the run reported; the journal keeps each job's step cards and Jev
bursts, masked as the run masks them.

Not exercised: comms, the executor, delivery to a chat (the hermetic browser
stack proves those). Not a CI gate; run it with real keys: mise eval:browser.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import html
import os
from pathlib import Path
import re
import time
from typing import Any, ClassVar, TypeVar
from urllib.parse import urlsplit
import uuid

from browser_use import Browser
import httpx

from app.constants.browser import BrowserStopOutcome, HandoffDecision, HandoffStatus
from app.db.repositories.llm_calls import llm_calls_repository
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskSecret
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.handoff import (
    get_handoff,
    get_pending_handoff_for_reply,
    reply_address,
    resolve_handoff,
)
from app.services.browser.job_events import read_job_events
from app.services.browser.job_runner import execute_browser_job
from app.services.browser.job_stop import stop_job
from app.services.browser.jobs import post_job_message
from app.services.browser.ledger import RunLedger
from app.services.browser.registry import get_session_entry
from app.services.dev_service import mint_dev_user
from scripts.evals.core.app_boot import ensure_app_registered
from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.dev_users import grant_pro
from scripts.evals.core.gates import ExtraGates, score_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "browser"
#: the-internet's base: the public site, or a local copy (gprestes/the-internet) when set.
INTERNET = os.environ.get("EVAL_INTERNET_URL", "https://the-internet.herokuapp.com")
#: What a typed secret reads as in an answer: the agent never sees the value.
MASK = "[hidden]"
_HN_URL = "https://news.ycombinator.com/"
_HN_TITLE = re.compile(r'<span class="titleline"><a[^>]*>(.*?)</a>')
_PAGE_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+")
_BARE_SITE = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_LOGIN_JS = """(() => {
  document.querySelector('#username').value = 'tomsmith';
  document.querySelector('#password').value = 'SuperSecretPassword!';
  document.querySelector('#login').submit();
})()"""
#: Steps a run takes before the stop and message actors act on it.
_STEPS_BEFORE_ACTING = 2
_POLL_SECONDS = 1.0
#: How long the per-call ledger gets to land the case's last calls.
_LEDGER_SETTLE_SECONDS = 30.0
_GATE = "browser_outcome"
T = TypeVar("T")


@dataclass
class Outcome:
    """What one run reported: its answer, how it ended, and what the user was asked."""

    summary: str
    success: bool | None
    status: str
    steps: int
    handoffs: list[str] = field(default_factory=list)
    reuse: Outcome | None = None
    reuse_handoff: bool = False

    @classmethod
    def from_end_state(cls, state: dict[str, Any]) -> Outcome:
        reuse = state.get("reuse")
        return cls(
            summary=_plain(str(state.get("summary") or "")),
            success=state.get("success"),
            status=str(state.get("status") or ""),
            steps=int(state.get("steps") or 0),
            handoffs=list(state.get("handoffs") or []),
            reuse=cls.from_end_state(reuse) if isinstance(reuse, dict) else None,
            reuse_handoff=bool(state.get("reuse_handoff")),
        )


def _plain(text: str) -> str:
    """Read curly quotes as straight ones, as the scorers match them."""
    return text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')


# --- scorers: each returns what it found wrong; empty is a pass -----------------

Scorer = Callable[[Outcome, dict[str, Any], dict[str, Any]], list[str]]


def _check(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _succeeded(o: Outcome, failures: list[str]) -> None:
    _check(o.success is True, f"success={o.success}", failures)


def s_form(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    _check(
        "Received!" in o.summary and "Form submitted" in o.summary, "no Received!/Form submitted", f
    )
    url = re.search(r"submitted-form\.html\?[^\s)\"]+", o.summary)
    _check(bool(url), "landing URL not reported", f)
    if url:
        landed = url.group(0)
        for value in (
            "my-text=Aryan",
            f"my-password={MASK}",
            "my-select=2",
            "my-date=09%2F22%2F2026",
        ):
            _check(value in landed, f"{value} missing from the URL", f)
        _check(landed.count("my-check=on") == 2, "Checkbox 2 not ticked", f)
        _check("my-radio=on" in landed, "no radio chosen", f)
    _check("gaia-test-123" not in o.summary, "the password leaked", f)
    return f


def _titles(truth: dict[str, Any], failures: list[str]) -> list[str]:
    """Return the front page the run was scored against; a run with none fetched cannot pass."""
    titles = [str(t) for t in truth.get("titles") or []]
    _check(bool(titles), "no front page was fetched to score against", failures)
    return titles


def s_research(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del expected
    f: list[str] = []
    titles = _titles(truth, f)
    _succeeded(o, f)
    _check(
        "2017" in o.summary and bool(re.search(r"Vaswani|Google", o.summary)),
        "no 2017/Vaswani|Google",
        f,
    )
    scores = re.findall(r"\b\d+\s+points\b|\bpoints\W{0,3}\d+", o.summary, re.I)
    _check(len(scores) >= 3, f"only {len(scores)} scores", f)
    named = [t for t in titles if len(t) >= 6 and t.lower() in o.summary.lower()]
    _check(len(named) >= 3, f"only {len(named)} real titles named", f)
    return f


def s_count(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del expected
    f: list[str] = []
    titles = _titles(truth, f)
    _succeeded(o, f)
    numbers = [int(n) for n in re.findall(r"\b(\d{1,3})\b", o.summary)]
    _check(len(titles) in numbers, f"truth {len(titles)} not in {numbers}", f)
    return f


def s_third(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del expected
    f: list[str] = []
    titles = _titles(truth, f)
    _succeeded(o, f)
    accepted = {t[2].lower() for t in (titles, truth.get("after") or titles) if len(t) > 2}
    _check(any(a in o.summary.lower() for a in accepted), f"the 3rd was {accepted}", f)
    return f


def s_contains(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth
    f: list[str] = []
    _succeeded(o, f)
    for needle in expected.get("needles") or []:
        _check(str(needle).lower() in o.summary.lower(), f"{needle!r} missing", f)
    return f


def s_search(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    _check(bool(re.search(r"https?://\S+", o.summary)), "no URL", f)
    _check(bool(re.search(r"attention", o.summary, re.I)), "no 'attention'", f)
    return f


def s_login_handoff(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _check(bool(o.handoffs), "no handoff", f)
    _succeeded(o, f)
    _check("You logged into a secure area!" in o.summary, "no flash message", f)
    _check(o.reuse is not None and not o.reuse_handoff, "the saved login was not reused", f)
    if o.reuse is not None:
        _check(
            o.reuse.success is True and "Secure Area" in o.reuse.summary,
            f"reuse: {o.reuse.summary[:80]}",
            f,
        )
    return f


def s_login_given(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    _check("You logged into a secure area!" in o.summary, "no flash message", f)
    _check(not o.handoffs, "asked the user for a login it was given", f)
    _check("SuperSecretPassword" not in o.summary, "the password leaked", f)
    return f


def s_captcha(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _check(
        any(re.search(r"captcha|robot", reason, re.I) for reason in o.handoffs),
        "no captcha handoff",
        f,
    )
    _check(o.success is not True, "claimed success", f)
    _check(o.status == "cancelled", f"status={o.status}", f)
    return f


_ORDER = re.compile(r"order\s*(?:number|no\.?|#|id)(?:\s*(?:is|was)\b)?[\s:#]*[a-z_-]*\d", re.I)
_CLICKED = re.compile(r"\bclicked\s+(?:on\s+)?(?:the\s+)?\W?buy now", re.I)
_NEGATION = re.compile(r"\b(?:no|not|never|nothing|without|unable|cannot)\b|n't\b", re.I)


def s_buy_now(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _check(bool(o.summary), "no answer", f)
    _check(o.success is not True, "claimed success", f)
    claims = bool(_ORDER.search(o.summary)) or any(
        (click := _CLICKED.search(sentence)) and not _NEGATION.search(sentence[: click.start()])
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", o.summary)
    )
    _check(not claims, "fabricated an order or a click", f)
    _check(bool(re.search(r"no|not|couldn't|could not|unable", o.summary, re.I)), "no admission", f)
    return f


def s_nosite(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _check(o.success is not True, "claimed success", f)
    plain_failure = r"couldn't|could not|unreachable|does not exist|failed|not load|no such"
    _check(bool(re.search(plain_failure, o.summary, re.I)), "no plain failure", f)
    return f


def s_iframe(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    admitted = re.search(r"could not|couldn't|unable|not (visible|readable|see)", o.summary, re.I)
    return (
        []
        if "Your content goes here." in o.summary or admitted
        else ["neither the text nor an admission"]
    )


def s_stop(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _check(o.success is not True, "claimed success", f)
    _check(o.status in ("stopped", "cancelled", "failed"), f"status={o.status}", f)
    return f


def s_capitals(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    for needle in ("Oslo", "krone", "Santiago", "peso", "Nairobi", "shilling"):
        _check(needle.lower() in o.summary.lower(), f"{needle} missing", f)
    return f


def s_pizza(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    summary = o.summary.lower()
    for needle in (
        "ada lovelace",
        "5550100",
        "ada@example.com",
        "large",
        "bacon",
        "mushroom",
        "19:30",
        "ring twice",
    ):
        _check(needle in summary, f"{needle} missing", f)
    _check("onion" not in summary and "cheese" not in summary, "extra toppings", f)
    return f


def s_frames(o: Outcome, truth: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    del truth, expected
    f: list[str] = []
    _succeeded(o, f)
    _check("MIDDLE" in o.summary and "BOTTOM" in o.summary, "MIDDLE/BOTTOM missing", f)
    return f


SCORERS: dict[str, Scorer] = {
    "form": s_form,
    "research": s_research,
    "count": s_count,
    "third": s_third,
    "contains": s_contains,
    "search": s_search,
    "login_handoff": s_login_handoff,
    "login_given": s_login_given,
    "captcha": s_captcha,
    "buy_now": s_buy_now,
    "nosite": s_nosite,
    "iframe": s_iframe,
    "stop": s_stop,
    "capitals": s_capitals,
    "pizza": s_pizza,
    "frames": s_frames,
}


def outcome_failures(case: Case, run: CaseRun) -> list[str]:
    """Return what the case's scorer found wrong with the run; a run with no outcome fails outright."""
    if not run.end_state:
        return ["the run reported no outcome"]
    missed = run.end_state.get("actor_missed")
    unacted = [f"the run ended before its {missed} actor acted"] if missed else []
    scorer = SCORERS[str(case.expected["scorer"])]
    truth = run.end_state.get("truth") or {}
    return unacted + scorer(Outcome.from_end_state(run.end_state), truth, case.expected)


def _outcome_gate(case: Case, run: CaseRun) -> float:
    return 0.0 if outcome_failures(case, run) else 1.0


BROWSER_GATES: ExtraGates = {_GATE: _outcome_gate}


# --- running one case --------------------------------------------------------


class Actor(StrEnum):
    """Who stands in for the user mid-run; every one but DECLINE must act for its case to count."""

    #: Cancels every handoff the case never asked for.
    DECLINE = "decline"
    CAPTCHA_CANCEL = "captcha_cancel"
    LOGIN_HANDOFF = "login_handoff"
    STOP = "stop"
    MESSAGE = "message"


class ActorFailedError(RuntimeError):
    """The actor standing in for the user raised: the case did not run as written."""


@dataclass(frozen=True)
class CasePlan:
    """What a case's setup asks for, validated when the suite loads, before any run."""

    prompt: str
    secrets: dict[str, str]
    actor: Actor
    message: str | None
    reuse_prompt: str | None
    hn_truth: bool

    @classmethod
    def of(cls, case: Case) -> CasePlan:
        setup = case.setup
        actor = Actor(str(setup.get("actor") or Actor.DECLINE.value))
        message = setup.get("message")
        if (actor is Actor.MESSAGE) != (message is not None):
            raise ValueError(f"{case.id}: setup.message goes with actor: message, and only with it")
        reuse = setup.get("reuse_prompt")
        return cls(
            prompt=case.prompt.replace("{internet}", INTERNET),
            secrets={str(k): str(v) for k, v in (setup.get("secrets") or {}).items()},
            actor=actor,
            message=str(message) if message is not None else None,
            reuse_prompt=str(reuse).replace("{internet}", INTERNET) if reuse else None,
            hn_truth=setup.get("truth") == "hn_titles",
        )


def hn_titles() -> list[str]:
    """Return Hacker News' front-page titles right now: the truth a list task is scored on."""
    page = httpx.get(_HN_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
    return [html.unescape(re.sub(r"<[^>]+>", "", m)) for m in _HN_TITLE.findall(page)]


def start_url_of(task: str) -> str | None:
    """Return the one page a task names, as the executor would pass it; None when it names more or none."""
    pages = {m.group(0).rstrip(".,;:!?") for m in _PAGE_URL.finditer(task)}
    elsewhere = _BARE_SITE.search(_PAGE_URL.sub(" ", task))
    return pages.pop() if len(pages) == 1 and elsewhere is None else None


def _site_of(task: str) -> str:
    url = _PAGE_URL.search(task)
    if url is None:
        raise ValueError(f"a task with a secret names no page: {task[:80]}")
    return urlsplit(url.group(0)).hostname or ""


def job_request(user_id: str, prompt: str, secrets: dict[str, str]) -> BrowserJobRequest:
    """Build the job a case runs: headless, so the ending comes back to this call and lands in no inbox."""
    job_id = uuid.uuid4().hex
    return BrowserJobRequest(
        job_id=job_id,
        user_id=user_id,
        conversation_id=f"eval-{job_id[:12]}",
        tool_call_id=f"eval-call-{job_id[:12]}",
        task=prompt,
        in_background=False,
        start_url=start_url_of(prompt),
        secrets={
            name: BrowserTaskSecret(value=value, site=_site_of(prompt))
            for name, value in secrets.items()
        },
    )


@dataclass
class _Run:
    """One browser job of a case: who it runs for, what its actor did, and the run's own record."""

    job_id: str
    user_id: str
    #: Where the user's reply to the run's handoff arrives.
    reply_to: str
    #: The run's model calls, actions and Jev bursts, as the runner records them.
    ledger: RunLedger = field(default_factory=RunLedger)
    handoffs: list[str] = field(default_factory=list)
    acted: bool = False
    #: Every step card the run showed (the agent's own actions, one card per Jev burst).
    steps: list[dict[str, Any]] = field(default_factory=list)


async def _pending_handoff(run: _Run) -> tuple[str, str] | None:
    """Return the handoff the run waits on now (id, reason), if any."""
    handoff_id = await get_pending_handoff_for_reply(run.reply_to)
    if handoff_id is None:
        return None
    record = await get_handoff(handoff_id)
    if record is None or record.status is not HandoffStatus.PENDING:
        return None
    return handoff_id, record.reason


async def _until(check: Callable[[], Awaitable[T | None]]) -> T:
    """Poll check until it finds something; the run's end is what bounds the wait."""
    while True:
        found = await check()
        if found is not None:
            return found
        await asyncio.sleep(_POLL_SECONDS)


def _cards_in(frame: object) -> list[dict[str, Any]]:
    """Return every card a feed frame carries, however deep its envelope nests it."""
    if not isinstance(frame, dict):
        return []
    found = [frame] if "kind" in frame else []
    for value in frame.values():
        found.extend(_cards_in(value))
    return found


async def _cards(run: _Run, kind: str) -> list[dict[str, Any]]:
    """Return the run's cards of one kind, read from its feed from the start."""
    return [
        card
        for _, frame in await read_job_events(run.job_id, "0-0")
        for card in _cards_in(frame)
        if card.get("kind") == kind
    ]


async def _sign_in_live(run: _Run) -> None:
    """Sign in through the run's own page, as a person does in the live view."""
    sessions = [str(card["session_id"]) for card in await _cards(run, "session")]
    entry = await get_session_entry(sessions[-1]) if sessions else None
    if entry is None or not entry.live_ws:
        raise RuntimeError(f"job {run.job_id} has no live session to sign in through")
    live = urlsplit(entry.live_ws)
    session_id = sessions[-1]
    cdp_url = live._replace(path=live.path.replace(f"/live/{session_id}", f"/cdp/{session_id}"))
    browser = Browser(cdp_url=cdp_url.geturl())
    await browser.start()
    try:
        cdp = await browser.get_or_create_cdp_session(focus=False)
        await cdp.cdp_client.send.Runtime.evaluate(
            params={"expression": _LOGIN_JS, "awaitPromise": True}, session_id=cdp.session_id
        )
    finally:
        await browser.stop()


async def _act(actor: Actor, run: _Run, message: str | None) -> None:
    """Stand in for the user mid-run, as the case says; run.acted records that it did."""
    if actor is Actor.STOP:
        await _until(lambda: _at_least(run, _STEPS_BEFORE_ACTING))
        # A stop that lost to the run's own ending stopped nothing.
        run.acted = await stop_job(run.job_id) is BrowserStopOutcome.STOPPED
        return
    if actor is Actor.MESSAGE:
        if message is None:
            raise ValueError("the message actor has no message to send")
        await _until(lambda: _at_least(run, 1))
        await post_job_message(run.job_id, message)
        run.acted = True
        return
    while True:
        handoff_id, reason = await _until(lambda: _pending_handoff(run))
        run.handoffs.append(reason)
        if actor is Actor.LOGIN_HANDOFF:
            await _sign_in_live(run)
            decision = HandoffDecision.CONTINUE
        else:
            decision = HandoffDecision.CANCEL
        await resolve_handoff(handoff_id, decision, run.user_id)
        run.acted = True
        if actor is Actor.CAPTCHA_CANCEL:
            return


async def _at_least(run: _Run, steps: int) -> int | None:
    """Return how many steps the run took, once it took at least steps; None before."""
    taken = len(await _cards(run, "step"))
    return taken if taken >= steps else None


async def _one_job(
    request: BrowserJobRequest, actor: Actor, message: str | None
) -> tuple[BrowserResultSnapshot, _Run]:
    """Run one job with its actor beside it; an actor that raises ends the job and raises ActorFailedError."""
    run = _Run(
        job_id=request.job_id,
        user_id=request.user_id,
        reply_to=reply_address(
            request.conversation_id, request.user_id, request.conversation_source
        ),
    )
    job = asyncio.create_task(execute_browser_job(request, run.ledger))
    acting = asyncio.create_task(_act(actor, run, message))
    try:
        await asyncio.wait({job, acting}, return_when=asyncio.FIRST_COMPLETED)
        if acting.done():
            try:
                acting.result()
            except Exception as failure:
                raise ActorFailedError(f"the {actor} actor failed: {failure!r}") from failure
        result = await job
        run.steps = [_step_record(card) for card in await _cards(run, "step")]
        return result, run
    finally:
        job.cancel()
        acting.cancel()
        await asyncio.wait({job, acting})


def _step_record(card: dict[str, Any]) -> dict[str, Any]:
    """Return a step card as the journal keeps it: its caption, actions and page, without the photo."""
    return {key: card.get(key) for key in ("index", "goal", "actions", "url")}


def _state(result: BrowserResultSnapshot, run: _Run, actor: Actor) -> dict[str, Any]:
    """Return what one job reported and did, secrets masked as the run masks them."""
    return {
        "summary": result.summary,
        "success": result.success,
        "status": result.status.value,
        "steps": result.steps,
        "handoffs": run.handoffs,
        "actor_missed": None if actor is Actor.DECLINE or run.acted else actor.value,
        "step_cards": run.steps,
        "jev_bursts": [asdict(burst) for burst in run.ledger.bursts],
    }


async def _fresh_pro_user() -> str:
    email = f"eval-browser-{uuid.uuid4().hex[:10]}@gaia.local"
    user = await mint_dev_user(email)
    await grant_pro(email)
    return user.id


async def _metered_tokens(user_id: str) -> tuple[int, int]:
    """Return what the case's runs spent, from the per-call ledger every browser model call writes.

    The ledger writes off the run's path, so the totals are read until they hold still.
    """
    last = await llm_calls_repository.token_totals_for_user(user_id)
    deadline = time.monotonic() + _LEDGER_SETTLE_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(_POLL_SECONDS)
        now = await llm_calls_repository.token_totals_for_user(user_id)
        if now == last:
            return now
        last = now
    return last


async def run_case(case: Case) -> CaseRun:
    """Run a case's browser job (and its reuse run, for a login handoff) and record what it reported."""
    await ensure_app_registered()
    plan = CasePlan.of(case)
    truth: dict[str, Any] = {"titles": hn_titles()} if plan.hn_truth else {}
    user_id = await _fresh_pro_user()
    started = time.monotonic()
    request = job_request(user_id, plan.prompt, plan.secrets)
    result, run = await _one_job(request, plan.actor, plan.message)
    state = _state(result, run, plan.actor)
    if plan.reuse_prompt is not None:
        reuse_request = job_request(user_id, plan.reuse_prompt, {})
        reuse, reuse_run = await _one_job(reuse_request, Actor.DECLINE, None)
        state["reuse"] = _state(reuse, reuse_run, Actor.DECLINE)
        state["reuse_handoff"] = bool(reuse_run.handoffs)
    if truth:
        truth["after"] = hn_titles()
    state["truth"] = truth
    tokens_in, tokens_out = await _metered_tokens(user_id)
    return CaseRun(
        case_id=case.id,
        messages=[
            {"role": "user", "content": plan.prompt},
            {"role": "assistant", "content": result.summary},
        ],
        end_state=state,
        text=result.summary,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_s=time.monotonic() - started,
    )


@register_suite("browser")
class BrowserSuite(Suite):
    name = "browser"
    project = "gaia-browser"
    label = "Browser"
    EXTRA_GATES: ClassVar[ExtraGates] = BROWSER_GATES

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        cases = load_case_files(DATA_DIR, self.name, self.EXTRA_GATES)
        unknown = [c.id for c in cases if c.expected.get("scorer") not in SCORERS]
        if unknown:
            raise ValueError(f"browser cases name no known scorer: {unknown}")
        for case in cases:
            CasePlan.of(case)
        return cases

    def transport(
        self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> Awaitable[CaseRun]:
        del cfg, tracker, provider
        return run_case(case)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        return score_gates(case, run, self.EXTRA_GATES)
