"""Drive one browser task: Jev first on the whole task, then the Browser-Use agent steers and finishes.

One long-lived Browser-Use Agent runs on the reasoning model with Jev registered
as its jev action. The Agent's initial action is a Jev burst on the whole
task, so the first model call the agent makes already reads what Jev did. The
agent then writes the answer, hands Jev a sharper goal, or acts itself; it is
the only finisher and the only answer writer. Every agent step and every Jev
burst reaches the runner as one frame through RunHooks. A run resumed on the
fallback engine carries the primary agent's state instead of a new Jev burst.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from itertools import compress
from time import perf_counter
from typing import Any, TypedDict, cast

from browser_use import Agent, Browser
from browser_use.agent.views import ActionResult, AgentHistoryList, AgentOutput, AgentState
from browser_use.browser.events import BrowserConnectedEvent, NavigationCompleteEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary
from pydantic import BaseModel, TypeAdapter

from app.constants.browser import (
    BROWSER_ANSWER_AFTER_STEP,
    BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS,
    BROWSER_ENGINE_RESUMED_NOTE,
    BROWSER_GUIDANCE_MAX_ELEMENTS,
    BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS,
    BROWSER_GUIDANCE_RECENT_ACTIONS,
    BROWSER_NO_GUIDANCE_AVAILABLE,
    BROWSER_TAKEOVER_DONE_NOTE,
    EngineSwitchReason,
    SensitiveCategory,
)
from app.constants.log_tags import LogTag
from app.patches.browser_use_run_lock_patch import isolate_run_events
from app.schemas.browser import (
    AgentGuidanceRequest,
    BrowserAction,
    BrowserActionOutput,
    GuidanceAction,
    GuidanceElement,
)
from app.services.browser.agent_options import agent_options, browser_options
from app.services.browser.captions import burst_caption, caption_from_action_list, step_caption
from app.services.browser.exceptions import (
    BrowserAutomationError,
    BrowserHandoffCancelled,
    BrowserUnavailableError,
)
from app.services.browser.jev.gateway import open_jev_client
from app.services.browser.jev.loop import BurstContext, JevRunner
from app.services.browser.jev.page import JevPage, PageAction
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.jev.tool import JEV_ACTION, JevDelegate, register_jev
from app.services.browser.ledger import CallComponent, ExecutedAction, RunLedger
from app.services.browser.llm import build_agent_llm, build_text_model
from app.services.browser.run_contract import (
    BrowserRunConfig,
    RunHooks,
    RunOutcome,
    StepClock,
    StepFrame,
    SwitchEngineFn,
)
from app.services.browser.session import BrowserHostSession
from app.services.browser.stalled_loads import StalledLoads
from app.services.browser.tools import build_browser_tools
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

# Attributes worth naming an otherwise-unlabelled control by, in the order a
# person would recognise it. `value` covers <input type="submit" value="Submit">.
_LABEL_ATTRIBUTES = ("aria-label", "value", "title", "placeholder", "alt", "name", "id")

_OUTPUT_MAX_CHARS = 1000
#: Browser-Use's typing action.
_INPUT_ACTION = "input"

#: Caption for a step that failed before it picked an action to describe.
STEP_ERROR_CAPTION = "That step failed"


class _ActionInputs(TypedDict, total=False):
    """One Browser-Use action's arguments, read only for the element it targets."""

    index: int


class _InputInputs(_ActionInputs, total=False):
    """Browser-Use's input action: the element it types into and the text."""

    text: str


class _FieldAttributes(TypedDict, total=False):
    """The HTML attributes of a form control read here: its input type."""

    type: str


_ACTION_INPUTS: TypeAdapter[_ActionInputs] = TypeAdapter(_ActionInputs)
_INPUT_INPUTS: TypeAdapter[_InputInputs] = TypeAdapter(_InputInputs)
_FIELD_ATTRIBUTES: TypeAdapter[_FieldAttributes] = TypeAdapter(_FieldAttributes)


