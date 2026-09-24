"""Drive a whole background browser job offline, from the executor's tool call to the worker's delivery.

Three things stand in for the world: Browser-Use (a scripted agent installed at
the one seam the run constructs it), the browser host (no session is allocated),
and ARQ (the real task body runs in this process on a fake Redis). Everything
between them is the production code path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import ExitStack, asynccontextmanager
from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import browser_use
import fakeredis.aioredis
from pydantic import BaseModel

from app.agents.core.background.session import RunKind, create_session
from app.agents.tools import browser_tool
from app.config.settings import settings
from app.constants.llm import ReasoningLevel
from app.models.hil_models import HILPreferences
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserSessionGone
from app.services.browser.host_client import HostSessionInfo
from app.services.browser.jev.chat_model import JevChatModel
from app.services.browser.jev.gateway import JevChoiceAnswer, JevEvaluation, JevUsage
from app.services.browser.jev.prompts import PART_DONE, PLAN_STEPS
from app.workers.tasks import browser_tasks

#: What the fake CDN hands back for a step screenshot, per step index.
SHOT_URL_TEMPLATE = "https://cdn.test/shot-{index}.png"

#: The live-view link a bot conversation is given.
LIVE_VIEW_LINK = "https://gaia.test/live/take-a-look"

#: The recap slideshow link every run closes with.
REPLAY_URL = "https://gaia.test/replay/the-run"

#: What a live browser session holds when its state is read: the cookie a
#: sign-in on it left behind.
LIVE_STORAGE_STATE: dict[str, Any] = {
    "cookies": [{"name": "session", "value": "signed-in", "domain": "example.test", "path": "/"}],
    "origins": [],
}


@dataclass
class ScriptedStep:
    """One step the scripted browser performs, in Browser-Use's own callback order."""

    actions: list[tuple[str, dict[str, Any]]]
    url: str = "https://example.test/page"
    #: Per-action result text, matched positionally to actions.
    outputs: list[str] = field(default_factory=list)
    #: Poll should_stop instead of stepping, so a stop arriving mid-run is observable.
    await_stop: bool = False
    #: Ask the bound Jev policy what to do instead of using this step's actions.
    decide: bool = False
    #: Wait until an executor has joined the job before deciding, so a journey
    #: about what a joined executor sees is not a race with the turn's own poll.
    await_joiner: bool = False
    #: The engine under the run dies here: the host loses the session and the run
    #: ends the way Browser-Use ends one, on step failures, with nothing raised.
    engine_dies: bool = False
    #: The page Jev reads when it decides this step; None keeps the one it read last.
    jev_page: JevPageView | None = None


class _Action:
    def __init__(self, name: str, params: dict[str, Any]) -> None:
        self._name = name
        self._params = params

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        return {self._name: self._params}


class _AgentOutput:
    def __init__(self, actions: list[_Action]) -> None:
        self.next_goal = ""
        self.thinking = ""
        self.action = actions


class _PageState:
    def __init__(self, url: str) -> None:
        self.url = url
        self.title = "Example"
        self.screenshot = "ZmFrZS1zY3JlZW5zaG90"


class _ActionResult:
    def __init__(self, output: str) -> None:
        self.extracted_content = output
        self.error = None
        self.long_term_memory = None


class _AgentState:
    def __init__(self, outputs: list[str]) -> None:
        self.last_result = [_ActionResult(text) for text in outputs]


class _History:
    def __init__(self, summary: str, successful: bool, *, done: bool = True) -> None:
        self._summary = summary
        self._successful = successful
        self._done = done
        self.usage = None

    def final_result(self) -> str:
        return self._summary

    def is_done(self) -> bool:
        return self._done

    def is_successful(self) -> bool:
        return self._successful


