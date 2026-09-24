"""Jev as the Browser-Use agent's decision model.

Browser-Use asks its chat model for an AgentOutput every step; this class
answers by having Jev decide the operation and target from the current page
state instead of returning a completion, and using the small text model only
to write a typed value when the decision needs one. Everything downstream
(execution, step cards, takeover, history, replay) is unchanged; calls that
are not a step decision go straight to the text model.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, replace
import json
import re
from time import perf_counter
from typing import (
    TYPE_CHECKING,
    Literal,
    Protocol,
    TypedDict,
    TypeVar,
    cast,
    get_args,
    overload,
)
from urllib.parse import urlsplit

from langchain_core.messages import BaseMessage as LangChainMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import CoreSchema, core_schema

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, silent_metered_config
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_FALLBACK_PAGE_BLOCKED,
    BROWSER_GUIDANCE_MAX_ELEMENTS,
    BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS,
    BROWSER_GUIDANCE_RECENT_ACTIONS,
    BROWSER_RUN_BLOCKED_SUMMARY,
    JEV_CLOSING_ANSWER_ACTIONS,
    JEV_CLOSING_ANSWER_HEDGE_SECONDS,
    JEV_CLOSING_ANSWER_TIMEOUT_SECONDS,
    JEV_DONE_REASK_BUDGET,
    JEV_MIN_DONE_CONFIDENCE,
    JEV_PLAN_MAX_STEPS,
    JEV_SECRET_MASK,
    JEV_SUMMARY_MAX_CHARS,
    JEV_TEXT_HEDGE_SECONDS,
    JEV_TEXT_HELPER_RECENT_ACTIONS,
    JEV_TEXT_TIMEOUT_SECONDS,
    JEV_TEXT_VALUE_MAX_CHARS,
    JEV_WAIT_SECONDS,
    BrowserHandoffAction,
    BrowserRunFailure,
    JevNoteSource,
    JevOperation,
    SensitiveCategory,
)
from app.constants.llm import ReasoningLevel
from app.constants.log_tags import LogTag
from app.patches.browser_use_deferred_screenshot_patch import defer_screenshots_for
from app.schemas.browser import AgentGuidanceRequest, GuidanceAction, GuidanceElement
from app.services.browser.exceptions import BrowserUnavailableError
from app.services.browser.jev.gateway import (
    JevDecisionsClient,
    JevFailoverClient,
    JevGatewayClient,
    JevGatewayError,
)
from app.services.browser.jev.hedge import first_answer
from app.services.browser.jev.live_values import read_live_values
from app.services.browser.jev.observation import JevElement, JevObservation, observe
from app.services.browser.jev.policy import (
    JevDecision,
    JevDecisionError,
    JevHistoryEntry,
    choose,
    page_key,
)
from app.services.browser.jev.prompts import (
    CAPTCHA_CHALLENGE,
    DONE_SUMMARY,
    GUIDANCE_REASON,
    PART_DONE,
    PLAN_STEPS,
    TAKEOVER_REASON,
    TEXT_VALUE,
    URL_VALUE,
)
from app.services.browser.jev.secrets import TypedSecrets
from app.services.browser.jev.seen_text import ReadPage, SeenText
from app.services.browser.jev.viewport import NodeHandles, ViewportBox, read_viewport
from app.services.browser.run_contract import GuidanceGate
from shared.py.wide_events import log

if TYPE_CHECKING:
    from browser_use.browser.session import BrowserSession
    from browser_use.llm.base import BaseChatModel
    from browser_use.llm.messages import BaseMessage
    from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar("T", bound=BaseModel)
_R = TypeVar("_R")


class _WaitAction(TypedDict, total=False):
    """One Browser-Use action, read only for whether it fell back to waiting."""

    wait: dict[str, object]


class _ActionField(TypedDict):
    """AgentOutput's fields, read only for the action model they carry."""

    action: FieldInfo


class _RootField(TypedDict, total=False):
    """A RootModel's fields, read only for the union member it wraps."""

    root: FieldInfo


# Browser-Use action name → the Jev operations it makes available. Text entry
# is `input` in Browser-Use 0.11 and `input_text` before it; both are known.
_OPERATIONS_BY_ACTION: dict[str, tuple[JevOperation, ...]] = {
    "click": (JevOperation.CLICK,),
    "input": (JevOperation.TYPE_TEXT,),
    "input_text": (JevOperation.TYPE_TEXT,),
    "select_dropdown": (JevOperation.SELECT,),
    "scroll": (JevOperation.SCROLL_UP, JevOperation.SCROLL_DOWN),
    "wait": (JevOperation.WAIT,),
    "navigate": (JevOperation.NAVIGATE,),
    "go_back": (JevOperation.GO_BACK,),
    BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: (JevOperation.REQUEST_HUMAN,),
    BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: (JevOperation.SOLVE_CAPTCHA,),
    "done": (JevOperation.DONE, JevOperation.BLOCKED),
}
_DEFAULT_TAKEOVER_REASON = "Complete this step in the live browser"
_DEFAULT_GUIDANCE_REASON = "No operation on this page moves the task forward."
_DEFAULT_CAPTCHA_CHALLENGE = "Solve the CAPTCHA, then continue"
_USER_REQUEST = re.compile(r"<user_request>(.*?)</user_request>", re.DOTALL)
# Neither ends the run on a real next action, so neither counts as an alternative
# to an unconfident DONE.
_TERMINAL_OPERATIONS = frozenset({JevOperation.DONE, JevOperation.BLOCKED})
_HANDOFF_OPERATIONS = frozenset({JevOperation.REQUEST_HUMAN, JevOperation.SOLVE_CAPTCHA})
# A step that ends the run or hands it to someone acts only once the part's
# judgement is in: ending a part already done, or asking a person to finish it, is wrong.
_WAITS_FOR_JUDGEMENT = _TERMINAL_OPERATIONS | _HANDOFF_OPERATIONS
#: History kinds a part judgement can cite as done: a field filled, an option or
#: box chosen, a button clicked, a step handed to the user.
_EVIDENCE_KINDS = frozenset({"type_text", "select", "click", "request_human", "solve_captcha"})
#: The part in progress, the pages read and the actions taken: what a judgement is of.
_JudgedState = tuple[int, tuple[tuple[str, ...], ...], tuple[str, ...]]
_JEV_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
# Vercel AI Gateway evaluation endpoint: same {model, state, questions} body
# and {answers, usage} response as the OpenRouter decisions route.
_JEV_VERCEL_EVALUATE_URL = "https://ai-gateway.vercel.sh/v1/evaluate"


class _TextValue(BaseModel):
    text: str | None = None


class _ClosingAnswer(BaseModel):
    """The closing answer is never optional: an empty reply is a failed call, retried on the lane."""

    text: str = Field(min_length=1)
    #: Whether the goal was done: an honest "there is no Buy now button" is a
    #: good answer to a goal that was not achieved, and the run reports it so.
    achieved: bool


class _TakeoverReason(BaseModel):
    text: str | None = None
    category: str = SensitiveCategory.IRREVERSIBLE.value


class StructuredCall(Protocol):
    """One structured one-shot to the writer: a schema and a prompt in, the filled schema out."""

    async def __call__(
        self,
        schema: type[T],
        prompt: list[LangChainMessage],
        *,
        label: str,
        timeout: float = JEV_TEXT_TIMEOUT_SECONDS,
        reasoning: ReasoningLevel | None = None,
    ) -> T: ...


def canonical_structured_call(user_id: str | None) -> StructuredCall:
    """Return the app's one structured one-shot, metered to the user the run works for."""

    async def call(
        schema: type[T],
        prompt: list[LangChainMessage],
        *,
        label: str,
        timeout: float = JEV_TEXT_TIMEOUT_SECONDS,
        reasoning: ReasoningLevel | None = None,
    ) -> T:
        return await ainvoke_structured(
            schema,
            prompt,
            label=label,
            config=silent_metered_config(user_id) if user_id else None,
            options=StructuredCallOptions(timeout=timeout, reasoning=reasoning),
        )

    return call


class _PlanStep(BaseModel):
    goal: str = ""
    url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_sentence(cls, value: object) -> object:
        # The writer sometimes lists a part as its sentence alone; that is a
        # part with no site of its own, not a malformed plan.
        return {"goal": value} if isinstance(value, str) else value