def _element_label(state: BrowserStateSummary, index: int | None) -> str | None:
    """Return the on-page name of the element an action targets, by its DOM index.

    Prefer the accessibility name, then visible text, then labelling
    attributes, then the tag name, so a control is never a bare verb.
    """
    node = state.dom_state.selector_map.get(index) if index is not None else None
    if node is None:
        return None
    candidates = [
        node.ax_node.name if node.ax_node else None,
        node.get_meaningful_text_for_llm(),
        *(node.attributes.get(attr) for attr in _LABEL_ATTRIBUTES),
    ]
    for candidate in candidates:
        text = (candidate or "").strip()
        if text:
            return text
    return node.node_name.strip().lower() or None


def _extract_actions(agent_output: AgentOutput, state: BrowserStateSummary) -> list[BrowserAction]:
    """Return the step's actions as the agent's own tool calls, each with the on-page text of what it targets."""
    actions: list[BrowserAction] = []
    for action in agent_output.action:
        for action_name, params in action.model_dump(exclude_none=True).items():
            raw_inputs = params if isinstance(params, dict) else {}
            typed_inputs: _ActionInputs = _ACTION_INPUTS.validate_python(raw_inputs)
            target = _element_label(state, typed_inputs.get("index"))
            actions.append(BrowserAction(name=action_name, inputs=raw_inputs, target=target))
    return actions


def _password_typed(action: BrowserAction, state: BrowserStateSummary) -> str | None:
    """Return what a Browser-Use input action types into a password field, or None for any other action."""
    if action.name != _INPUT_ACTION:
        return None
    typed_inputs: _InputInputs = _INPUT_INPUTS.validate_python(action.inputs)
    index = typed_inputs.get("index")
    node = state.dom_state.selector_map.get(index) if index is not None else None
    if node is None:
        return None
    attributes: _FieldAttributes = _FIELD_ATTRIBUTES.validate_python(node.attributes)
    kind = attributes.get("type")
    if kind is None or kind.lower() != "password":
        return None
    return typed_inputs.get("text")


def _summarize_action_result(result: ActionResult) -> str | None:
    """One action's outcome as short display text, or None when there is nothing worth showing."""
    text = result.error or result.extracted_content or result.long_term_memory or ""
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) <= _OUTPUT_MAX_CHARS:
        return collapsed
    return collapsed[: _OUTPUT_MAX_CHARS - 1].rstrip() + "…"


def _guidance_element(action: PageAction) -> GuidanceElement:
    """Return one control as a guidance ask lists it: its label and role."""
    return GuidanceElement(label=action["label"], role=action.get("role", action["kind"]))


def outcome_from_history(history: AgentHistoryList[BaseModel]) -> tuple[bool, str | None]:
    """Return whether the agent finished successfully, and the answer it wrote."""
    final = history.final_result()
    success = bool(history.is_done() and history.is_successful() is not False)
    return success, final


@dataclass(frozen=True)
class _Step:
    """The agent step in flight: when it started, the actions it picked, and the card of its own."""

    started_at: float
    actions: list[str]
    #: What the step's own actions did, as its card captions them; "" for a step that only hands Jev a goal.
    caption: str
    #: The card showing every action but jev's, whose rows its results land on; None when there is none.
    frame: int | None


@dataclass(frozen=True)
class AgentRunSetup:
    """Who a run works for and what it carries across engines: the user, its ledger and secrets, the steps shown."""

    user_id: str | None
    ledger: RunLedger
    secrets: RunSecrets
    #: A run resumed on the fallback engine numbers on from the steps the user already saw.
    steps_before: int = 0
    #: The primary agent's state, for a run resumed on the fallback engine: it goes on from there.
    resumed_from: AgentState | None = None


