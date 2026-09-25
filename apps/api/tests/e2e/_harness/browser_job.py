"""Drive a whole background browser job offline, from the executor's tool call to the worker's delivery.

Three things stand in for the world: Browser-Use (a scripted agent installed at
the one seam the run constructs it), the browser host (no session is allocated),
and ARQ (the real task body runs in this process on a fake Redis). Everything
between them is the production code path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, ExitStack, asynccontextmanager
from dataclasses import dataclass, field
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import browser_use
import fakeredis.aioredis

from app.agents.core.background.session import RunKind, create_session
from app.agents.tools import browser_tool
from app.config.settings import settings
from app.constants.browser import BrowserEngine, EngineSwitchReason
from app.models.hil_models import HILPreferences
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.exceptions import BrowserHandoffCancelled, BrowserSessionGone
from app.services.browser.host_client import HostSessionInfo
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
    #: The agent's request_human_takeover action as the step: (reason, category).
    takeover: tuple[str, str] | None = None
    #: The agent's request_agent_guidance action as the step: its reason.
    guidance: str | None = None
    #: The agent's continue_in_full_browser action as the step: why the fast engine failed.
    switch: EngineSwitchReason | None = None
    #: Wait until an executor has joined the job before stepping, so a journey
    #: about what a joined executor sees is not a race with the turn's own poll.
    await_joiner: bool = False
    #: The engine under the run dies here: the host loses the session and the run
    #: ends the way Browser-Use ends one, on step failures, with nothing raised.
    engine_dies: bool = False
    #: The page's controls by index, as (tag, attributes), for the element an action targets.
    fields: dict[int, dict[str, str]] = field(default_factory=dict)


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


class _Node:
    """The slice of a Browser-Use DOM node a card and the password check read."""

    def __init__(self, attributes: dict[str, str]) -> None:
        self.attributes = attributes
        self.ax_node = None
        self.node_name = "INPUT"

    def get_meaningful_text_for_llm(self) -> str:
        return self.attributes.get("aria-label", "")


class _PageState:
    def __init__(self, url: str, fields: dict[int, dict[str, str]]) -> None:
        self.url = url
        self.title = "Example"
        self.screenshot = "ZmFrZS1zY3JlZW5zaG90"
        self.dom_state = SimpleNamespace(
            selector_map={index: _Node(attributes) for index, attributes in fields.items()}
        )


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
        #: Where the scripted browser is now, for the run's resume on a fallback engine.
        self.url: str | None = None
        #: The continue_in_full_browser action, when the run on this engine was offered it.
        self.switch: Callable[[EngineSwitchReason], Any] | None = None

    def agent(self, **kwargs: Any) -> _ScriptedAgent:
        return _ScriptedAgent(self, **kwargs)


class _BrowserSession:
    """The agent's browser, as the run reads it: where it is; never connected over CDP."""

    def __init__(self, double: BrowserDouble) -> None:
        self._double = double
        self.is_cdp_connected = False
        self.reset = AsyncMock()

    async def get_current_page_url(self) -> str | None:
        return self._double.url