class BrowserDouble:
    """The scripted Browser-Use run, and what it observed while running."""

    def __init__(self, steps: list[ScriptedStep], summary: str, successful: bool) -> None:
        self.steps = steps
        self.summary = summary
        self.successful = successful
        #: True once the agent's own should_stop callback said to stop.
        self.stop_observed = False
        #: What each takeover handed back to the agent — the user's note.
        self.takeover_notes: list[str | None] = []
        self.takeover: Callable[[str, str], Any] | None = None
        #: The reason each blocked step gave when it asked the agent for guidance.
        self.guidance_reasons: list[str] = []
        #: What each of those asks handed back — the executor's instruction.
        self.guidance_notes: list[str] = []
        self.guidance: Callable[[str], Any] | None = None
        #: Set once the job reaches the worker; the await_joiner step needs it.
        self.job_id: str = ""
        #: The next step to play: a run moved to the fallback engine picks up
        #: where the run on the dead engine stopped.
        self.next_step = 0
        #: Kills the engine under the session the run is on; the world wires it.
        self.kill_engine: Callable[[], None] = lambda: None
        #: The page a Jev-driven run reads; the world wires it.
        self.page: _JevPage | None = None

    def agent(self, **kwargs: Any) -> _ScriptedAgent:
        return _ScriptedAgent(self, **kwargs)


class _ScriptedAgent:
    """Stands in for browser_use.Agent, calling back exactly where the real one does."""

    def __init__(self, double: BrowserDouble, **kwargs: Any) -> None:
        self._double = double
        self._on_step = kwargs["register_new_step_callback"]
        self._should_stop = kwargs["register_should_stop_callback"]
        self._llm = kwargs["llm"]
        self._stopped = False
        self.state = _AgentState([])

    def stop(self) -> None:
        self._stopped = True

    async def run(self, max_steps: int, on_step_end: Any = None) -> _History:
        double = self._double
        while double.next_step < len(double.steps):
            step = double.steps[double.next_step]
            double.next_step += 1
            if step.engine_dies:
                double.kill_engine()
                return _History("", successful=False, done=False)
            if await self._halts_before(step):
                break
            try:
                step_actions = await self._actions_for(step)
            except _RunHalted:
                break
            if step_actions is None:
                continue
            ended = await self._perform(step, step_actions, double.next_step, on_step_end)
            if ended is not None:
                return ended
        return _History(double.summary, double.successful)

    async def _halts_before(self, step: ScriptedStep) -> bool:
        """Whether the run stops before this step, after waiting on whatever the step waits for."""
        if step.await_stop:
            await self._wait_for_stop()
            return True
        if self._stopped or await self._should_stop():
            self._double.stop_observed = True
            return True
        if step.await_joiner:
            await self._wait_for_joiner()
        return False

    async def _actions_for(self, step: ScriptedStep) -> list[tuple[str, dict[str, Any]]] | None:
        """Return the step's actions, scripted or decided by the real Jev policy; None when a handoff was the step."""
        if not step.decide:
            return list(step.actions)
        if step.jev_page is not None and self._double.page is not None:
            self._double.page.show(step.jev_page)
        try:
            decided = await self._decide()
        except BrowserHandoffCancelled:
            # Browser-Use turns this into an action error and the run's own flags
            # decide the outcome; the loop has nothing left to do.
            raise _RunHalted from None
        return None if decided is None else [decided]

    async def _perform(
        self,
        step: ScriptedStep,
        step_actions: list[tuple[str, dict[str, Any]]],
        index: int,
        on_step_end: Any,
    ) -> _History | None:
        """Report the step as Browser-Use does and return the history a done action ends the run with, else None."""
        actions = [_Action(name, params) for name, params in step_actions]
        await self._on_step(_PageState(step.url), _AgentOutput(actions), index)
        if on_step_end is not None:
            self.state = _AgentState(step.outputs)
            await on_step_end(self)
        # A done action ends the run where Browser-Use ends it, with its own text and verdict.
        return _ended_by(step_actions)

    async def _decide(self) -> tuple[str, dict[str, Any]] | None:
        """Ask the real Jev policy for this step, and perform a takeover it asks for.

        None once the decision was the handoff itself: the takeover IS the step,
        exactly as Browser-Use executes that action and then continues.
        """
        completion = (await self._llm.ainvoke([], JevAgentOutput)).completion
        name, params = next(iter(completion.action[0].model_dump(exclude_none=True).items()))
        if name == "request_human_takeover":
            await self._hand_over(params["reason"], params["category"])
            return None
        if name == "request_agent_guidance":
            await self._ask_the_agent(params["reason"])
            return None
        return name, params

    async def _hand_over(self, reason: str, category: str) -> None:
        assert self._double.takeover is not None, "the takeover action was never built"
        self._double.takeover_notes.append(await self._double.takeover(reason, category))

    async def _wait_for_joiner(self) -> None:
        from app.services.browser.jobs import joiner_lease_held

        for _ in range(500):
            if await joiner_lease_held(self._double.job_id):
                return
            await asyncio.sleep(0.01)
        raise AssertionError("no executor ever joined the job")

    async def _ask_the_agent(self, reason: str) -> None:
        assert self._double.guidance is not None, "the guidance action was never built"
        self._double.guidance_reasons.append(reason)
        self._double.guidance_notes.append(await self._double.guidance(reason))

    async def _wait_for_stop(self) -> None:
        """Sit on the page until the user's stop reaches the agent, as a real run would."""
        for _ in range(500):
            if self._stopped or await self._should_stop():
                self._double.stop_observed = True
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the browser run was never told to stop")