class _PlanSteps(BaseModel):
    steps: list[_PlanStep] = []


class _Evidence(BaseModel):
    """One requirement of a part and what the run holds for it."""

    requirement: str = ""
    #: None for a bare source with no kind: held to the strictest rule.
    kind: Literal["action", "page opened", "fact"] | None = None
    source: str = ""

    @model_validator(mode="before")
    @classmethod
    def _from_source(cls, value: object) -> object:
        # The writer sometimes lists an entry as its source alone.
        return {"source": value} if isinstance(value, str) else value


class _PartDone(BaseModel):
    #: Named before the evidence, so a requirement with nothing to cite is
    #: written down rather than left out of a "done".
    requirements: list[str] = []
    evidence: list[_Evidence] = []
    done: bool = False
    findings: str = ""

    def uncovered(self) -> list[str]:
        """Return the requirements left without an evidence entry of their own.

        One entry per requirement is what the writer is asked for; fewer entries
        than requirements leaves the ones no entry names (in any wording) bare.
        """
        if len(self.evidence) >= len(self.requirements):
            return []
        named = {" ".join(item.requirement.casefold().split()) for item in self.evidence}
        return [r for r in self.requirements if " ".join(r.casefold().split()) not in named]


@dataclass(frozen=True)
class _WriterCall:
    """What one writer call sees beyond goal, page and field, and the lane it runs on.

    whole_history hands over every action of the run, not the recent few: the
    closing answer can only know what was done from the actions themselves.
    start_page is the page the current part began on, which the run opened for it.
    """

    seen_text: str | None = None
    whole_history: bool = False
    start_page: str | None = None
    timeout: float = JEV_TEXT_TIMEOUT_SECONDS
    hedge_after: float = JEV_TEXT_HEDGE_SECONDS
    label: str | None = None
    reasoning: ReasoningLevel | None = None


_DEFAULT_WRITER_CALL = _WriterCall()


@dataclass(frozen=True)
class _PendingChoice:
    """A step's choice as asked: its goal and operations, Jev's answer in flight, and any closing answer started with it."""

    goal: str
    offered: frozenset[JevOperation]
    choosing: asyncio.Task[JevDecision] | None
    answering: asyncio.Task[_ClosingAnswer | None] | None


@dataclass(frozen=True)
class _SettledChoice:
    """The decision a step executes, the goal it was made against, and the closing answer it may use."""

    decision: JevDecision
    goal: str
    answering: asyncio.Task[_ClosingAnswer | None] | None