class _ScriptedAgent:
    """Stands in for browser_use.Agent, calling back exactly where the real one does.

    The run's initial jev action is not executed: Jev's own loop is proven by its
    unit tests, and these journeys are about everything around the run.
    """

    def __init__(self, double: BrowserDouble, **kwargs: Any) -> None:
        self._double = double
        self._on_step = kwargs["register_new_step_callback"]
        self._should_stop = kwargs["register_should_stop_callback"]
        self.task = kwargs["task"]
        self._stopped = False
        self.state = _AgentState([])
        self.browser_session = _BrowserSession(double)
        self.new_tasks: list[str] = []
        self.message_manager = SimpleNamespace(add_new_task=self.new_tasks.append)

    def stop(self) -> None:
        self._stopped = True

    async def run(
        self, max_steps: int, on_step_start: Any = None, on_step_end: Any = None
    ) -> _History:
        double = self._double
        while double.next_step < len(double.steps):
            step = double.steps[double.next_step]
            double.next_step += 1
            if step.engine_dies:
                double.kill_engine()
                return _History("", successful=False, done=False)
            if await self._halts_before(step):
                break
            if on_step_start is not None:
                await on_step_start(self)
            try:
                ended = await self._perform(step, double.next_step, on_step_end)
            except _RunHalted:
                break
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

    async def _perform(self, step: ScriptedStep, index: int, on_step_end: Any) -> _History | None:
        """Report the step as Browser-Use does, run its takeover or guidance action, and return the history a done action ends the run with."""
        step_actions = list(step.actions)
        if step.takeover is not None:
            step_actions = [
                (
                    "request_human_takeover",
                    {"reason": step.takeover[0], "category": step.takeover[1]},
                )
            ]
        elif step.guidance is not None:
            step_actions = [("request_agent_guidance", {"reason": step.guidance})]
        elif step.switch is not None:
            step_actions = [("continue_in_full_browser", {"category": step.switch.value})]
        self._double.url = step.url
        actions = [_Action(name, params) for name, params in step_actions]
        await self._on_step(_PageState(step.url, step.fields), _AgentOutput(actions), index)
        try:
            if step.takeover is not None:
                await self._hand_over(*step.takeover)
            elif step.guidance is not None:
                await self._ask_the_agent(step.guidance)
            elif step.switch is not None:
                assert self._double.switch is not None, "the run was not offered the full browser"
                await self._double.switch(step.switch)
        except BrowserHandoffCancelled:
            # Browser-Use turns this into an action error and the run's own flags
            # decide the outcome; the loop has nothing left to do.
            raise _RunHalted from None
        if on_step_end is not None:
            self.state = _AgentState(step.outputs)
            await on_step_end(self)
        # A done action ends the run where Browser-Use ends it, with its own text and verdict.
        return _ended_by(step_actions)

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
    browser = MagicMock()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    create_session(stream_id, RunKind.LIVE)

    async def _enqueue(
        pool: Any, name: str, payload: dict[str, Any], *, _queue_name: str
    ) -> object:
        world.enqueued.append(BrowserJobRequest.model_validate(payload))
        double.job_id = world.enqueued[-1].job_id
        world.jobs.append(asyncio.create_task(browser_tasks.run_browser_job({}, payload)))
        return object()

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
        patch.object(browser_use, "Browser", lambda **kwargs: browser),
        patch("app.agents.tools.browser_tool.enqueue_worker_job", _enqueue),
        patch("app.agents.tools.browser_tool.RedisPoolManager.get_pool", AsyncMock()),
        patch(
            "app.services.hil.policy.get_hil_preferences",
            AsyncMock(return_value=HILPreferences(mode="always_allow")),
        ),
        *_host_patches(world, scripted_host),
        # A world with a fallback host is an Obscura user's (Chrome behind it); any
        # other runs on Chrome, the default engine.
        patch(
            "app.services.browser.job_runner.is_enabled",
            AsyncMock(return_value=scripted_host.fallback_url is not None),
        ),
        patch.object(
            settings,
            "BROWSER_ENGINE",
            BrowserEngine.OBSCURA if scripted_host.fallback_url else BrowserEngine.CHROMIUM,
        ),
        # The models and Jev's gateway are never called: the agent and Jev are scripted.
        patch("app.services.browser.agent_run.build_agent_llm", AsyncMock(return_value=object())),
        patch("app.services.browser.agent_run.build_text_model", lambda ledger: object()),
        patch("app.services.browser.agent_run.build_jev_client", lambda: object()),
        patch("app.services.browser.agent_run.JevPage", _Page),
        patch("app.services.browser.job_runner.record_browser_task", AsyncMock()),
        patch("app.services.browser.job_runner.capture_event", MagicMock()),
        patch("app.services.browser.agent_run.build_browser_tools", _tools_of(double)),
        patch(
            "app.services.browser.runner.publish_step_screenshot",
            lambda image, session_id, index: _shot_url(index),
        ),
        patch("app.services.browser.runner.create_replay_link", AsyncMock(return_value=REPLAY_URL)),
        patch("app.workers.tasks.browser_tasks.load_user_context", AsyncMock(return_value=_user())),
        *_delivery_patches(world, stream_id),
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