def _ended_by(step_actions: list[tuple[str, dict[str, Any]]]) -> _History | None:
    """Return the history a done action among step_actions ends the run with, if one is there."""
    for name, params in step_actions:
        if name == "done":
            return _History(str(params.get("text", "")), bool(params.get("success")))
    return None


class JobWorld:
    """Everything the run touched outside its own process, recorded."""

    def __init__(self, double: BrowserDouble) -> None:
        self.browser = double
        self.enqueued: list[BrowserJobRequest] = []
        self.chunks: list[str] = []
        self.bot_messages: list[str] = []
        self.bot_photos: list[str] = []
        self.deliveries: list[dict[str, Any]] = []
        self.jev: ScriptedJevGateway | None = None
        self.jobs: list[asyncio.Task[Any]] = []
        self.host_sessions = 0
        #: Sessions whose engine died; the host answers 404 for them.
        self.dead_sessions: set[str] = set()
        #: The storage_state each host session was created with, in order.
        self.seeded_states: list[Any] = []
        #: Each session whose live storage_state was read.
        self.storage_reads: list[str] = []

    def frames(self) -> list[dict[str, Any]]:
        """Return each SSE chunk the turn's stream carried, decoded."""
        return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in self.chunks]

    def cards(self) -> list[dict[str, Any]]:
        """Return the browser card payloads, in publish order."""
        return [
            frame["tool_data"]["data"]
            for frame in self.frames()
            if "tool_data" in frame and frame["tool_data"].get("tool_name") == "browser_task_data"
        ]

    async def settle(self) -> None:
        """Wait out the worker task and the fire-and-forget publishes it left behind."""
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        from app.utils import background_tasks

        for _ in range(50):
            pending = [task for task in background_tasks._background_tasks if not task.done()]
            if not pending:
                break
            await asyncio.gather(*pending, return_exceptions=True)


class _RunHalted(Exception):
    """The scripted run ends here, as Browser-Use ends it."""


@dataclass(frozen=True)
class ScriptedHost:
    """The browser host a job reaches: whether opening a session on it fails, and the fallback it may use."""

    error: Exception | None = None
    fallback_url: str | None = None


