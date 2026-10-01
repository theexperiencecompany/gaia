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
from typing import Protocol

from browser_use.llm.exceptions import ModelError
from browser_use.llm.messages import BaseMessage, SystemMessage, UserMessage
from browser_use.llm.views import ChatInvokeCompletion
from pydantic import BaseModel, Field

from app.constants.browser import (
    JEV_BURST_MAX_ACTIONS,
    JEV_BURST_MAX_DECISIONS,
    JEV_COVERED_LIMIT,
    JEV_PAGE_TEXT_MAX_CHARS,
    JEV_RECENT_ACTIONS,
    JEV_REPORT_OPENED_PAGE_CHARS,
    JEV_SECRET_DIFFERS,
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
    choose_option,
    choose_value,
    decide,
    describe_field,
    masked_json,
)
from app.services.browser.jev.gateway import JevDecider, JevEvaluation, JevGatewayError
from app.services.browser.jev.page import (
    Covered,
    DocumentReplaced,
    FieldUnfocused,
    Frame,
    NavigationFailed,
    PageAction,
    PageScriptError,
    PageState,
    PageUnresponsive,
    StalePage,
    TabUnavailable,
    controls,
)
from app.services.browser.jev.questions import TEXT_VALUE
from app.services.browser.jev.secrets import (
    RunSecrets,
    SecretWithheld,
    holds_placeholder,
    is_placeholder,
)
from app.services.browser.ledger import CallComponent, ExecutedAction, ModelCall, RunLedger
from app.services.browser.run_contract import FlagFn
from shared.py.wide_events import log

#: Why a burst ended, and what the agent is told about it.
_Ending = tuple[JevStop, str]

_ASKED_TO_STOP: _Ending = (JevStop.STOPPED, "The run was asked to stop.")
_USER_MESSAGE: _Ending = (JevStop.USER_MESSAGE, "The user sent a message.")
_MAX_ACTIONS: _Ending = (JevStop.MAX_ACTIONS, f"{JEV_BURST_MAX_ACTIONS} actions in one burst.")
_MAX_DECISIONS: _Ending = (
    JevStop.MAX_DECISIONS,
    f"{JEV_BURST_MAX_DECISIONS} decisions in one burst.",
)
_KEPT_CHANGING: _Ending = (JevStop.STALE, "The page kept changing under each decision.")
_OVERLAID: _Ending = (
    JevStop.COVERED,
    "A press could not reach the chosen control: covered, hidden or disabled.",
)
_JUDGED_BLOCKED: _Ending = (JevStop.BLOCKED, "Jev found no operation that makes progress here.")
_JUDGED_DONE: _Ending = (JevStop.DONE, "Jev judged the goal done.")
_NO_CHANGE: _Ending = (
    JevStop.NO_PROGRESS,
    f"{JEV_UNCHANGED_LIMIT} actions in a row changed nothing.",
)
_CYCLED: _Ending = (
    JevStop.CYCLE,
    "Jev's actions took the page back and forth between the same two states.",
)
#: How many steps one back-and-forth spans: there, back, there again, back again.
_CYCLE_STEPS = 4
_SECRET_WRITTEN = "The written value names a secret; nothing was typed."
#: Unreachable by construction: decide offers an operation only with its target.
_NO_TARGET = "Jev chose an operation with no target on this page; nothing was executed."


def _elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


class _TextValue(BaseModel):
    text: str | None = Field(default=None, max_length=JEV_TEXT_VALUE_MAX_CHARS)


class JevTab(Protocol):
    """The tab as a burst drives it: JevPage on the run's browser."""

    async def observe(self) -> PageState: ...

    async def act(
        self, action: PageAction, page: PageState, text: str | None = None
    ) -> str | None: ...

    async def navigate(self, url: str) -> None: ...

    async def follow_new_tab(self) -> bool: ...

    async def body_text(self, limit: int) -> str: ...


class ValueWriter(Protocol):
    """The tiny model as Jev asks it: one structured answer."""

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[_TextValue]
    ) -> ChatInvokeCompletion[_TextValue]: ...


class LoadStalls(Protocol):
    """The loads the browser stopped because their site never answered."""

    def take(self) -> list[str]: ...


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
    #: The option a SELECT set.
    option: str | None = None
    #: The address a NAVIGATE opened.
    opened: str | None = None
    #: What the field held after typing, quoted, when that is not what was typed.
    held: str | None = None


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
    #: Controls on the final page beyond what the snapshot reads.
    omitted_controls: int = 0


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
    option: str | None = None
    opened: str | None = None
    held: str | None = None