class BrowserAgentRun:
    """Run one Browser-Use Agent, with Jev as its first action and its fast operator."""

    def __init__(
        self,
        *,
        session: BrowserHostSession,
        config: BrowserRunConfig,
        hooks: RunHooks,
        setup: AgentRunSetup,
    ) -> None:
        self._session = session
        self._config = config
        self._hooks = hooks
        self._secrets = setup.secrets
        self._ledger = setup.ledger
        self._user_id = setup.user_id
        self._resumed_from = setup.resumed_from
        #: The task as the runner gave it, without the rules the agent is told alongside.
        self._task = ""
        self._agent: Any = None
        self._page: JevPage | None = None
        self._stalls: StalledLoads | None = None
        self._clock = StepClock()
        # A run resumed on the fallback engine numbers on from the steps the user already saw.
        self._frames = setup.steps_before
        self._step: _Step | None = None
        #: What a handoff action asked to wait on; run after its step, so no step budget counts the wait.
        self._wait: Callable[[], Awaitable[str]] | None = None
        #: The last page the run was seen on, for a resume on the fallback engine.
        self.last_url: str | None = None
        #: Whether the agent's browser ever attached to the session over CDP.
        self.connected = False

    @property
    def frames(self) -> int:
        return self._frames

    @property
    def agent_state(self) -> AgentState | None:
        """The agent's state as it stands, for a resume on the fallback engine; None before it is built."""
        return cast(AgentState, self._agent.state) if self._agent is not None else None

    async def execute(self, task: str) -> RunOutcome:
        self._task = task
        # Before any Browser-Use object exists, so every event bus this run
        # starts takes the run's lock, not the process-wide one.
        isolate_run_events()
        try:
            llm = await build_agent_llm(self._user_id, self._ledger)
            text_model = build_text_model(self._ledger)
        except BrowserUnavailableError as exc:
            # The run's event says the model, not the browser, was unusable.
            log.set_ns("browser", llm_error=type(exc).__name__)
            raise
        async with open_jev_client() as client:
            browser = Browser(**browser_options(self._session.cdp_url))
            stalls = self._stalls = StalledLoads(browser)
            browser.event_bus.on(BrowserConnectedEvent, self._on_connected)
            browser.event_bus.on(BrowserConnectedEvent, stalls.attach)
            browser.event_bus.on(NavigationCompleteEvent, stalls.on_navigation_complete)

            def runner_for() -> JevRunner:
                return JevRunner(
                    page=self._page_for(self._agent.browser_session),
                    client=client,
                    text_model=text_model,
                    run=BurstContext(
                        ledger=self._ledger,
                        secrets=self._secrets,
                        stalls=stalls,
                        should_stop=self._hooks.should_stop,
                        user_waiting=self._hooks.user_waiting,
                    ),
                )

            delegate = JevDelegate(runner_for=runner_for, emit=self._emit_burst)
            tools = build_browser_tools(
                solve_captcha=self._config.solve_captcha,
                handle_takeover=self._takeover,
                handle_guidance=self._guidance,
                handle_engine_switch=(
                    partial(self._switch_engine, self._hooks.switch_engine)
                    if self._hooks.switch_engine is not None
                    else None
                ),
            )
            register_jev(tools, delegate)
            self._agent = Agent(
                **agent_options(
                    task, self._config, self._secrets, resumed=self._resumed_from is not None
                ),
                injected_agent_state=self._resumed_state(),
                llm=llm,
                browser=browser,
                tools=tools,
                register_new_step_callback=self._on_step,
                register_should_stop_callback=self._hooks.should_stop,
                page_extraction_llm=text_model,
            )
            try:
                history = await self._agent.run(
                    max_steps=self._config.max_steps,
                    on_step_start=self._on_step_start,
                    on_step_end=self._on_step_end,
                )
            finally:
                stalls.close()
        self.last_url = await self._current_url()
        success, final = outcome_from_history(history)
        summary = self._secrets.redact(final) if final else None
        return RunOutcome(success, summary or "")

    def stop(self) -> None:
        if self._agent is not None:
            self._agent.stop()

    async def connection_answers(self) -> bool:
        """Whether the run's own CDP connection answers a bounded read; True before it opens."""
        browser = self._agent.browser_session if self._agent is not None else None
        if browser is None or not browser.is_cdp_connected:
            return True
        try:
            await asyncio.wait_for(
                browser.cdp_client.send.Target.getTargets(),
                timeout=BROWSER_ENGINE_PROBE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return False
        return True

    async def abandon(self) -> None:
        """Drop the connection to an engine that stopped answering, failing every call still waiting on it."""
        if self._agent is not None:
            await self._agent.browser_session.reset()

    def _on_connected(self, event: BrowserConnectedEvent) -> None:
        del event
        self.connected = True

    def _resumed_state(self) -> AgentState | None:
        """Return the primary agent's state to go on from, told where the run now is, or None for a new run."""
        if self._resumed_from is None:
            return None
        note = BROWSER_ENGINE_RESUMED_NOTE.format(page=self._config.start_url or "a blank page")
        return self._resumed_from.model_copy(
            update={
                "stopped": False,
                "paused": False,
                "consecutive_failures": 0,
                "last_result": [
                    *(self._resumed_from.last_result or []),
                    ActionResult(long_term_memory=self._secrets.mask(note)),
                ],
            }
        )

    def _page_for(self, browser_session: BrowserSession) -> JevPage:
        if self._page is None:
            self._page = JevPage(browser_session)
        return self._page

    async def _current_url(self) -> str | None:
        if self._agent is None:
            return None
        url = await self._agent.browser_session.get_current_page_url()
        return str(url) if url else None

    async def _on_step_start(self, agent: object) -> None:
        """Hand the agent what the user said since its last step, and any load the browser stopped or did not finish."""
        del agent
        for message in await self._hooks.take_user_messages():
            self._agent.message_manager.add_new_task(self._secrets.mask(message))
        if self._stalls is not None and (
            loads := [*self._stalls.take(), *self._stalls.take_unfinished()]
        ):
            # How Browser-Use itself reports a wait between steps: a result the next prompt carries.
            notes = [ActionResult(long_term_memory=self._secrets.mask(note)) for note in loads]
            self._agent.state.last_result = [*(self._agent.state.last_result or []), *notes]

    async def _switch_engine(self, switch: SwitchEngineFn, category: EngineSwitchReason) -> str:
        """Move the run to the full browser: the runner resumes it there once this run stops."""
        answer = await switch(category, await self._current_url())
        self.stop()
        return answer

    async def _takeover(self, reason: str, category: SensitiveCategory) -> str:
        """Hand the browser to the user once this step ends; the agent reads their note before its next step."""
        self._wait = partial(self._user_note, reason, category)
        return BROWSER_ANSWER_AFTER_STEP

    async def _user_note(self, reason: str, category: SensitiveCategory) -> str:
        note = await self._hooks.takeover(reason, category)
        return note or BROWSER_TAKEOVER_DONE_NOTE

    async def _guidance(self, reason: str) -> str:
        """Ask the agent that started this run how to proceed, once this step ends; the hook raises when none answers."""
        allowed = self._hooks.guidance_allowed
        if (
            self._hooks.guidance is None
            or allowed is None
            or self._page is None
            or not await allowed()
        ):
            return BROWSER_NO_GUIDANCE_AVAILABLE
        page = await self._page.observe()
        request = AgentGuidanceRequest(
            reason=reason,
            task=self._task,
            url=self._secrets.redact(page.url),
            title=page.title,
            page_text=self._secrets.redact(page.text)[:BROWSER_GUIDANCE_PAGE_TEXT_MAX_CHARS],
            elements=[
                _guidance_element(action)
                for action in page.actions[:BROWSER_GUIDANCE_MAX_ELEMENTS]
                if "node" in action
            ],
            recent_actions=[
                GuidanceAction(action=a.description)
                for a in self._ledger.actions[-BROWSER_GUIDANCE_RECENT_ACTIONS:]
            ],
        )
        self._wait = partial(self._hooks.guidance, request)
        return BROWSER_ANSWER_AFTER_STEP

    async def _screenshot(self, page: JevPage) -> str | None:
        """Photograph the page for a card, or None when it does not answer: a card never fails its step."""
        try:
            return await page.screenshot()
        except (BrowserAutomationError, RuntimeError) as exc:
            log.warning(f"{LogTag.BROWSER} Step photo not taken", error_type=type(exc).__name__)
            return None

    async def _emit_frame(
        self, *, caption: str, actions: list[BrowserAction], url: str | None, title: str | None
    ) -> None:
        """Emit one card under the next number the user sees, with a photo of the page taken off the step's path."""
        self._frames += 1
        if url:
            self.last_url = url
        photo = (
            spawn_background_task(self._screenshot(self._page), name="browser_step_photo")
            if self._page is not None and self._config.stream_screenshots
            else None
        )
        self._hooks.step(
            StepFrame(
                index=self._frames,
                session_id=self._session.session_id,
                goal=self._secrets.redact(caption),
                actions=[
                    action.model_copy(
                        update={
                            "inputs": {
                                key: self._secrets.redact(value)
                                if isinstance(value, str)
                                else value
                                for key, value in action.inputs.items()
                            }
                        }
                    )
                    for action in actions
                ],
                url=self._secrets.redact(url) if url else url,
                title=title,
                photo=photo,
                since_prev_ms=self._clock.tick(),
            )
        )

    async def _emit_burst(self, actions: list[BrowserAction], url: str, title: str) -> None:
        await self._emit_frame(
            caption=burst_caption(actions), actions=actions, url=url, title=title
        )

    async def _on_step(
        self, browser_state_summary: BrowserStateSummary, agent_output: AgentOutput, n_steps: int
    ) -> None:
        """Fire after the agent picks actions, before they execute: one card for its own actions."""
        del n_steps
        started_at = perf_counter()
        if self._page is None:
            self._page = JevPage(self._agent.browser_session)
        actions = _extract_actions(agent_output, browser_state_summary)
        for action in actions:
            if (typed := _password_typed(action, browser_state_summary)) is not None:
                self._secrets.learn(typed)
        own = [a for a in actions if a.name != JEV_ACTION]
        # A step with no card of its own has no own results to place, so "" would read the same.
        frame: int | None = None  # pragma: no mutate
        # A step that only hands Jev a goal is shown by the burst's own card.
        if own:
            await self._emit_frame(
                caption=step_caption(own, agent_output.next_goal),
                actions=own,
                url=browser_state_summary.url,
                title=browser_state_summary.title,
            )
            frame = self._frames
        self._step = _Step(
            started_at=started_at,
            actions=[a.name for a in actions],
            caption=self._secrets.redact(caption_from_action_list(own)),
            frame=frame,
        )

    async def _on_step_end(self, agent: Agent[None, BaseModel]) -> None:
        """Record the step's actions and mirror their results, then wait on whoever a handoff action asked."""
        await self._record_step(agent.state.last_result or [])
        wait, self._wait = self._wait, None
        if wait is not None:
            agent.state.last_result = [*(agent.state.last_result or []), await self._answer(wait)]

    async def _answer(self, wait: Callable[[], Awaitable[str]]) -> ActionResult:
        """Return what the user or the agent answered, as the result the agent's next prompt carries."""
        try:
            answer = await wait()
        except BrowserHandoffCancelled as exc:
            # The runner has stopped the run; the agent's next stop check ends it.
            return ActionResult(error=f"The handoff ended: {exc}")
        return ActionResult(long_term_memory=self._secrets.mask(answer))

    async def _record_step(self, results: list[ActionResult]) -> None:
        # A step _on_step saw has its card already (or Jev's burst card stands for it).
        step, self._step = self._step, None
        if step is None:
            if any(result.error for result in results):
                await self._emit_frame(caption=STEP_ERROR_CAPTION, actions=[], url=None, title=None)
            return
        # One result per action run, in order; a step cut short has fewer. Jev's burst has its own card.
        own = list(compress(results, (name != JEV_ACTION for name in step.actions)))
        if step.caption:
            self._ledger.executed(
                ExecutedAction(
                    component=CallComponent.AGENT,
                    description=step.caption,
                    duration_ms=round((perf_counter() - step.started_at) * 1000),
                    count=len(own),
                )
            )
        if self._hooks.action_results is None or step.frame is None:
            return
        outputs = [
            BrowserActionOutput(position=position, output=self._secrets.redact(text))
            for position, result in enumerate(own)
            if (text := _summarize_action_result(result))
        ]
        if outputs:
            await self._hooks.action_results(step.frame, outputs)
