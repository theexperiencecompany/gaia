"""One Jev burst: observe, one decision, execute, until Jev is done or the agent must take over.

Ported from browser-use/jev-ultrafast (MIT) jev_ultrafast/agent.py. A
decision is made only against a fresh observation, is consumed once before any
input, and a mutation is never retried: a stale or covered target is observed
again and decided again. Execution is recorded before the next observation,
so a navigation that interrupts it cannot erase it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import json
from time import perf_counter
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.constants.browser import (
    JEV_BURST_MAX_ACTIONS,
    JEV_CAPTCHA_FRAME_MARKERS,
    JEV_COVERED_LIMIT,
    JEV_PAGE_TEXT_MAX_CHARS,
    JEV_RECENT_ACTIONS,
    JEV_REPORT_OPENED_PAGE_CHARS,
    JEV_STALE_LIMIT,
    JEV_TEXT_TIMEOUT_SECONDS,
    JEV_TEXT_VALUE_MAX_CHARS,
    JEV_UNCHANGED_LIMIT,
    JEV_VISITED_PAGES,
    JevOperation,
    JevStop,
)
from app.constants.log_tags import LogTag
from app.services.browser.jev.decision import (
    GENERATE,
    NONE_VALUE,
    Decision,
    JevDecisionError,
    RecentAction,
    Visited,
    choose_value,
    decide,
    describe_field,
    goal_addresses,
)
from app.services.browser.jev.gateway import JevDecisionsClient, JevEvaluation, JevGatewayError
from app.services.browser.jev.page import (
    Covered,
    Frame,
    JevPage,
    NavigationFailed,
    PageAction,
    PageState,
    PageUnresponsive,
    StalePage,
    UncertainSelect,
)
from app.services.browser.jev.questions import TEXT_VALUE
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.ledger import CallComponent, ExecutedAction, ModelCall, RunLedger
from app.services.browser.run_contract import FlagFn
from app.services.browser.stalled_loads import StalledLoads
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.llm.base import BaseChatModel

#: Why a burst ended, and what the agent is told about it.
_Ending = tuple[JevStop, str]

_ASKED_TO_STOP: _Ending = (JevStop.STOPPED, "The run was asked to stop.")
_USER_MESSAGE: _Ending = (JevStop.USER_MESSAGE, "The user sent a message.")
_MAX_ACTIONS: _Ending = (JevStop.MAX_ACTIONS, f"{JEV_BURST_MAX_ACTIONS} actions in one burst.")
_KEPT_CHANGING: _Ending = (JevStop.STALE, "The page kept changing under each decision.")
_OVERLAID: _Ending = (
    JevStop.COVERED,
    "The chosen control is covered, hidden or disabled (an overlay?).",
)
_JUDGED_BLOCKED: _Ending = (JevStop.BLOCKED, "Jev found no operation that makes progress here.")
_JUDGED_DONE: _Ending = (JevStop.DONE, "Jev judged the goal done.")
_NO_CHANGE: _Ending = (
    JevStop.NO_PROGRESS,
    f"{JEV_UNCHANGED_LIMIT} actions in a row changed nothing.",
)
_CYCLED: _Ending = (JevStop.CYCLE, "Jev went back and forth between the same two actions.")
#: How much of a CAPTCHA frame's address the stop names.
_CAPTCHA_SRC_CHARS = 120
#: What a page-level step records as its label.
_PAGE_LEVEL_LABELS = {JevOperation.GO_BACK: "Go back", JevOperation.PRESS_ENTER: "Press Enter"}


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


class _TextValue(BaseModel):
    text: str | None = Field(default=None, max_length=JEV_TEXT_VALUE_MAX_CHARS)


@dataclass(frozen=True)
class JevStep:
    """One executed action of a burst, as the agent and the card read it."""

    operation: JevOperation
    label: str
    #: The target's id or name attribute, which tells apart controls that share a label.
    ident: str
    #: Where a clicked link points.
    href: str
    #: What was typed, with any secret masked; None for every other operation.
    text: str | None
    url: str
    page_changed: bool | None
    decision_ms: int


@dataclass(frozen=True)
class OpenedPage:
    """A page a burst opened, and its visible text as Jev read it there."""

    url: str
    title: str
    text: str


@dataclass(frozen=True)
class BurstResult:
    goal: str
    stop: JevStop
    detail: str
    steps: list[JevStep]
    url: str
    title: str
    #: The final page's visible text, as Jev read it.
    text: str
    #: Every other page the burst opened, in order, as Jev read it there.
    opened: list[OpenedPage]
    #: Frames on the final page whose content Jev cannot see (cross-origin).
    hidden_frames: list[str]

    @property
    def progressed(self) -> bool:
        return any(step.page_changed for step in self.steps)


@dataclass(frozen=True)
class _Performed:
    """What one executed decision did, as its step records it."""

    label: str
    #: The target's id or name attribute.
    ident: str = ""
    #: Where a clicked link points.
    href: str = ""
    #: What was typed, as shown (a secret stays its placeholder).
    text: str | None = None
    #: The tabs open before a click, to follow one it opens.
    tabs: frozenset[str] = frozenset()


@dataclass
class _Burst:
    """One burst's working state."""

    goal: str
    page: PageState
    addresses: list[str]
    steps: list[JevStep] = field(default_factory=list)
    opened: dict[str, OpenedPage] = field(default_factory=dict)
    stale: int = 0
    covered: int = 0