@asynccontextmanager
async def browser_job_world(
    stream_id: str,
    *,
    steps: list[ScriptedStep] | None = None,
    summary: str = "The table is booked for 7pm on Friday.",
    successful: bool = True,
    jev: JevScript | None = None,
    host: ScriptedHost | None = None,
) -> AsyncIterator[JobWorld]:
    """Wire one turn's world: a fake Redis, a scripted browser, an in-process worker."""
    double = BrowserDouble(
        steps
        if steps is not None
        else [
            ScriptedStep(
                actions=[("go_to_url", {"url": "https://example.test"})],
                outputs=["opened example.test"],
            )
        ],
        summary,
        successful,
    )
    world = JobWorld(double)
    scripted_host = host if host is not None else ScriptedHost()
    page: Any = AsyncMock()
    llm: Any = object()
    if jev is not None:
        world.jev = ScriptedJevGateway(jev)
        helper = _JevTextHelper(jev.texts, jev.judge)
        llm = JevChatModel(client=world.jev, text_model=helper, structured_call=helper.structured)
        page = _JevPage()
        double.page = page
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    create_session(stream_id, RunKind.LIVE)

    async def _enqueue(
        pool: Any, name: str, payload: dict[str, Any], *, _queue_name: str
    ) -> object:
        world.enqueued.append(BrowserJobRequest.model_validate(payload))
        double.job_id = world.enqueued[-1].job_id
        world.jobs.append(asyncio.create_task(browser_tasks.run_browser_job({}, payload)))
        return object()

    async def _publish_chunk(chunk_stream_id: str, chunk: str) -> None:
        if chunk_stream_id == stream_id:
            world.chunks.append(chunk)

    async def _outbound_message(platform: Any, user_id: str, blocks: list[str]) -> bool:
        world.bot_messages.extend(blocks)
        return True

    async def _outbound_photo(platform: Any, user_id: str, url: str, **kwargs: Any) -> bool:
        world.bot_photos.append(url)
        return True

    async def _create_host_session(storage_state: Any, host_url: str) -> Any:
        if scripted_host.error is not None:
            raise scripted_host.error
        world.seeded_states.append(storage_state)
        world.host_sessions += 1
        return MagicMock(
            session_id=f"sess-{world.host_sessions}",
            cdp_ws="ws://browser.test/cdp",
            live_ws="ws://browser.test/live",
            context_id="ctx-1",
        )

    async def _deliver(**kwargs: Any) -> None:
        world.deliveries.append(kwargs)

    def _kill_engine() -> None:
        world.dead_sessions.add(f"sess-{world.host_sessions}")

    double.kill_engine = _kill_engine

    async def _get_host_session(
        session_id: str, host_url: str, *, timeout: float | None = None
    ) -> HostSessionInfo:
        if session_id in world.dead_sessions:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}"
            )
        return HostSessionInfo(
            session_id=session_id,
            live=True,
            last_activity_at=0.0,
            url=page.url if isinstance(page, _JevPage) else None,
        )

    async def _get_storage_state(session_id: str, host_url: str) -> Any:
        world.storage_reads.append(session_id)
        if session_id in world.dead_sessions:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}/storage-state"
            )
        return LIVE_STORAGE_STATE

    patches = [
        patch("app.db.redis.redis_cache.redis", redis),
        # The real waits are tens of seconds of polling. Shrunk, not removed: the
        # poll loops are what the join and the delivery hand-off are made of.
        patch.object(browser_tasks, "BROWSER_JOB_JOINER_LEASE_SECONDS", 0.2),
        patch.object(browser_tasks, "BROWSER_JOB_JOINER_REFRESH_SECONDS", 0.1),
        patch.object(browser_tasks, "BROWSER_JOB_POLL_INTERVAL_SECONDS", 0.02),
        patch.object(browser_tool, "BROWSER_JOB_POLL_INTERVAL_SECONDS", 0.02),
        patch.object(browser_tool, "BROWSER_JOB_JOINER_REFRESH_SECONDS", 0.1),
        patch("app.services.browser.handoff.HANDOFF_POLL_INTERVAL_SECONDS", 0.02),
        # A guidance request nobody answers must fail the journey in seconds, not
        # sit out the real two-minute budget.
        patch("app.services.browser.job_runner.BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS", 2),
        patch.object(browser_use, "Agent", double.agent),
        patch.object(browser_use, "Browser", lambda **kwargs: page),
        patch("app.agents.tools.browser_tool.enqueue_worker_job", _enqueue),
        patch("app.agents.tools.browser_tool.RedisPoolManager.get_pool", AsyncMock()),
        patch(
            "app.core.stream_manager.StreamManager.publish_chunk",
            AsyncMock(side_effect=_publish_chunk),
        ),
        patch(
            "app.services.hil.policy.get_hil_preferences",
            AsyncMock(return_value=HILPreferences(mode="always_allow")),
        ),
        patch("app.services.browser.session.host_client.create_session", _create_host_session),
        patch(
            "app.services.browser.session.host_client.delete_session",
            AsyncMock(return_value=LIVE_STORAGE_STATE),
        ),
        patch("app.services.browser.session.host_client.get_session", _get_host_session),
        patch("app.services.browser.session.host_client.get_storage_state", _get_storage_state),
        patch.object(settings, "BROWSER_FALLBACK_HOST_URL", scripted_host.fallback_url),
        patch("app.services.browser.session.load_storage_state", AsyncMock(return_value=None)),
        patch("app.services.browser.session.save_storage_state", AsyncMock()),
        patch("app.services.browser.job_runner.build_browser_llm", lambda user_id=None: llm),
        patch("app.services.browser.job_runner.record_browser_task", AsyncMock()),
        patch("app.services.browser.job_runner.capture_event", MagicMock()),
        patch("app.services.browser.agent_run.build_browser_tools", _tools_of(double)),
        patch(
            "app.services.browser.runner.publish_step_screenshot",
            lambda image, session_id, index: _shot_url(index),
        ),
        patch("app.services.browser.runner.create_replay_link", AsyncMock(return_value=REPLAY_URL)),
        patch("app.services.browser.bot_delivery.publish_outbound_message", _outbound_message),
        patch("app.services.browser.bot_delivery.publish_outbound_photo", _outbound_photo),
        patch(
            "app.services.browser.bot_delivery.create_live_view_link",
            AsyncMock(return_value=LIVE_VIEW_LINK),
        ),
        patch("app.workers.tasks.browser_tasks.load_user_context", AsyncMock(return_value=_user())),
        patch(
            "app.workers.tasks.browser_tasks.narrate_executor_result",
            AsyncMock(side_effect=_narrate),
        ),
        patch("app.workers.tasks.browser_tasks.deliver_message_to_conversation", _deliver),
    ]
    with ExitStack() as stack:
        for entered in patches:
            stack.enter_context(entered)
        try:
            yield world
        finally:
            for task in world.jobs:
                task.cancel()
            await redis.aclose()