class JevChatModel:
    """Browser-Use BaseChatModel whose step decisions come from Jev."""

    _verified_api_keys = True

    #: The step photo in flight, rendered while the decision is; class-level so a
    #: model built without __init__ (the runner tests do) still answers None.
    _shot: asyncio.Task[str | None] | None = None

    def __init__(
        self,
        *,
        client: JevDecisionsClient,
        text_model: BaseChatModel,
        provider: str = "openrouter",
        structured_call: StructuredCall | None = None,
        user_id: str | None = None,
    ) -> None:
        self.model = client.model
        self.text_model = text_model
        #: The writer: every typed value, URL, part judgement and closing answer
        #: is one structured one-shot on the app's own LLM lane, so it runs on
        #: the provider chat runs on, with its retry, fallback and metering.
        self._structured_call = structured_call or canonical_structured_call(user_id)
        self._provider = provider
        self._client = client
        self._browser: BrowserSession | None = None
        self._task: str | None = None
        #: The task split into ordered sub-goals once, at the first decision; Jev
        #: sees only the current one, so a compound task cannot loop on its first part.
        self._plan: list[_PlanStep] | None = None
        #: The plan being written; it needs only the task, so it starts at bind,
        #: while the browser opens the first page.
        self._planning: asyncio.Task[list[_PlanStep]] | None = None
        #: The current part's judgement, left running while the step's action
        #: executes; a done verdict is applied at the next step.
        self._judging: asyncio.Task[bool] | None = None
        self._judging_for: _JudgedState | None = None
        self._plan_index = 0
        #: The state the part was last judged in, so each part is judged once per
        #: state of what was read and done: a new page, a page read to the end, a
        #: new document on a url already read (a wall that cleared into the list),
        #: or an action it may cite (a field filled on the form it is judging).
        self._judged: _JudgedState | None = None
        #: What each finished part produced, in the writer's words: the list a
        #: later part works through, the fact the closing answer reports.
        self._findings: list[str] = []
        #: What the last judgement of the current part found no evidence for, and
        #: the state it judged: the gap is only the run's while the run is in it.
        self._missing: list[str] = []
        self._missing_for: _JudgedState | None = None
        #: Parts whose own site the run has opened; a part opens its site once.
        self._opened_parts: set[int] = set()
        self._history: list[JevHistoryEntry] = []
        self._last_fingerprint: str | None = None
        self._steps = 0
        #: Whether a run blocked on a page may retry it once on the fallback
        #: engine (the runner says so when a fallback host is configured).
        self.fallback_available = False
        #: Where the run resumes on the fallback engine: the page it gave up on, or
        #: the last page it read when the primary engine failed under it.
        self.fallback_url: str | None = None
        #: Where the run resumes after the switch: its first step opens it.
        self._resume_url: str | None = None
        #: Actual gateway-reported spend across this run's decisions (Vercel
        #: reports cost 0 on free allowance); None the moment one decision
        #: arrives without cost metadata, so metering falls back to the table.
        self._gateway_cost_usd: float | None = 0.0
        self._viewport: dict[int, ViewportBox] = {}
        self._done_reasks_left = JEV_DONE_REASK_BUDGET
        self._guidance_allowed: GuidanceGate | None = None
        self._observation: JevObservation | None = None
        self._seen_text = SeenText()
        self._handles = NodeHandles()
        self._shot = None
        #: One-shot: guidance just arrived, so this next step may not give up on it.
        self._blocked_suppressed = False
        #: History length when a stalled page was last acted on, so one stall is one BLOCKED.
        self._stall_handled_at = 0
        #: This browser's back list as the run moved through it, oldest first.
        self._back_list: list[str] = []
        #: What was typed into password fields, kept out of everything people read.
        self._secrets = TypedSecrets()

    def redact(self, text: str) -> str:
        """Return text with every value this run typed into a password field masked."""
        return self._secrets.redact(text)

    def viewport_points(self) -> dict[int, tuple[float, float]]:
        """Return the last observation's on-screen centres by Browser-Use index, for the UI pulse."""
        return {
            index: (round(box.cx, 4), round(box.cy, 4))
            for index, box in self._viewport.items()
            if box.on_screen
        }

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def actual_cost_usd(self) -> float | None:
        """Gateway-reported spend for this run's decisions, or None when any decision lacked cost metadata."""
        return self._gateway_cost_usd

    @property
    def name(self) -> str:
        return self.model

    @property
    def model_name(self) -> str:
        return self.model

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: object) -> CoreSchema:
        # Browser-Use stores its model in pydantic settings; the Protocol asks for this.
        return core_schema.any_schema()

    def bind(
        self, browser: BrowserSession, task: str, guidance_allowed: GuidanceGate | None = None
    ) -> None:
        """Give the policy the session whose observations it decides on, the raw goal, and the gate that says whether a blocked step may ask the agent for guidance."""
        self._browser = browser
        self._task = task
        self._guidance_allowed = guidance_allowed
        defer_screenshots_for(browser)
        if self._plan is None and self._planning is None:
            self._planning = asyncio.create_task(self._build_plan(task))

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: None = None, **kwargs: object
    ) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T], **kwargs: object
    ) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None, **kwargs: object
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        if output_format is None or not _is_agent_output(output_format):
            return await self.text_model.ainvoke(messages, output_format, **kwargs)
        return await self._decide(messages, output_format)

    async def _decide(
        self, messages: list[BaseMessage], output_format: type[T]
    ) -> ChatInvokeCompletion[T]:
        observation = await self._observe_step()
        await self._ensure_plan()
        goal = self._effective_goal(messages)
        registered = _registered_actions(output_format)
        self._steps += 1
        if self._resume_url is not None:
            # First step on the fallback engine: back to the page the run could
            # not pass, with the plan, findings and history it already has.
            url, self._resume_url = self._resume_url, None
            return self._direct(output_format, url, observation)
        # Only a step that ends or hands off the run waits for the part check (10-30 s
        # of writer reasoning once held every click); a check still running when the
        # action goes out is applied at the next step.
        judging = self._judgement(observation, goal)
        opening, offered = self._step_options(observation, registered)
        stalled = self._page_stalled()
        # A judgement already done here is a done part not yet applied: no choice needed.
        choosing = (
            asyncio.create_task(self._choose(observation, goal, offered))
            if opening is None and not stalled and not judging.done()
            else None
        )
        chosen = await _settled(choosing)
        answering: asyncio.Task[_ClosingAnswer | None] | None = None
        if chosen is not None and chosen.operation is JevOperation.DONE and self._on_last_part():
            # Written while the checks decide whether the run ends; dropped if not.
            answering = asyncio.create_task(self._closing_answer(observation, goal))
        # A DONE is settled by its own check on the pages read now; a judgement
        # still running on older pages is left to the next step, not waited out.
        stale = (
            chosen is not None
            and chosen.operation is JevOperation.DONE
            and self._judging_for != self._read_state()
        )
        if (
            judging.done()
            or stalled
            or (chosen is not None and chosen.operation in _WAITS_FOR_JUDGEMENT and not stale)
        ):
            while await judging:
                self._judging = None
                _discard(choosing)
                choosing = None
                if not self._advance_plan():
                    # The writer judged the last part complete: finish with the summary,
                    # without waiting for Jev to reach the same conclusion by chance.
                    return await self._finish(
                        observation, goal, registered, output_format, answering
                    )
                # The next part is judged on the same pages at once: the page that
                # finished one part often answers the next, and waiting for another
                # page once spent 24 steps clicking around an article already open.
                goal = self._effective_goal(messages)
                opening, offered = self._step_options(observation, registered)
                judging = self._judgement(observation, goal)
        if opening is not None:
            # A new part starts on a site of its own; open it outright instead of
            # spending a decision and a URL answer on what the plan already knows.
            return self._direct(output_format, opening, observation)
        if self._page_stalled():
            return await self._stalled_step(output_format, observation, goal, registered)
        try:
            settled = await self._settle_choice(
                messages, observation, _PendingChoice(goal, offered, choosing, answering)
            )
            action, text = await self._action_for(
                settled.decision, observation, settled.goal, registered, settled.answering
            )
        except (JevDecisionError, JevGatewayError) as exc:
            return self._rejected_step(output_format, exc)
        return self._decided_step(output_format, settled.decision, action, text, observation)

    async def _observe_step(self) -> JevObservation:
        """Read the page for the step about to be decided, and record what it shows."""
        if self._browser is None:
            raise BrowserUnavailableError("Jev policy has no browser session bound.")
        t0 = perf_counter()
        state = await self._browser.get_browser_state_summary(cached=True, include_screenshot=False)
        t1 = perf_counter()
        selector_map = getattr(getattr(state, "dom_state", None), "selector_map", None) or {}
        self._handles.on_page(getattr(state, "url", None))
        screen = await read_viewport(self._browser, selector_map, self._handles)
        # Keyed on the page's own url as well as the summary's: a click whose
        # watchdog timed out leaves the summary's url pre-navigation.
        self._handles.on_page(screen.url or getattr(state, "url", None))
        t2 = perf_counter()
        self._viewport = screen.boxes
        # The engine idles while Jev and the text helper think; render the step's
        # photo then, not inside the state read where it queued ahead of the DOM.
        self._shot = asyncio.create_task(self._capture_screenshot())
        live = await read_live_values(self._browser)
        t3 = perf_counter()
        observation = self._secrets.mask_fields(observe(state, live, screen))
        t4 = perf_counter()
        log.info(
            f"{LogTag.BROWSER} Jev step input built",
            step=self._steps + 1,
            state_ms=round((t1 - t0) * 1000),
            viewport_ms=round((t2 - t1) * 1000),
            live_values_ms=round((t3 - t2) * 1000),
            observe_ms=round((t4 - t3) * 1000),
            elements=len(observation.elements),
        )
        self._observation = observation
        self._seen_text.record(
            observation.url,
            observation.text,
            observation.title,
            at_bottom=observation.at_bottom is True,
        )
        self._settle_previous_step(observation)
        return observation

    async def _stalled_step(
        self,
        output_format: type[T],
        observation: JevObservation,
        goal: str,
        registered: set[str],
    ) -> ChatInvokeCompletion[T]:
        """Block the run on a page nothing has changed for a whole run of steps.

        A search form the engine cannot submit once took 38 steps; the run is
        blocked here, whatever Jev would pick next.
        """
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
        )

        self._stall_handled_at = len(self._history)
        log.info(
            f"{LogTag.BROWSER} Jev page stalled",
            step=self._steps,
            stalled_steps=_STALLED_STEPS,
            url=observation.url[:80],
        )
        decision = JevDecision(operation=JevOperation.BLOCKED, confidence=1.0)
        action, text = await self._action_for(decision, observation, goal, registered)
        self._remember(decision.label, "blocked", text, url=observation.url)
        return ChatInvokeCompletion(
            completion=_output(
                output_format, action, decision.label, f"Step {self._steps}: BLOCKED"
            ),
            usage=None,
        )

    async def _settle_choice(
        self, messages: list[BaseMessage], observation: JevObservation, pending: _PendingChoice
    ) -> _SettledChoice:
        """Return Jev's decision for the step, a DONE held to the part's evidence check first."""
        goal, offered, answering = pending.goal, pending.offered, pending.answering
        decision = await (pending.choosing or self._choose(observation, goal, offered))
        if decision.operation is not JevOperation.DONE:
            return _SettledChoice(decision, goal, answering)
        if answering is None and self._on_last_part():
            answering = asyncio.create_task(self._closing_answer(observation, goal))
        if not await self._part_is_done(observation, goal, done_chosen=True):
            # Jev's DONE is a read of the screen; the evidence check decides. A DONE
            # taken on confidence alone once reported a page still showing "Loading...".
            _discard(answering)
            log.info(
                f"{LogTag.BROWSER} Jev DONE withheld: the part is not done",
                step=self._steps,
                url=observation.url[:80],
            )
            # The check that withheld the DONE may have named what is still needed.
            goal = self._effective_goal(messages)
            decision = await self._choose(observation, goal, offered - {JevOperation.DONE})
            return _SettledChoice(decision, goal, None)
        if self._advance_plan():
            # One part of the task is done; the next part is decided on this
            # same screen instead of ending the run here.
            goal = self._effective_goal(messages)
            decision = await self._choose(observation, goal, offered)
        return _SettledChoice(decision, goal, answering)

    def _rejected_step(
        self, output_format: type[T], exc: JevDecisionError | JevGatewayError
    ) -> ChatInvokeCompletion[T]:
        """Answer a malformed decision or a silent gateway with an idle step.

        A WAIT, not a raise: the failure shows in Jev's next recent_actions,
        while a raise is a Browser-Use step failure, and six of those
        silently narrow the run to done.
        """
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
        )

        log.warning(
            f"{LogTag.BROWSER} Jev decision rejected",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        log.set_ns("browser", llm_error=type(exc).__name__)
        self._remember("WAIT", "error", str(exc))
        fallback = _idle_action(output_format)
        return ChatInvokeCompletion(
            completion=_output(output_format, fallback, next(iter(fallback)).upper(), str(exc)),
            usage=None,
        )

    def _decided_step(
        self,
        output_format: type[T],
        decision: JevDecision,
        action: dict[str, dict[str, object]],
        text: str | None,
        observation: JevObservation,
    ) -> ChatInvokeCompletion[T]:
        """Record the step Jev decided and return it, metered, as Browser-Use's completion."""
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
            ChatInvokeUsage,
        )

        wait_action: _WaitAction = cast(_WaitAction, action)
        kind = (
            "error"
            if wait_action.get("wait") and decision.operation is not JevOperation.WAIT
            else (decision.operation.value.lower())
        )
        self._remember(
            decision.label,
            kind,
            text,
            url=observation.url,
            target_label=decision.element.label if decision.element is not None else None,
        )
        evaluation = decision.evaluation
        if self._gateway_cost_usd is not None:
            cost = evaluation.gateway_cost_usd if evaluation is not None else None
            self._gateway_cost_usd = (self._gateway_cost_usd + cost) if cost is not None else None
        served_by = (evaluation.provider if evaluation else None) or self._provider
        log.info(
            f"{LogTag.BROWSER} Jev step decided",
            step=self._steps,
            provider=served_by,
            operation=decision.operation.value,
            target=decision.target,
            confidence=round(decision.confidence, 3),
            latency_ms=evaluation.latency_ms if evaluation else None,
            url=observation.url[:80],
        )
        usage = evaluation.usage if evaluation else None
        return ChatInvokeCompletion(
            completion=_output(
                output_format,
                action,
                self._next_goal(decision),
                f"Step {self._steps}: {decision.label} (p={decision.confidence:.2f})",
            ),
            usage=ChatInvokeUsage(
                prompt_tokens=usage.input_tokens,
                prompt_cached_tokens=None,
                prompt_cache_creation_tokens=None,
                prompt_image_tokens=None,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
            )
            if usage
            else None,
        )

    async def _choose(
        self, observation: JevObservation, goal: str, offered: frozenset[JevOperation]
    ) -> JevDecision:
        """Ask Jev for this step, re-asking without DONE while the run's re-ask budget holds.

        A DONE under the floor ends the run on whatever page is showing, and the
        closing summary then reads like a confident answer to a goal never met.
        """
        if self._missing and JevOperation.GO_BACK in offered:
            # The last check named what the part still needs, and the page the run
            # just left may be where it is done (a form submitted with a field
            # skipped): giving up on a page with no way forward is not the move.
            offered -= {JevOperation.BLOCKED}
        decision = await choose(
            self._client, observation, goal, self._history, offered, self._seen_text.pages
        )
        if (
            decision.operation is not JevOperation.DONE
            or decision.confidence >= JEV_MIN_DONE_CONFIDENCE
            or self._done_reasks_left <= 0
            or not offered - _TERMINAL_OPERATIONS
        ):
            return decision
        log.info(
            f"{LogTag.BROWSER} Jev DONE below the confidence floor; re-asking without it",
            step=self._steps,
            confidence=round(decision.confidence, 3),
        )
        self._done_reasks_left -= 1
        alternative = await choose(
            self._client,
            observation,
            goal,
            self._history,
            offered - {JevOperation.DONE},
            self._seen_text.pages,
        )
        # A re-ask that surfaces only a less sure WAIT spends a whole step (about
        # 6s on a long page) to change nothing; the unsure DONE was the better read.
        return alternative if alternative.confidence >= decision.confidence else decision

    async def _action_for(
        self,
        decision: JevDecision,
        observation: JevObservation,
        goal: str,
        registered: set[str],
        answering: asyncio.Task[_ClosingAnswer | None] | None = None,
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        """Return the Browser-Use action a decision executes as, plus any text the helper wrote.

        answering is a closing answer already being written for this step's DONE.
        """
        action: tuple[dict[str, dict[str, object]], str | None] | None = None
        match decision.operation:
            case JevOperation.DONE | JevOperation.BLOCKED:
                action = await self._terminal_action(
                    decision, observation, goal, registered, answering
                )
            case JevOperation.REQUEST_HUMAN | JevOperation.SOLVE_CAPTCHA:
                action = await self._handoff_action(decision, observation, goal)
            case JevOperation.CLICK | JevOperation.TYPE_TEXT | JevOperation.SELECT:
                action = await self._element_action(decision, observation, goal, registered)
            case (
                JevOperation.SCROLL_UP
                | JevOperation.SCROLL_DOWN
                | JevOperation.WAIT
                | JevOperation.GO_BACK
                | JevOperation.NAVIGATE
            ):
                action = await self._control_action(decision, observation, goal)
        if action is None:
            raise JevDecisionError(f"Jev chose {decision.operation.value} without a usable target.")
        return action

    async def _terminal_action(
        self,
        decision: JevDecision,
        observation: JevObservation,
        goal: str,
        registered: set[str],
        answering: asyncio.Task[_ClosingAnswer | None] | None,
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        if decision.operation is JevOperation.BLOCKED:
            return await self._blocked_action(goal, observation, registered)
        answer = await (answering or self._closing_answer(observation, goal))
        if answer is None:
            # The pages were read but the answer could not be written; saying
            # "completed" here would report a success the user never receives.
            return {"done": {"text": _NO_SUMMARY, "success": False}}, _NO_SUMMARY
        return {"done": {"text": answer.text, "success": answer.achieved}}, answer.text

    async def _closing_answer(
        self, observation: JevObservation, goal: str
    ) -> _ClosingAnswer | None:
        """Write the final message against the whole task, or None when it could not be written."""
        answer = await self._structured(
            _ClosingAnswer,
            DONE_SUMMARY,
            self._effective_goal([], whole_task=True) if self._task else goal,
            observation,
            None,
            _WriterCall(
                seen_text=self._seen_text.all_text,
                whole_history=True,
                timeout=JEV_CLOSING_ANSWER_TIMEOUT_SECONDS,
                hedge_after=JEV_CLOSING_ANSWER_HEDGE_SECONDS,
            ),
        )
        summary = self.redact(answer.text).strip() if answer else ""
        if not answer or not summary:
            return None
        if len(summary) > JEV_SUMMARY_MAX_CHARS:
            log.warning(
                f"{LogTag.BROWSER} Jev closing answer discarded: over the length cap",
                step=self._steps,
                chars=len(summary),
                cap=JEV_SUMMARY_MAX_CHARS,
            )
            return None
        return answer.model_copy(update={"text": summary})

    async def _blocked_action(
        self, goal: str, observation: JevObservation, registered: set[str]
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        """Ask the agent that started the run how to proceed, or end the run failed when nobody can answer."""
        unopened = self._page_that_never_opened(observation)
        if self.fallback_available and self.fallback_url is None and not unopened:
            # Before giving up on a page, try it once on the fallback engine: a
            # page the primary engine renders wrongly is not a page with no way
            # forward. A site that does not resolve is not an engine problem.
            self.fallback_url = observation.url
            log.set_ns("browser", fallback_reason=BROWSER_FALLBACK_PAGE_BLOCKED)
            return {"done": {"text": BROWSER_RUN_BLOCKED_SUMMARY, "success": False}}, None
        action = BrowserHandoffAction.REQUEST_AGENT_GUIDANCE
        if action not in registered or not await self._may_ask_for_guidance():
            blocked = BrowserRunFailure.NEVER_OPENED if unopened else BrowserRunFailure.BLOCKED
            log.set_ns("browser", blocked=blocked.value)
            if unopened:
                # A site that never loaded is what blocked the run; "no way
                # forward on this page" would describe a blank tab instead.
                text = f"I couldn't open {unopened}: the page never loaded."
                return {"done": {"text": text, "success": False}}, text
            if self._seen_text.pages:
                # A blocked run that read pages reports what they held and what it
                # could not finish; "no way forward" once threw away a front page
                # and an article already read.
                answer = await self._closing_answer(observation, goal)
                if answer is not None:
                    return {"done": {"text": answer.text, "success": False}}, answer.text
            return {"done": {"text": BROWSER_RUN_BLOCKED_SUMMARY, "success": False}}, None
        # With reasoning on, half the replies were prose with no tool call (measured).
        reason = await self._field_text(
            GUIDANCE_REASON, goal, observation, None, reasoning=ReasoningLevel.OFF
        )
        text = self.redact(reason) if reason else _DEFAULT_GUIDANCE_REASON
        return {action: {"reason": text}}, text

    async def _may_ask_for_guidance(self) -> bool:
        return self._guidance_allowed is not None and await self._guidance_allowed()

    async def _handoff_action(
        self, decision: JevDecision, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        if decision.operation is JevOperation.SOLVE_CAPTCHA:
            challenge = await self._field_text(CAPTCHA_CHALLENGE, goal, observation, None)
            text = challenge or _DEFAULT_CAPTCHA_CHALLENGE
            return {BrowserHandoffAction.SOLVE_CAPTCHA_WITH_HELP: {"challenge": text}}, text
        reason = await self._structured(_TakeoverReason, TAKEOVER_REASON, goal, observation, None)
        text = (reason.text if reason else None) or _DEFAULT_TAKEOVER_REASON
        category = reason.category if reason else SensitiveCategory.IRREVERSIBLE.value
        return _takeover(text, category), text

    async def _element_action(
        self, decision: JevDecision, observation: JevObservation, goal: str, registered: set[str]
    ) -> tuple[dict[str, dict[str, object]], str | None] | None:
        """None when the decision named no usable element, which the caller rejects."""
        element = decision.element
        if element is None:
            return None
        match decision.operation:
            case JevOperation.CLICK:
                return {"click": {"index": element.browser_index}}, None
            case JevOperation.TYPE_TEXT:
                value = await self._field_value(goal, observation, element)
                if value is None:
                    # A value the goal did not supply is never invented; the human
                    # supplies it instead, per the takeover policy.
                    return _takeover(f"Enter the {element.label}"), None
                input_action = "input" if "input" in registered else "input_text"
                action = {
                    input_action: {"index": element.browser_index, "text": value, "clear": True}
                }
                if element.secret:
                    self._secrets.add(value, element.browser_index)
                    return action, JEV_SECRET_MASK
                return action, value
            case JevOperation.SELECT if decision.option is not None:
                return {
                    "select_dropdown": {
                        "index": element.browser_index,
                        "text": decision.option.label,
                    }
                }, decision.option.label
        return None

    async def _control_action(
        self, decision: JevDecision, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None] | None:
        """None when the operation is not one of the controls, which the caller rejects."""
        match decision.operation:
            case JevOperation.SCROLL_UP:
                return {"scroll": {"down": False, "pages": 1.0}}, None
            case JevOperation.SCROLL_DOWN:
                return {"scroll": {"down": True, "pages": 1.0}}, None
            case JevOperation.WAIT:
                return self._wait_action(observation), None
            case JevOperation.GO_BACK:
                return {"go_back": {}}, None
            case JevOperation.NAVIGATE:
                return await self._navigate_action(observation, goal)
        return None

    def _wait_action(self, observation: JevObservation) -> dict[str, dict[str, object]]:
        """Wait longer the more waits in a row this page has already had."""
        waited = 0
        for entry in reversed(self._history):
            if entry.kind != "wait" or page_key(entry.url) != page_key(observation.url):
                break
            waited += 1
        seconds = JEV_WAIT_SECONDS[min(waited, len(JEV_WAIT_SECONDS) - 1)]
        # +1: Browser-Use sleeps one second less than asked.
        return {"wait": {"seconds": seconds + 1}}

    async def _navigate_action(
        self, observation: JevObservation, goal: str
    ) -> tuple[dict[str, dict[str, object]], str | None]:
        """Open the part's own site, or the URL the goal implies; a no-op wait when there is none."""
        if self._off_part_site(observation) and self._plan is not None:
            # Back to the part's own site: the plan already names it.
            part_url = cast(str, self._plan[self._plan_index].url)
            return {"navigate": {"url": part_url, "new_tab": False}}, part_url
        url = await self._field_text(URL_VALUE, goal, observation, None)
        if not url or not url.lower().startswith(("http://", "https://")):
            return {"wait": {"seconds": 1}}, "NAVIGATE needs a URL the goal implies; none found"
        if _same_page(url, observation.url):
            # Browser-Use's wait(1) sleeps zero seconds: opening the page
            # already showing would spend a step on nothing at all.
            return {
                "wait": {"seconds": 1}
            }, f"NAVIGATE to {url} is the page already open; nothing to load"
        return {"navigate": {"url": url, "new_tab": False}}, url

    async def _field_text(
        self,
        instructions: str,
        goal: str,
        observation: JevObservation,
        field: JevElement | None,
        reasoning: ReasoningLevel | None = None,
    ) -> str | None:
        answer = await self._structured(
            _TextValue, instructions, goal, observation, field, _WriterCall(reasoning=reasoning)
        )
        return self._usable_text(answer)

    async def _field_value(
        self, goal: str, observation: JevObservation, field: JevElement
    ) -> str | None:
        """Return the value to type, None when the goal supplies none; a failed call raises.

        A failure is not a missing value: it idles the step for a retry rather than
        handing the user a field the goal already filled.
        """
        try:
            answer = await self._ask(_TextValue, TEXT_VALUE, goal, observation, field)
        except Exception as exc:
            raise JevDecisionError(
                f"The value for {field.label} could not be written ({type(exc).__name__})."
            ) from exc
        return self._usable_text(answer)

    def _usable_text(self, answer: _TextValue | None) -> str | None:
        value = answer.text if answer else None
        if not value or not value.strip():
            return None
        if len(value) > JEV_TEXT_VALUE_MAX_CHARS:
            log.warning(
                f"{LogTag.BROWSER} Jev text helper value discarded: over the length cap",
                step=self._steps,
                chars=len(value),
                cap=JEV_TEXT_VALUE_MAX_CHARS,
            )
            return None
        return value

    async def _structured(
        self,
        output: type[T],
        instructions: str,
        goal: str,
        observation: JevObservation | None,
        field: JevElement | None,
        call: _WriterCall = _DEFAULT_WRITER_CALL,
    ) -> T | None:
        """Return the writer's answer, or None once its lane has given up (logged once here)."""
        try:
            return await self._ask(output, instructions, goal, observation, field, call)
        except Exception as exc:
            log.warning(
                f"{LogTag.BROWSER} Jev text helper failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return None

    async def _ask(
        self,
        output: type[T],
        instructions: str,
        goal: str,
        observation: JevObservation | None,
        field: JevElement | None,
        call: _WriterCall = _DEFAULT_WRITER_CALL,
    ) -> T:
        """Goal, field, page and recent actions in; one small JSON value out."""
        context: dict[str, object] = {
            "goal": goal,
            "field": {"label": field.label, "role": field.role, "value": field.value}
            if field
            else None,
            "page": {"title": observation.title, "url": observation.url, "text": observation.text}
            if observation
            else None,
            "recent_actions": [
                {"action": h.action, "text": h.text, "page_changed": h.page_changed}
                for h in (
                    self._history[-JEV_CLOSING_ANSWER_ACTIONS:]
                    if call.whole_history
                    else self._history[-JEV_TEXT_HELPER_RECENT_ACTIONS:]
                )
            ],
            "latest_note": self._latest_note(),
            # What is already done, so a URL or a closing answer is written for
            # the part of the goal that is left, not the part already read.
            "pages_read": self._seen_text.pages,
            "findings": self._findings,
        }
        if call.seen_text:
            context["seen_on_pages_read"] = call.seen_text
        if call.start_page:
            context["start_page"] = call.start_page
        t0 = perf_counter()
        label = call.label or f"browser_{output.__name__.strip('_').lower()}"
        prompt = [SystemMessage(content=instructions), HumanMessage(content=json.dumps(context))]
        parsed = await first_answer(
            lambda: self._structured_call(
                output, prompt, label=label, timeout=call.timeout, reasoning=call.reasoning
            ),
            hedge_after=call.hedge_after,
            deadline=call.timeout,
        )
        answer = next(iter(parsed.model_dump().values()), None)
        log.info(
            f"{LogTag.BROWSER} Jev text helper answered",
            step=self._steps,
            label=label,
            text_ms=round((perf_counter() - t0) * 1000),
            value_chars=len(str(answer)) if answer is not None else 0,
        )
        return parsed

    def note_from_user(self, note: str | None) -> None:
        """Attach what the user said when handing the browser back to the step that asked.

        The takeover step is the last history entry: _remember runs inside
        _decide, before Browser-Use executes the action that blocks on the human.
        """
        self._attach_note(note, JevNoteSource.USER)

    def note_from_agent(self, note: str | None) -> None:
        """Attach the instruction the agent that started the run sent back to the blocked step that asked for it."""
        self._attach_note(note, JevNoteSource.AGENT)
        self._blocked_suppressed = bool(note)

    def _attach_note(self, note: str | None, source: JevNoteSource) -> None:
        if not self._history:
            raise RuntimeError("No step to attach a note to")
        self._history[-1] = replace(
            self._history[-1], note=note, note_source=source if note else None
        )

    async def take_step_screenshot(self) -> str | None:
        """Return the photo captured for the step being decided, base64 PNG, or None."""
        if self._shot is None:
            return None
        shot, self._shot = self._shot, None
        return await shot

    async def _capture_screenshot(self) -> str | None:
        if self._browser is None:
            return None
        try:
            t0 = perf_counter()
            raw = await self._browser.take_screenshot()
            log.info(
                f"{LogTag.BROWSER} Jev step screenshot captured",
                size_kb=len(raw) // 1024,
                capture_ms=round((perf_counter() - t0) * 1000),
            )
            return base64.b64encode(raw).decode()
        except Exception as exc:  # a missing photo must never cost the step
            log.warning(
                f"{LogTag.BROWSER} Jev step screenshot failed", error_type=type(exc).__name__
            )
            return None

    def guidance_request(self, reason: str) -> AgentGuidanceRequest:
        """Return what the blocked step shows the agent: the page it is on, what it can see, and what it just tried."""
        observation = self._observation
        return AgentGuidanceRequest(
            reason=reason,
            task=self._task or "",
            url=self.redact(observation.url) if observation else "",
            title=observation.title if observation else "",
            page_text=self.redact(observation.text[:BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS])
            if observation
            else "",
            elements=[
                GuidanceElement(index=e.index, label=e.label, role=e.role)
                for e in (observation.elements if observation else ())[
                    :BROWSER_GUIDANCE_MAX_ELEMENTS
                ]
            ],
            recent_actions=[
                GuidanceAction(action=h.action, page_changed=h.page_changed)
                for h in self._history[-BROWSER_GUIDANCE_RECENT_ACTIONS:]
            ],
            user_notes=[
                h.note for h in self._history if h.note and h.note_source is JevNoteSource.USER
            ],
        )

    def _settle_previous_step(self, observation: JevObservation) -> None:
        if self._history and self._last_fingerprint is not None:
            # replace(), not a rebuild: a note attached to this step must survive.
            self._history[-1] = replace(
                self._history[-1],
                page_changed=observation.fingerprint != self._last_fingerprint,
            )
        self._last_fingerprint = observation.fingerprint
        key = page_key(observation.url)
        went_back = bool(self._history) and self._history[-1].kind == "go_back"
        if went_back and len(self._back_list) >= 2 and self._back_list[-2] == key:
            self._back_list.pop()
        elif not self._back_list or self._back_list[-1] != key:
            self._back_list.append(key)

    async def _ensure_plan(self) -> None:
        if self._plan is not None:
            return
        if self._planning is None:
            self._planning = asyncio.create_task(self._build_plan(self._task or ""))
        self._plan = await self._planning

    async def _build_plan(self, task: str) -> list[_PlanStep]:
        """Split the task into its ordered parts; a single-part task is its own plan.

        A one-part plan decides on the task itself (see _goal_with_plan) and opens
        no site of its own; its goal is only the writer's name for it, or empty.
        """
        plan = await self._structured(_PlanSteps, PLAN_STEPS, task, None, None)
        steps = [
            _PlanStep(goal=s.goal.strip(), url=_https_or_none(s.url))
            for s in (plan.steps if plan else [])
            if s.goal and s.goal.strip()
        ]
        parts = (
            steps[:JEV_PLAN_MAX_STEPS]
            if len(steps) > 1
            else [_PlanStep(goal=steps[0].goal if steps else "")]
        )
        log.info(
            f"{LogTag.BROWSER} Jev plan built",
            steps=len(parts),
            part_urls=[s.url for s in parts],
        )
        return parts

    def _on_last_part(self) -> bool:
        return self._plan is not None and self._plan_index == len(self._plan) - 1

    def _next_goal(self, decision: JevDecision) -> str | None:
        """Return the step's next_goal: the part a finishing step finished (its caption), else Jev's label."""
        if decision.operation is not JevOperation.DONE:
            return decision.label
        return (self._plan[self._plan_index].goal or None) if self._plan else None

    def _judgement(self, observation: JevObservation, goal: str) -> asyncio.Task[bool]:
        """Return the current part's judgement in flight, or start one on the pages read now.

        A finished judgement that found the part done is returned until it is applied.
        """
        held = self._judging
        if held is not None and (not held.done() or (not held.cancelled() and held.result())):
            return held
        self._judging = asyncio.create_task(self._part_is_done(observation, goal))
        self._judging_for = self._read_state()
        return self._judging

    def _read_state(self) -> _JudgedState:
        """Return the part in progress, what has been read and what has been done, the state a judgement is of.

        The actions count: a form is filled on one page, and a gap judged before
        its first field stood for the whole run, so Jev typed the password twenty times.
        """
        pages: list[ReadPage] = self._seen_text.pages
        return (
            self._plan_index,
            tuple((page["url"], page["title"], page["read"]) for page in pages),
            tuple(entry.action for entry in self._history if entry.kind in _EVIDENCE_KINDS),
        )

    async def _part_is_done(
        self, observation: JevObservation, goal: str, *, done_chosen: bool = False
    ) -> bool:
        """Ask the writer whether the current part is complete, once per part and newly read page.

        done_chosen asks again on the current screen whatever was judged
        before: Jev chose DONE, and only this evidence check may accept it.
        """
        state = self._read_state()
        part, read, _ = state
        pages = len(read)
        if pages == 0 or self._plan is None:
            return False
        if not done_chosen and self._judged == state:
            return False
        self._judged = state
        # Reasoning off: 1-3 s instead of 8-33 s a judgement. Without it the judge
        # needs the text read, not the screen alone, to see a list read to the end.
        start_page = self._plan[part].url
        verdict = await self._structured(
            _PartDone,
            PART_DONE,
            goal,
            observation,
            None,
            _WriterCall(
                seen_text=self._seen_text.all_text,
                whole_history=True,
                label="browser_done_check" if done_chosen else None,
                reasoning=ReasoningLevel.OFF,
                start_page=start_page,
            ),
        )
        evidence = [item for item in (verdict.evidence if verdict else []) if item.source.strip()]
        unverified = [
            item.source for item in evidence if not self._holds(item, page_key(start_page))
        ]
        if verdict is not None and part == self._plan_index:
            held = {
                " ".join(item.requirement.casefold().split())
                for item in evidence
                if item.source not in unverified
            }
            self._missing_for = state
            self._missing = [
                r for r in verdict.requirements if " ".join(r.casefold().split()) not in held
            ]
        uncovered = verdict.uncovered() if verdict else []
        done = (
            bool(verdict and verdict.done and verdict.requirements and evidence and not unverified)
            and not uncovered
        )
        if verdict and verdict.done and uncovered:
            log.info(
                f"{LogTag.BROWSER} Jev part claimed done with requirements it cites nothing for",
                step=self._steps,
                part=part + 1,
                uncovered=len(uncovered),
            )
        if verdict and verdict.done and not done:
            log.info(
                f"{LogTag.BROWSER} Jev part claimed done on evidence the run does not hold",
                step=self._steps,
                part=part + 1,
                unverified=unverified[:4],
                cited=len(evidence),
            )
        findings = (verdict.findings if verdict else "").strip()
        if done and findings:
            self._findings.append(f"Part {part + 1}: {findings}")
        cited = [f"{item.kind}: {item.source[:120]}" for item in evidence]
        log.info(
            f"{LogTag.BROWSER} Jev part judged",
            step=self._steps,
            part=part + 1,
            parts=len(self._plan),
            done=done,
            pages_read=pages,
            evidence=cited,
            still_needed=self._missing,
        )
        return done

    def _holds(self, evidence: _Evidence, start_page: str | None) -> bool:
        """Whether the run itself holds this evidence entry, as what the entry says it is.

        An action is one the run took, cited by its action string or by what it
        said; a page is never one. A page counts when it was read, and the part's
        own start page shows facts but is never a page opened from it.
        """
        source = evidence.source.strip()
        taken = source in _citations(self._history)
        if evidence.kind == "action" or (evidence.kind is None and taken):
            return taken
        key = page_key(source)
        pages: list[ReadPage] = self._seen_text.pages
        read = key in {page_key(page["url"]) for page in pages}
        return read and (key != start_page or evidence.kind == "fact")

    def _advance_plan(self) -> bool:
        """Move to the next part of the plan; False when the part just finished was the last."""
        if self._plan is None or self._plan_index >= len(self._plan) - 1:
            return False
        done = self._plan[self._plan_index]
        # A judgement still running is of the part just finished.
        _discard(self._judging)
        self._judging = None
        self._plan_index += 1
        self._missing = []
        self._remember(f"DONE part {self._plan_index}: {done.goal[:80]}", "done_part", None)
        log.info(
            f"{LogTag.BROWSER} Jev plan advanced",
            step=self._steps,
            part=self._plan_index + 1,
            parts=len(self._plan),
        )
        return True

    def _off_part_site(self, observation: JevObservation) -> bool:
        """Whether the current part names a site of its own and the run is not on it.

        A site, not a page: the part's URL is where the part starts, and it
        redirects (en.wikipedia.org lands on /wiki/Main_Page) while the work
        then moves across that site's pages.
        """
        if not self._plan or not self._plan[self._plan_index].url:
            return False
        return _site_of(self._plan[self._plan_index].url) != _site_of(observation.url)

    def _part_opening(self, observation: JevObservation) -> str | None:
        """Return the url that opens a part on its own site, the first time the part runs."""
        if self._plan is None or self._plan_index in self._opened_parts:
            return None
        self._opened_parts.add(self._plan_index)
        part = self._plan[self._plan_index]
        if not part.url or not self._off_part_site(observation):
            return None
        return part.url

    def _direct(
        self,
        output_format: type[T],
        url: str,
        observation: JevObservation,
    ) -> ChatInvokeCompletion[T]:
        """Open url as a step the plan chose itself, recorded like any other step."""
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
        )

        self._remember(f"NAVIGATE {url}", "navigate", url, url=observation.url)
        log.info(
            f"{LogTag.BROWSER} Jev step decided by the plan",
            step=self._steps,
            operation="NAVIGATE",
            url=observation.url[:80],
            target_url=url[:80],
        )
        return ChatInvokeCompletion(
            completion=_output(
                output_format,
                {"navigate": {"url": url, "new_tab": False}},
                f"NAVIGATE {url}",
                f"Step {self._steps}: opening {url}",
            ),
            usage=None,
        )

    async def _finish(
        self,
        observation: JevObservation,
        goal: str,
        registered: set[str],
        output_format: type[T],
        answering: asyncio.Task[_ClosingAnswer | None] | None,
    ) -> ChatInvokeCompletion[T]:
        """End the run with the closing answer, as a DONE the writer decided."""
        from browser_use.llm.views import (  # noqa: PLC0415 -- heavy optional dep
            ChatInvokeCompletion,
        )

        decision = JevDecision(operation=JevOperation.DONE, confidence=1.0)
        action, text = await self._action_for(decision, observation, goal, registered, answering)
        self._remember(decision.label, "done", text, url=observation.url)
        log.info(
            f"{LogTag.BROWSER} Jev step decided by the writer's judgement",
            step=self._steps,
            operation="DONE",
            url=observation.url[:80],
        )
        return ChatInvokeCompletion(
            completion=_output(
                output_format, action, self._next_goal(decision), f"Step {self._steps}: DONE"
            ),
            usage=None,
        )

    def _goal_with_plan(self, goal: str) -> str:
        """Frame the goal as its current part when the task was split, with what the part still needs."""
        # The judge knew each article was read only for its title; Jev, not
        # told, went back to the list for 37 steps.
        # A gap judged before the run's latest action may be what that action did;
        # repeated as still needed, it had Jev fill one field again every step.
        missing = self._missing if self._missing_for == self._read_state() else []
        still_needed = f"{_STILL_NEEDED}{' / '.join(missing)}" if missing else None
        if not self._plan or len(self._plan) == 1:
            # A one-part task is decided on the task itself, and needs to hear the
            # gap too: a form submitted with its radio unchosen was declared BLOCKED.
            return f"{goal}\n{still_needed}" if still_needed else goal
        i, n = self._plan_index, len(self._plan)
        lines = [f"CURRENT PART ({i + 1} of {n}), the only thing to do now: {self._plan[i].goal}"]
        if i:
            lines.append("ALREADY DONE, never redo: " + " / ".join(s.goal for s in self._plan[:i]))
        if self._findings:
            lines.append(
                "FOUND SO FAR, what the parts done produced: " + " | ".join(self._findings)
            )
        if still_needed:
            lines.append(still_needed)
        if i < n - 1:
            lines.append(
                "STILL TO DO AFTER THIS PART, not yet: "
                + " / ".join(s.goal for s in self._plan[i + 1 :])
            )
        lines.append(
            "DONE means this current part is complete; the parts after it come next. "
            f"FULL TASK for reference: {goal}"
        )
        return "\n".join(lines)

    def _effective_goal(self, messages: list[BaseMessage], *, whole_task: bool = False) -> str:
        """Return the goal to decide and answer against: what the user changed, how to proceed, then the task.

        The user's instruction leads and says it overrides -- appended at the end
        it read as an aside, and the closing answer reported the original task as
        unfinished instead. Agent guidance only says how to proceed, so it never
        displaces what the user asked for.
        """
        task = self._task or _goal_from_messages(messages)
        # The closing answer is written against the whole task, every part of
        # it; a decision is made against the part in progress.
        goal = task if whole_task else self._goal_with_plan(task)
        user_note = self._latest_note_from(JevNoteSource.USER)
        agent_note = self._latest_note_from(JevNoteSource.AGENT)
        if not user_note and not agent_note:
            return goal
        lines = []
        if user_note:
            lines.append(
                f"Latest instruction from the user, which overrides the task below: {user_note}"
            )
        if agent_note:
            lines.append(
                "Guidance from the assistant that planned this task, on how to proceed: "
                f"{agent_note}"
            )
        lines.append(f"{'Original task' if user_note else 'Task, which still stands'}: {goal}")
        return "\n".join(lines)

    def _latest_note_from(self, source: JevNoteSource) -> str | None:
        return next(
            (h.note for h in reversed(self._history) if h.note and h.note_source is source), None
        )

    def _latest_note(self) -> str | None:
        return next((h.note for h in reversed(self._history) if h.note), None)

    def _page_that_never_opened(self, observation: JevObservation) -> str | None:
        """Return the URL of the last navigate that left the run on a blank tab, if it is still there."""
        if not observation.url.startswith("about:"):
            return None
        return next(
            (
                h.text
                for h in reversed(self._history)
                if h.kind == "navigate" and h.page_changed is False
            ),
            None,
        )

    def _step_options(
        self, observation: JevObservation, registered: set[str]
    ) -> tuple[str | None, frozenset[JevOperation]]:
        """Return the url that opens the current part, if any, and the operations offered on this page."""
        opening = self._part_opening(observation)
        offered = _offered_operations(registered)
        if self._latest_note_from(JevNoteSource.USER):
            # The user answered a takeover with an instruction; handing the same step
            # back ignores what they said, then blames them when it times out. A later
            # agent note says how to proceed and never restores what they declined.
            offered -= _HANDOFF_OPERATIONS
        if self._blocked_suppressed:
            # The agent just said how to proceed; giving up on the same step would
            # spend a guidance round and never try what it said.
            offered -= {JevOperation.BLOCKED}
            self._blocked_suppressed = False
        last = self._history[-1] if self._history else None
        if any(
            entry.kind == "error"
            and entry.action.startswith(JevOperation.NAVIGATE.value)
            and page_key(entry.url) == page_key(observation.url)
            for entry in self._history
        ):
            # The helper found no URL to write from this page; asking again on
            # the same page gets the same answer and spends a step on a wait
            # that sleeps nothing.
            offered -= {JevOperation.NAVIGATE}
        if self._off_part_site(observation):
            # Off the part's own site; the plan knows the way back, so NAVIGATE
            # is a direct move there (see _control_action), and never a blank.
            offered |= {JevOperation.NAVIGATE} & _offered_operations(registered)
        if observation.at_bottom:
            # Nothing is further down; an offered scroll there is a step that changes nothing.
            offered -= {JevOperation.SCROLL_DOWN}
        if len(self._back_list) < 2 or self._back_list[-2].startswith("about:"):
            # Back from this browser's first page lands on the blank tab it opened
            # on: after the engine switch, GO_BACK and then clicks on about:blank ended a run.
            offered -= {JevOperation.GO_BACK}
        if last is not None and last.kind == "go_back":
            # Two backs in a row is never the plan: the first one landed somewhere,
            # and the run decides from there; twenty of them once spent a whole run.
            offered -= {JevOperation.GO_BACK}
        return opening, offered - _stalled_operations(self._history)

    def fall_back_after_engine_failure(self) -> None:
        """Resume on the fallback engine at the last page the run read, since the primary engine failed under it.

        A run that never read a page has nowhere to resume and starts the task over.
        """
        self.fallback_url = _https_or_none(self._observation.url if self._observation else None)

    def continue_on_fallback(self) -> None:
        """Resume on a fresh browser at the page the run gave up on, keeping plan, findings and history."""
        self._resume_url = self.fallback_url
        self.fallback_available = False
        self._handles = NodeHandles()
        self._last_fingerprint = None
        self._shot = None
        self._back_list = []

    def _page_stalled(self) -> bool:
        return _page_stalled_in(self._history, self._stall_handled_at)

    def _remember(
        self,
        action: str,
        kind: str,
        text: str | None,
        *,
        url: str | None = None,
        target_label: str | None = None,
    ) -> None:
        self._history.append(
            JevHistoryEntry(action=action, kind=kind, text=text, url=url, target_label=target_label)
        )


def _citations(history: list[JevHistoryEntry]) -> set[str]:
    """Every string that names an action the run took: its action string, its text, or both."""
    cited = {entry.action for entry in history}
    for entry in history:
        if entry.text:
            cited |= {entry.text.strip(), f"{entry.action}: {entry.text.strip()}"}
    return cited


_STALLED_STEPS = 8
_STILL_NEEDED = "STILL NEEDED FOR THIS PART, what the last check found nothing for: "
_PRODUCTIVE_KINDS = frozenset({"type_text", "select", "done_part"})


def _page_stalled_in(history: list[JevHistoryEntry], since: int) -> bool:
    """Whether the last steps all left one page as it was, none of them entering anything."""
    recent = history[since:][-_STALLED_STEPS:]
    if len(recent) < _STALLED_STEPS:
        return False
    first = page_key(recent[0].url)
    return all(
        entry.page_changed is False
        and entry.kind not in _PRODUCTIVE_KINDS
        and page_key(entry.url) == first
        for entry in recent
    )


async def _settled(task: asyncio.Task[JevDecision] | None) -> JevDecision | None:
    """Wait for Jev's choice without raising; a failed choice re-raises where the step awaits it."""
    if task is None:
        return None
    await asyncio.wait({task})
    return None if task.exception() else task.result()


def _discard(task: asyncio.Task[_R] | None) -> None:
    """Drop speculative work the step made moot, collecting its error if it had one."""
    if task is None:
        return
    if not task.done():
        task.cancel()
    elif not task.cancelled():
        task.exception()


def _stalled_operations(history: list[JevHistoryEntry]) -> frozenset[JevOperation]:
    """Operations whose last two uses changed nothing on the page, so a third would not either."""
    if len(history) < 2:
        return frozenset()
    last, before = history[-1], history[-2]
    if last.page_changed is not False or before.page_changed is not False:
        return frozenset()
    if last.kind != before.kind or last.kind in ("wait", "error", "done_part"):
        return frozenset()
    return frozenset(op for op in JevOperation if op.value.lower() == last.kind)


def _same_page(target: str, current: str) -> bool:
    """Return whether the URL to open is the document already showing, fragment aside."""
    return page_key(target) == page_key(current)


_NO_SUMMARY = "I read the pages but could not write the closing answer."


def _site_of(url: str | None) -> str:
    """Return the host a URL is on, so a part's site matches every page of it."""
    return urlsplit(url or "").netloc.lower().removeprefix("www.")


def _https_or_none(url: str | None) -> str | None:
    value = (url or "").strip()
    return value if value.lower().startswith(("http://", "https://")) else None


def _takeover(
    reason: str, category: str = SensitiveCategory.IRREVERSIBLE.value
) -> dict[str, dict[str, object]]:
    return {BrowserHandoffAction.REQUEST_HUMAN_TAKEOVER: {"reason": reason, "category": category}}


def _idle_action(output_format: type[BaseModel]) -> dict[str, dict[str, object]]:
    """Return an action that changes nothing and is valid for this step's schema."""
    if "wait" in _registered_actions(output_format):
        return {"wait": {"seconds": 1}}
    return {"done": {"text": BROWSER_RUN_BLOCKED_SUMMARY, "success": False}}


def _is_agent_output(output_format: type[BaseModel]) -> bool:
    return "action" in getattr(output_format, "model_fields", {})


def _offered_operations(registered: set[str]) -> frozenset[JevOperation]:
    """Only operations whose Browser-Use action is registered for this run are offered."""
    return frozenset(
        op for name, ops in _OPERATIONS_BY_ACTION.items() if name in registered for op in ops
    )


def _registered_actions(output_format: type[BaseModel]) -> set[str]:
    """Return the action names in AgentOutput.action's element model.

    Browser-Use builds that model two ways: one model with an optional field per
    action, or (0.11+) a RootModel over a union of single-field models.
    """
    action_fields: _ActionField = cast(_ActionField, output_format.model_fields)
    action_model = get_args(action_fields["action"].annotation)[0]
    fields: _RootField = cast(_RootField, getattr(action_model, "model_fields", {}))
    if "root" not in fields:
        return set(fields)
    members = get_args(fields["root"].annotation) or (fields["root"].annotation,)
    return {name for member in members for name in getattr(member, "model_fields", {})}


def _output(
    output_format: type[T], action: dict[str, dict[str, object]], goal: str | None, memory: str
) -> T:
    return output_format.model_validate({"memory": memory, "next_goal": goal, "action": [action]})


def _goal_from_messages(messages: list[BaseMessage]) -> str:
    """Return the task as Browser-Use's own prompt carries it, for an unbound adapter."""
    for message in reversed(messages):
        text = getattr(message, "text", None)
        if not isinstance(text, str):
            continue
        match = _USER_REQUEST.search(text)
        if match:
            return match.group(1).strip()
    return ""


def build_jev_chat_model(*, text_model: BaseChatModel, user_id: str | None = None) -> JevChatModel:
    """Return the Jev policy over the configured gateway, with text_model as its text helper.

    BROWSER_JEV_PROVIDER selects "openrouter" (default) or "vercel" (Vercel AI
    Gateway). Raises BrowserUnavailableError when the selected gateway's key
    is not configured.
    """
    provider = settings.BROWSER_JEV_PROVIDER
    if provider == "vercel":
        if not settings.BROWSER_JEV_VERCEL_API_KEY:
            raise BrowserUnavailableError(
                "Jev provider is vercel but BROWSER_JEV_VERCEL_API_KEY is not set."
            )
    elif not settings.OPENROUTER_API_KEY:
        raise BrowserUnavailableError("Jev is enabled but OPENROUTER_API_KEY is not set.")
    gateways = {
        name: client
        for name, client in (("vercel", _vercel_client()), ("openrouter", _openrouter_client()))
        if client is not None
    }
    primary = gateways.pop(provider)
    fallback = next(iter(gateways.values()), None)
    client: JevDecisionsClient = (
        JevFailoverClient(primary=primary, fallback=fallback) if fallback is not None else primary
    )
    log.info(
        f"{LogTag.BROWSER} Jev gateway wired",
        provider=provider,
        fallback_provider=fallback.provider if fallback is not None else None,
    )
    return JevChatModel(client=client, text_model=text_model, provider=provider, user_id=user_id)


def _vercel_client() -> JevGatewayClient | None:
    if not settings.BROWSER_JEV_VERCEL_API_KEY:
        return None
    return JevGatewayClient(
        api_key=settings.BROWSER_JEV_VERCEL_API_KEY,
        model=settings.BROWSER_JEV_VERCEL_MODEL,
        url=_JEV_VERCEL_EVALUATE_URL,
        provider="vercel",
    )


def _openrouter_client() -> JevGatewayClient | None:
    if not settings.OPENROUTER_API_KEY:
        return None
    return JevGatewayClient(
        api_key=settings.OPENROUTER_API_KEY,
        model=settings.BROWSER_USE_JEV_MODEL,
        url=_JEV_DECISIONS_URL,
        provider="openrouter",
    )


__all__ = ["JevChatModel", "JevGatewayError", "build_jev_chat_model"]