@dataclass(frozen=True)
class BurstContext:
    """What every burst shares with the run around it: its ledger, secrets, stopped loads and signals."""

    ledger: RunLedger
    secrets: RunSecrets
    stalls: StalledLoads
    #: Asked between decisions: whether the run must stop, and whether the user sent a message.
    should_stop: FlagFn
    user_waiting: FlagFn


class JevRunner:
    """Runs Jev bursts on one browser session; what it has visited carries across bursts."""

    def __init__(
        self,
        *,
        page: JevPage,
        client: JevDecisionsClient,
        text_model: BaseChatModel,
        run: BurstContext,
    ) -> None:
        self._page = page
        self._client = client
        self._text_model = text_model
        self._ledger = run.ledger
        self._secrets = run.secrets
        self._stalls = run.stalls
        self._should_stop = run.should_stop
        self._user_waiting = run.user_waiting
        self.visited: list[Visited] = []

    async def burst(self, goal: str, start_url: str | None) -> BurstResult:
        """Run Jev on goal from the current page (or start_url) until it stops."""
        opening = await self._open(start_url) if start_url else None
        page = await self._page.observe()
        self._visit(page)
        state = _Burst(goal=goal, page=page, addresses=goal_addresses(goal))
        try:
            stop, detail = opening or await self._run(state)
        except PageUnresponsive as exc:
            stop, detail = JevStop.UNRESPONSIVE, str(exc)
        except StalePage as exc:
            # A read that never settles, before or after an action (which is recorded first).
            stop, detail = JevStop.STALE, str(exc)
        final = state.page
        final_url = self._secrets.mask(final.url)
        log.info(
            f"{LogTag.BROWSER} Jev burst ended",
            stop=stop.value,
            actions=len(state.steps),
        )
        return BurstResult(
            goal=goal,
            stop=stop,
            detail=detail,
            steps=state.steps,
            url=final_url,
            title=final.title,
            text=self._secrets.mask(final.text),
            opened=[page for url, page in state.opened.items() if url != final_url],
            hidden_frames=_hidden_frames(final.frames),
        )

    async def _run(self, state: _Burst) -> _Ending:
        while True:
            if await self._should_stop():
                return _ASKED_TO_STOP
            if await self._user_waiting():
                return _USER_MESSAGE
            if (captcha := _captcha(state.page.frames)) is not None:
                return (
                    JevStop.CAPTCHA,
                    f"A CAPTCHA is on the page ({captcha[:_CAPTCHA_SRC_CHARS]}).",
                )
            if len(state.steps) >= JEV_BURST_MAX_ACTIONS:
                return _MAX_ACTIONS
            if state.stale >= JEV_STALE_LIMIT:
                return _KEPT_CHANGING
            if state.covered >= JEV_COVERED_LIMIT:
                return _OVERLAID
            if not await self._page.fresh(state.page):
                state.page = await self._page.observe()
            try:
                ended = await self._execute(state, await self._decide(state))
            except (JevGatewayError, JevDecisionError) as exc:
                # Deciding the step or the value to type; an action already taken stays recorded.
                return JevStop.GATEWAY, f"Jev could not decide this step: {exc}"
            if ended is not None:
                return ended

    async def _decide(self, state: _Burst) -> Decision:
        started = perf_counter()
        decision = await decide(
            self._client,
            self._masked(state.page),
            state.goal,
            _history(state),
            self.visited,
            list(dict.fromkeys([*state.addresses, *(v.url for v in self.visited)])),
        )
        self._record_call(decision.evaluation, _elapsed_ms(started))
        return decision

    async def _execute(self, state: _Burst, decision: Decision) -> _Ending | None:
        """Execute one decision; return why the burst ends, or None to take another step."""
        operation = decision.operation
        if operation in (JevOperation.DONE, JevOperation.BLOCKED):
            return await self._conclude(state, operation)
        started = perf_counter()
        try:
            performed = await self._perform(state, decision)
        except Covered:
            state.covered += 1
            state.page = await self._page.observe()
            return None
        except UncertainSelect as exc:
            return JevStop.STALE, str(exc)
        except StalePage:
            state.stale += 1
            state.page = await self._page.observe()
            return None
        if not isinstance(performed, _Performed):
            return performed
        state.stale = state.covered = 0
        before = state.page
        step = self._record(state, decision, performed, started)
        # Recorded before observing: a navigation interrupting the read must not erase the action.
        state.page = await self._page.observe()
        # Checked after the read, when a tab the click opened is registered; a
        # person follows the tab a link opens.
        if operation is JevOperation.CLICK and await self._page.follow_new_tab(set(performed.tabs)):
            state.page = await self._page.observe()
        state.steps[-1] = replace(step, page_changed=state.page.fingerprint != before.fingerprint)
        if stalled := self._load_stalled():
            return stalled
        await self._read(state)
        return self._stuck(state)

    async def _conclude(self, state: _Burst, operation: JevOperation) -> _Ending | None:
        """Return DONE or BLOCKED once the page it was judged on still stands, else read it again."""
        if not await self._page.fresh(state.page):
            state.page = await self._page.observe()
            return None
        return _JUDGED_BLOCKED if operation is JevOperation.BLOCKED else _JUDGED_DONE

    async def _perform(self, state: _Burst, decision: Decision) -> _Performed | _Ending:
        """Carry out one decision on the page; return what it did, or why the burst ends instead."""
        operation = decision.operation
        if decision.url is not None:
            failed = await self._open(decision.url)
            return failed if failed is not None else _Performed(label=f"Open {decision.url}")
        if decision.action_id is None:
            # GO_BACK and PRESS_ENTER act on the page, not on an observed target.
            label = _PAGE_LEVEL_LABELS[operation]
            if operation is JevOperation.GO_BACK:
                await self._page.go_back()
            else:
                await self._page.press_enter()
            return _Performed(label=label)
        action: PageAction = state.page.action(decision.action_id)
        target = _Performed(
            label=action["label"],
            ident=action.get("ident", ""),
            href=self._secrets.mask(action.get("href", "")),
        )
        if operation is JevOperation.TYPE_TEXT:
            value = await self._value_for(state, action)
            if value is None:
                return (
                    JevStop.NEEDS_INPUT,
                    f"The goal gives no value for the field “{target.label}”.",
                )
            text, typed = value
            await self._page.act(action, state.page, text=typed)
            return replace(target, text=text)
        tabs = await self._page.tab_ids()
        await self._page.act(action, state.page)
        return replace(target, tabs=frozenset(tabs))

    def _record(
        self, state: _Burst, decision: Decision, performed: _Performed, started: float
    ) -> JevStep:
        """Record an executed action in the ledger and the burst, before the page is read again."""
        operation = decision.operation
        self._ledger.executed(
            ExecutedAction(
                component=CallComponent.JEV,
                description=self._secrets.redact(f"{operation.value} {performed.label}"),
                duration_ms=_elapsed_ms(started),
            )
        )
        step = JevStep(
            operation=operation,
            label=performed.label,
            ident=performed.ident,
            href=performed.href,
            text=performed.text,
            url=self._secrets.mask(state.page.url),
            page_changed=None,
            decision_ms=decision.latency_ms,
        )
        state.steps.append(step)
        return step

    async def _read(self, state: _Burst) -> None:
        """Note the page the action led to: visited, and its text read once for the report."""
        self._visit(state.page)
        opened = self._masked(state.page)
        if opened.url not in state.opened:
            # Read once per page: the viewport text of an article is mostly its header.
            body = await self._page.body_text(JEV_REPORT_OPENED_PAGE_CHARS)
            state.opened[opened.url] = OpenedPage(
                url=opened.url, title=opened.title, text=self._secrets.mask(body)
            )
        else:
            state.opened[opened.url] = state.opened.pop(opened.url)

    async def _open(self, url: str) -> _Ending | None:
        """Open url; return why the burst ends when the page could not be opened."""
        try:
            await self._page.navigate(url)
        except NavigationFailed as exc:
            return self._load_stalled() or (
                JevStop.NAVIGATION_FAILED,
                self._secrets.mask(f"{url} could not be opened: {exc}"),
            )
        return None

    def _load_stalled(self) -> _Ending | None:
        """Return why the burst ends when the browser stopped loads that never answered."""
        stalled = self._stalls.take()
        return (JevStop.LOAD_STALLED, self._secrets.mask(" ".join(stalled))) if stalled else None

    def _stuck(self, state: _Burst) -> _Ending | None:
        """Whether the burst stopped making progress: no change, or a back-and-forth between two moves."""
        recent = [
            s for s in state.steps[-JEV_UNCHANGED_LIMIT:] if s.operation is not JevOperation.WAIT
        ]
        if len(recent) == JEV_UNCHANGED_LIMIT and all(s.page_changed is False for s in recent):
            return _NO_CHANGE
        moves = [(s.url, s.label) for s in state.steps[-4:]]
        if len(moves) == 4 and moves[0] == moves[2] != moves[1] == moves[3]:
            return _CYCLED
        return None

    async def _value_for(self, state: _Burst, action: PageAction) -> tuple[str, str] | None:
        """Return what to type into action, as (shown, typed); None when the goal gives no value."""
        page = self._masked(state.page)
        history = _history(state)
        started = perf_counter()
        choice, evaluation = await choose_value(
            self._client, page, state.goal, action, history, self._secrets.names
        )
        self._record_call(evaluation, _elapsed_ms(started))
        if choice == NONE_VALUE:
            return None
        if choice == GENERATE:
            written = await self._write_value(state, action, history)
            return (written, written) if written else None
        if action["kind"] == "secret":
            secret = self._secrets.value_for(choice, state.page.url)
            return (choice, secret) if secret else None
        return choice, choice

    async def _write_value(
        self, state: _Burst, action: PageAction, history: list[RecentAction]
    ) -> str | None:
        """Ask the tiny model for a value the goal implies but does not spell out.

        A model that fails or never answers is a step Jev could not decide.
        """
        from browser_use.llm.exceptions import ModelError  # noqa: PLC0415 -- heavy optional dep
        from browser_use.llm.messages import (  # noqa: PLC0415 -- heavy optional dep
            SystemMessage,
            UserMessage,
        )

        page = self._masked(state.page)
        context = {
            "goal": state.goal,
            "field": describe_field(action),
            "page": {"title": page.title, "text": page.text[:JEV_PAGE_TEXT_MAX_CHARS]},
            "recent_actions": [{"action": h.action, "text": h.text} for h in history],
        }
        try:
            completion = await asyncio.wait_for(
                self._text_model.ainvoke(
                    [SystemMessage(content=TEXT_VALUE), UserMessage(content=json.dumps(context))],
                    output_format=_TextValue,
                ),
                timeout=JEV_TEXT_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ModelError) as exc:
            raise JevDecisionError(
                f"The value could not be written ({type(exc).__name__})."
            ) from exc
        value = completion.completion.text
        return value if value and value.strip() else None

    def _visit(self, page: PageState) -> None:
        url = self._secrets.mask(page.url)
        self.visited = [v for v in self.visited if v.url != url][-(JEV_VISITED_PAGES - 1) :]
        self.visited.append(Visited(title=page.title, url=url))

    def _masked(self, page: PageState) -> PageState:
        """Return the page as Jev may read it: no secret value in its address or text."""
        return replace(page, url=self._secrets.mask(page.url), text=self._secrets.mask(page.text))

    def _record_call(self, evaluation: JevEvaluation, latency_ms: int) -> None:
        usage = evaluation.usage
        self._ledger.add(
            ModelCall(
                component=CallComponent.JEV,
                provider=evaluation.provider,
                model=self._client.model,
                latency_ms=latency_ms,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cost_usd=evaluation.gateway_cost_usd,
            )
        )


def _captcha(frames: list[Frame]) -> str | None:
    """Return the address of a CAPTCHA frame on the page, if one is shown."""
    return next(
        (
            frame["src"]
            for frame in frames
            if frame["visible"]
            and any(marker in frame["src"].lower() for marker in JEV_CAPTCHA_FRAME_MARKERS)
        ),
        None,
    )


def _hidden_frames(frames: list[Frame]) -> list[str]:
    """Return the shown frames Jev cannot see into: cross-origin ones with an address."""
    return [
        frame["src"]
        for frame in frames
        if frame["visible"] and not frame["same_origin"] and frame["src"]
    ]


def _history(state: _Burst) -> list[RecentAction]:
    """Return the burst's recent actions as Jev's questions show them."""
    return [
        RecentAction(
            action=s.label, kind=s.operation.value, text=s.text, page_changed=s.page_changed
        )
        for s in state.steps[-JEV_RECENT_ACTIONS:]
    ]