@dataclass
class _Burst:
    """One burst's working state."""

    goal: str
    #: The latest observation; None until the burst's first read succeeds.
    page: PageState | None = None
    steps: list[JevStep] = field(default_factory=list)
    #: The page's fingerprint after each step, to see it go back and forth.
    after: list[str] = field(default_factory=list)
    opened: dict[str, OpenedPage] = field(default_factory=dict)
    decisions: int = 0
    stale: int = 0
    covered: int = 0

    @property
    def current(self) -> PageState:
        if self.page is None:
            raise StalePage("The page was not read.")
        return self.page


@dataclass(frozen=True)
class BurstContext:
    """What every burst shares with the run around it: its ledger, secrets, stopped loads and signals."""

    ledger: RunLedger
    secrets: RunSecrets
    stalls: LoadStalls
    #: Asked between decisions: whether the run must stop, and whether the user sent a message.
    should_stop: FlagFn
    user_waiting: FlagFn


class JevRunner:
    """Runs Jev bursts on one browser session; what it has visited carries across bursts."""

    def __init__(
        self,
        *,
        page: JevTab,
        client: JevDecider,
        text_model: ValueWriter,
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
        #: Every start address the agent gave a burst: the pages NAVIGATE may open besides those visited.
        self._starts: list[str] = []
        #: A value the text model wrote that no input took yet, by the context it was written for.
        self._pending_text: tuple[str, str] | None = None

    async def burst(self, goal: str, start_url: str | None) -> BurstResult:
        """Run Jev on goal from the current page (or start_url) until it stops; every step it took is reported."""
        if start_url and start_url not in self._starts:
            self._starts.append(start_url)
        state = _Burst(goal=goal)
        try:
            opening = await self._open(start_url) if start_url else None
            state.page = await self._page.observe()
            self._visit(state.page)
            stop, detail = opening or await self._run(state)
        except PageUnresponsive as exc:
            stop, detail = JevStop.UNRESPONSIVE, str(exc)
        except StalePage as exc:
            # A read that never settles, before or after an action (which is recorded first).
            stop, detail = JevStop.STALE, str(exc)
        except TabUnavailable as exc:
            stop, detail = JevStop.TAB_UNAVAILABLE, str(exc)
        except PageScriptError as exc:
            stop, detail = JevStop.PAGE_SCRIPT_ERROR, str(exc)
        log.info(f"{LogTag.BROWSER} Jev burst ended", stop=stop.value, actions=len(state.steps))
        return self._result(state, stop, detail)

    def _result(self, state: _Burst, stop: JevStop, detail: str) -> BurstResult:
        final = state.page
        mask = self._secrets.mask
        final_url = mask(final.url) if final else ""
        return BurstResult(
            goal=mask(state.goal),
            stop=stop,
            detail=mask(detail),
            steps=state.steps,
            url=final_url,
            title=mask(final.title) if final else "",
            text=self._secrets.excerpt(final.text, final.text_cut) if final else "",
            opened=[page for url, page in state.opened.items() if url != final_url],
            hidden_frames=[mask(src) for src in _hidden_frames(final.frames)] if final else [],
            omitted_controls=final.omitted_actions if final else 0,
        )

    async def _run(self, state: _Burst) -> _Ending:
        """Decide and execute until the burst ends; each decision is on the page as just read."""
        while True:
            if await self._should_stop():
                return _ASKED_TO_STOP
            if await self._user_waiting():
                return _USER_MESSAGE
            if (spent := _budget_spent(state)) is not None:
                return spent
            # Each decision is on the page as it is now, results that arrived since included.
            state.page = await self._page.observe()
            try:
                ended = await self._execute(state, await self._decide(state))
            except (JevGatewayError, JevDecisionError) as exc:
                # Deciding the step, its option or its value; an action already taken stays recorded.
                return JevStop.GATEWAY, f"Jev could not decide this step: {exc}"
            if ended is not None:
                return ended

    async def _decide(self, state: _Burst) -> Decision:
        state.decisions += 1
        started = perf_counter()
        decision = await decide(
            self._client,
            self._shown(state.current),
            state.goal,
            _history(state),
            self.visited,
            list(dict.fromkeys([*self._starts, *(v.url for v in self.visited)])),
            self._secrets.mask,
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
            return None
        except StalePage:
            state.stale += 1
            return None
        except FieldUnfocused as exc:
            # The click that should have focused the field was sent; the step says what it did.
            if decision.target is not None:
                self._record(state, decision, self._named(decision.target), started)
            return JevStop.FIELD_UNFOCUSED, str(exc)
        if not isinstance(performed, _Performed):
            return performed
        state.stale = state.covered = 0
        before = state.current
        step = self._record(state, decision, performed, started)
        # Recorded before observing: a navigation interrupting the read must not erase the action.
        state.page = await self._page.observe()
        # A person follows the tab a click opens; the read above waited for the click to settle.
        if operation is JevOperation.CLICK and await self._page.follow_new_tab():
            state.page = await self._page.observe()
        state.steps[-1] = replace(step, page_changed=state.page.fingerprint != before.fingerprint)
        state.after.append(state.page.fingerprint)
        if stalled := self._load_stalled():
            return stalled
        await self._read(state)
        return self._stuck(state)

    async def _conclude(self, state: _Burst, operation: JevOperation) -> _Ending | None:
        """Return DONE or BLOCKED once the page it was judged on still stands, else decide again on it.

        The page stands while its document, scroll and fields and its set of controls
        do: results that arrived, or a spinner that gave way, are judged afresh.
        """
        judged = state.current
        state.page = await self._page.observe()
        if _standing(state.page) != _standing(judged):
            return None
        return _JUDGED_BLOCKED if operation is JevOperation.BLOCKED else _JUDGED_DONE

    def _named(self, action: PageAction) -> _Performed:
        """Return a target as its step names it, with any secret masked."""
        mask = self._secrets.mask
        return _Performed(
            label=mask(action["label"]),
            ident=mask(action.get("ident", "")),
            href=mask(action.get("href", "")),
        )

    async def _perform(self, state: _Burst, decision: Decision) -> _Performed | _Ending:
        """Carry out one decision on the page; return what it did, or why the burst ends instead."""
        operation = decision.operation
        if decision.url is not None:
            failed = await self._open(decision.url)
            shown = self._secrets.mask(decision.url)
            return failed if failed is not None else _Performed(label=f"Open {shown}", opened=shown)
        action = decision.target
        if action is None:
            raise JevDecisionError(_NO_TARGET)
        target = self._named(action)
        page = state.current
        if operation is JevOperation.SELECT:
            option: PageAction = await self._option_for(state, action)
            await self._page.act(option, page)
            return replace(target, option=self._secrets.mask(option["current_value"]))
        if operation is not JevOperation.TYPE_TEXT:
            await self._page.act(action, page)
            return target
        try:
            value = await self._value_for(state, action)
        except SecretWithheld as exc:
            return JevStop.SECRET_WITHHELD, str(exc)
        if value is None:
            return (
                JevStop.NEEDS_INPUT,
                f"The goal gives no value for the field “{target.label}”.",
            )
        shown, typed = value
        held = await self._page.act(action, page, text=typed)
        self._pending_text = None
        return replace(target, text=shown, held=self._held(action, typed, held))

    def _held(self, action: PageAction, typed: str, held: str | None) -> str | None:
        """Return what the field holds when it is not what was typed; a password's value never shows."""
        if held is None or held == typed:
            return None
        return (
            JEV_SECRET_DIFFERS
            if action["kind"] == "secret"
            else json.dumps(self._secrets.mask(held))
        )

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
            url=self._secrets.mask(state.current.url),
            page_changed=None,
            option=performed.option,
            opened=performed.opened,
            held=performed.held,
        )
        state.steps.append(step)
        return step

    async def _read(self, state: _Burst) -> None:
        """Note the page the action led to: visited, and its text read once for the report."""
        page = state.current
        self._visit(page)
        mask = self._secrets.mask
        url = mask(page.url)
        if url not in state.opened:
            # Read once per page: the viewport text of an article is mostly its header.
            try:
                body = await self._page.body_text(JEV_REPORT_OPENED_PAGE_CHARS)
            except DocumentReplaced:
                # It navigated on by itself (a redirect): the next read is of the page it went to.
                return
            text = self._secrets.excerpt(body, cut=len(body) >= JEV_REPORT_OPENED_PAGE_CHARS)
            state.opened[url] = OpenedPage(url=url, title=mask(page.title), text=text)
        else:
            state.opened[url] = state.opened.pop(url)

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
        """Whether the burst stopped making progress: no change, or the page going back and forth."""
        recent = [
            s for s in state.steps[-JEV_UNCHANGED_LIMIT:] if s.operation is not JevOperation.WAIT
        ]
        if len(recent) == JEV_UNCHANGED_LIMIT and all(s.page_changed is False for s in recent):
            return _NO_CHANGE
        # The same two pages in turn: repeating one move on a page that changes (adding
        # items to a cart, one by one) is progress, not a cycle.
        pages = state.after[-_CYCLE_STEPS:]
        if len(pages) == _CYCLE_STEPS and pages[0] == pages[2] != pages[1] == pages[3]:
            return _CYCLED
        return None

    async def _option_for(self, state: _Burst, dropdown: PageAction) -> PageAction:
        """Return the chosen dropdown set to the option the goal asks for."""
        started = perf_counter()
        option, evaluation = await choose_option(
            self._client,
            self._shown(state.current),
            state.goal,
            dropdown,
            _history(state),
            self._secrets.mask,
        )
        self._record_call(evaluation, _elapsed_ms(started))
        return option

    async def _value_for(self, state: _Burst, action: PageAction) -> tuple[str, str] | None:
        """Return what to type into action, as (shown, typed); None when the goal gives no value."""
        history = _history(state)
        page = state.current
        started = perf_counter()
        choice, evaluation = await choose_value(
            self._client,
            self._shown(page),
            state.goal,
            action,
            history,
            self._secrets.names,
            self._secrets.mask,
        )
        self._record_call(evaluation, _elapsed_ms(started))
        if choice == NONE_VALUE:
            return None
        if choice == GENERATE:
            written = await self._write_value(state, action, history)
            return (written, written) if written else None
        if is_placeholder(choice):
            return choice, self._secrets.value_for(choice, page.url)
        return choice, choice

    async def _write_value(
        self, state: _Burst, action: PageAction, history: list[RecentAction]
    ) -> str | None:
        """Ask the tiny model for a value the goal implies but does not spell out.

        A value written for the same context and not typed yet (the page moved first) is reused.
        A model that fails or never answers is a step Jev could not decide.
        """
        page = self._shown(state.current)
        context = {
            "goal": state.goal,
            "field": describe_field(action),
            "page": {"title": page.title, "text": page.text[:JEV_PAGE_TEXT_MAX_CHARS]},
            "recent_actions": [{"action": h.action, "text": h.text} for h in history],
        }
        # The field's label and value, the page and the goal can each hold a secret's value.
        masked = json.dumps(masked_json(context, self._secrets.mask))
        if self._pending_text is not None and self._pending_text[0] == masked:
            return self._pending_text[1]
        try:
            completion = await asyncio.wait_for(
                self._text_model.ainvoke(
                    [SystemMessage(content=TEXT_VALUE), UserMessage(content=masked)],
                    output_format=_TextValue,
                ),
                timeout=JEV_TEXT_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ModelError) as exc:
            raise JevDecisionError(
                f"The value could not be written ({type(exc).__name__})."
            ) from exc
        value = completion.completion.text
        if value and holds_placeholder(value):
            # A secret is typed only as itself, on its own site, never inside a written value.
            raise JevDecisionError(_SECRET_WRITTEN)
        if not (value and value.strip()):
            return None
        self._pending_text = (masked, value)
        return value

    def _shown(self, page: PageState) -> PageState:
        """Return page with its text masked before any cut of it, so a split value leaves no prefix."""
        return replace(page, text=self._secrets.excerpt(page.text, page.text_cut))

    def _visit(self, page: PageState) -> None:
        """Keep the page's real address, to open it again; every question masks it."""
        url = page.url
        self.visited = [v for v in self.visited if v.url != url][-(JEV_VISITED_PAGES - 1) :]
        self.visited.append(Visited(title=page.title, url=url))

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


def _standing(page: PageState) -> tuple[str, list[str]]:
    """Return what a judgement on page rests on: its key and its controls, wherever they sit."""
    return json.dumps(page.page_key), sorted(
        json.dumps(control) for control in controls(page.actions)
    )


def _budget_spent(state: _Burst) -> _Ending | None:
    """Return which of the burst's own budgets is spent, if one is: actions, decisions, stale or covered targets."""
    spent = (
        (len(state.steps) >= JEV_BURST_MAX_ACTIONS, _MAX_ACTIONS),
        (state.decisions >= JEV_BURST_MAX_DECISIONS, _MAX_DECISIONS),
        (state.stale >= JEV_STALE_LIMIT, _KEPT_CHANGING),
        (state.covered >= JEV_COVERED_LIMIT, _OVERLAID),
    )
    return next((ending for hit, ending in spent if hit), None)


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
            action=s.label if s.option is None else f"{s.label}: {s.option}",
            kind=s.operation.value,
            text=s.text,
            page_changed=s.page_changed,
        )
        for s in state.steps[-JEV_RECENT_ACTIONS:]
    ]