def _tools_of(double: BrowserDouble) -> Callable[..., object]:
    """Hand the double the takeover and guidance actions, which Browser-Use would otherwise own."""

    def _build(
        *,
        solve_captcha: bool,
        handle_takeover: Callable[[str, str], Any],
        handle_guidance: Callable[[str], Any],
    ) -> object:
        double.takeover = handle_takeover
        double.guidance = handle_guidance
        return object()

    return _build


async def _shot_url(index: int) -> str:
    return SHOT_URL_TEMPLATE.format(index=index)


async def _narrate(result_text: str, msg_type: str, conversation_id: str, user: Any) -> str:
    """Stand in for the comms re-voicing, which is an LLM call; the run's own text is what matters here."""
    return f"NARRATED: {result_text}"


def _user() -> Any:
    return MagicMock(user_id="user-e2e", email="e2e@example.test")


# ---------------------------------------------------------------------------
# Jev: the real policy model, with the gateway and the page it reads scripted
# ---------------------------------------------------------------------------


class _JevAction(BaseModel):
    """The Browser-Use action model Jev fills in, cut down to the operations this suite offers."""

    click: dict[str, Any] | None = None
    navigate: dict[str, Any] | None = None
    input_text: dict[str, Any] | None = None
    wait: dict[str, Any] | None = None
    go_back: dict[str, Any] | None = None
    done: dict[str, Any] | None = None
    request_human_takeover: dict[str, Any] | None = None
    request_agent_guidance: dict[str, Any] | None = None


class JevAgentOutput(BaseModel):
    """What Browser-Use asks the model for each step; an `action` field is what routes it to Jev."""

    memory: str
    next_goal: str | None = None
    action: list[_JevAction]


class _JevNode:
    """The slice of a Browser-Use DOM node the observation reads."""

    def __init__(self, node_name: str, attributes: dict[str, str]) -> None:
        self.node_name = node_name
        self.attributes = attributes
        self.text = ""
        self.ax_node = None
        self.children_nodes: list[_JevNode] = []
        self.is_visible = True

    def get_meaningful_text_for_llm(self) -> str:
        return self.attributes.get("placeholder") or self.attributes.get("value") or ""

    def get_all_children_text(self) -> str:
        return self.get_meaningful_text_for_llm()


@dataclass(frozen=True)
class JevPageView:
    """One page as Jev reads it: where it is, its controls as (tag, attributes), and its text."""

    url: str
    controls: list[tuple[str, dict[str, str]]]
    text: str = ""
    title: str = "Example"