def _host_patches(
    world: JobWorld, scripted_host: ScriptedHost
) -> list[AbstractContextManager[object]]:
    """Stand in for the browser host: sessions it opens, loses when the engine dies, and whose state it reads."""
    double = world.browser

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
            url=double.url,
        )

    async def _get_storage_state(session_id: str, host_url: str) -> Any:
        world.storage_reads.append(session_id)
        if session_id in world.dead_sessions:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}/storage-state"
            )
        return LIVE_STORAGE_STATE

    return [
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
    ]


def _delivery_patches(world: JobWorld, stream_id: str) -> list[AbstractContextManager[object]]:
    """Record what reaches the user: the turn's stream, bot messages and photos, and the conversation."""

    async def _publish_chunk(chunk_stream_id: str, chunk: str) -> None:
        if chunk_stream_id == stream_id:
            world.chunks.append(chunk)

    async def _outbound_message(platform: Any, user_id: str, blocks: list[str]) -> bool:
        world.bot_messages.extend(blocks)
        return True

    async def _outbound_photo(platform: Any, user_id: str, url: str, **kwargs: Any) -> bool:
        world.bot_photos.append(url)
        return True

    async def _deliver(**kwargs: Any) -> None:
        world.deliveries.append(kwargs)

    return [
        patch(
            "app.core.stream_manager.StreamManager.publish_chunk",
            AsyncMock(side_effect=_publish_chunk),
        ),
        patch("app.services.browser.bot_delivery.publish_outbound_message", _outbound_message),
        patch("app.services.browser.bot_delivery.publish_outbound_photo", _outbound_photo),
        patch(
            "app.services.browser.bot_delivery.create_live_view_link",
            AsyncMock(return_value=LIVE_VIEW_LINK),
        ),
        patch(
            "app.workers.tasks.browser_tasks.narrate_executor_result",
            AsyncMock(side_effect=_narrate),
        ),
        patch("app.workers.tasks.browser_tasks.deliver_message_to_conversation", _deliver),
    ]


def _tools_of(double: BrowserDouble) -> Callable[..., object]:
    """Hand the double the takeover and guidance actions, which Browser-Use would otherwise own."""

    def _build(
        *,
        solve_captcha: bool,
        handle_takeover: Callable[[str, str], Any],
        handle_guidance: Callable[[str], Any],
        handle_engine_switch: Callable[[EngineSwitchReason], Any] | None = None,
    ) -> object:
        double.takeover = handle_takeover
        double.guidance = handle_guidance
        double.switch = handle_engine_switch
        return _Tools()

    return _build


class _Tools:
    """Browser-Use's tool registry, as far as registering the jev action needs it."""

    def action(self, description: str, **kwargs: Any) -> Callable[[Any], Any]:
        return lambda function: function


class _Page:
    """Jev's view of the tab, as far as a step card's photo and a guidance ask read it."""

    def __init__(self, browser: _BrowserSession) -> None:
        self._browser = browser

    async def screenshot(self) -> str:
        return "ZmFrZS1zY3JlZW5zaG90"

    async def observe(self) -> Any:
        url = await self._browser.get_current_page_url()
        return SimpleNamespace(url=url or "", title="Example", text="", actions=[])


async def _shot_url(index: int) -> str:
    return SHOT_URL_TEMPLATE.format(index=index)


async def _narrate(result_text: str, msg_type: str, conversation_id: str, user: Any) -> str:
    """Stand in for the comms re-voicing, which is an LLM call; the run's own text is what matters here."""
    return f"NARRATED: {result_text}"


def _user() -> Any:
    return MagicMock(user_id="user-e2e", email="e2e@example.test")