class _JevPage:
    """The browser session Jev observes: one cached state read, one DOM snapshot, no CDP."""

    def __init__(self) -> None:
        node = _JevNode("INPUT", {"role": "combobox", "placeholder": "Where to?"})
        self._selector_map = {7: node}
        self._text = "[1]<input>Where to?"
        self.url = "https://example.test/book"
        self.title = "Book a table"

    def show(self, view: JevPageView) -> None:
        self._selector_map = {
            index: _JevNode(tag, attributes)
            for index, (tag, attributes) in enumerate(view.controls, start=1)
        }
        self._text = view.text
        self.url = view.url
        self.title = view.title

    async def get_browser_state_summary(self, **kwargs: Any) -> Any:
        text = self._text
        dom_state = SimpleNamespace(
            selector_map=self._selector_map, llm_representation=lambda: text
        )
        return SimpleNamespace(dom_state=dom_state, url=self.url, title=self.title)

    async def get_or_create_cdp_session(self) -> Any:
        return SimpleNamespace(session_id="s", cdp_client=SimpleNamespace(send=SimpleNamespace()))


@dataclass
class JevScript:
    """What the gateway answers, and what Jev's text helper writes, in call order."""

    #: (operation, target key) per decision; target None for an operation with no element head.
    decisions: list[tuple[str, str | None]]
    #: One structured reply per text-helper call, e.g. the takeover reason.
    texts: list[dict[str, Any]] = field(default_factory=list)
    #: The part check, as (label, context) -> verdict; None takes a chosen DONE at its word.
    judge: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None


class ScriptedJevGateway:
    """Answers each evaluation from the script, and keeps every request it was sent."""

    model = "typesafe-ai/jev"

    def __init__(self, script: JevScript) -> None:
        self._decisions = list(script.decisions)
        self.requests: list[Any] = []

    async def evaluate(self, request: Any) -> Any:
        self.requests.append(request)
        operation, target = self._decisions.pop(0)
        answers = {"operation": _choice(operation, list(request.questions["operation"].criteria))}
        if target is not None:
            head = f"{operation.lower()}_target"
            answers[head] = _choice(target, list(request.questions[head].criteria))
        return JevEvaluation(
            answers=answers, usage=JevUsage(inputTokens=120, outputTokens=4), latency_ms=1
        )

    def goal(self, call: int) -> str:
        """Return the goal text Jev classified against on one decision."""
        goal: str = self.requests[call].questions["operation"].instructions["goal"]
        return goal


def _choice(choice: str, keys: list[str]) -> JevChoiceAnswer:
    """One answer whose distribution passes the policy's own validation."""
    # A lone key carries the whole distribution, or the policy rejects the answer.
    top = 0.8 if len(keys) > 1 else 1.0
    rest = (1 - top) / (len(keys) - 1) if len(keys) > 1 else 0.0
    return JevChoiceAnswer(
        type="choice",
        choice=choice,
        probabilities={key: (top if key == choice else rest) for key in keys},
    )


class _JevTextHelper:
    """Jev's text side: the reason it writes for a takeover, the value it types."""

    model = "text-helper"
    provider = "fake"
    name = "text-helper"

    def __init__(
        self,
        replies: list[dict[str, Any]],
        judge: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._replies = list(replies)
        self._judge = judge

    async def ainvoke(self, messages: Any, output_format: Any = None, **kwargs: Any) -> Any:
        from browser_use.llm.views import ChatInvokeCompletion

        if output_format is None:
            return ChatInvokeCompletion(completion="", usage=None)
        reply = self._replies.pop(0) if self._replies else {}
        return ChatInvokeCompletion(completion=output_format.model_validate(reply), usage=None)

    async def structured(
        self,
        schema: Any,
        prompt: Any,
        *,
        label: str,
        timeout: float | None = None,
        reasoning: ReasoningLevel | None = None,
    ) -> Any:
        """Answer as the loop's writer: plan and part checks answer themselves, the rest take the scripted replies in order."""
        instructions = prompt[0].content
        if instructions.startswith(PLAN_STEPS):
            return schema.model_validate({"steps": []})
        if instructions.startswith(PART_DONE):
            if self._judge is not None:
                return schema.model_validate(self._judge(label, json.loads(prompt[1].content)))
            if label != "browser_done_check":
                return schema.model_validate({"done": False})
            # A DONE the script chose is taken at its word, cited by the page read.
            pages = json.loads(prompt[1].content)["pages_read"]
            return schema.model_validate(
                {"done": True, "evidence": [pages[0]["url"]] if pages else [], "findings": ""}
            )
        reply = self._replies.pop(0) if self._replies else {}
        if "achieved" in schema.model_fields and isinstance(reply, dict):
            reply = {"achieved": True, **reply}
        return schema.model_validate(reply)
