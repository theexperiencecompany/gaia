"""Drive a whole background browser job offline, from the executor's tool call to the worker's delivery.

Three things stand in for the world: Browser-Use (a scripted agent installed at
the one seam the run constructs it), the browser host (no session is allocated),
and ARQ (the real task body runs in this process on a fake Redis). Everything
between them is the production code path.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import inspect
import json
import tempfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from browser_use.agent.views import ActionResult, AgentHistoryList, AgentState
from browser_use.browser.events import BrowserConnectedEvent
import fakeredis.aioredis

from app.agents.core.background.session import RunKind, create_session, signal_executor_done
from app.browser_host.wire import SessionInfo
from app.config.settings import settings
from app.constants.browser import (
    BROWSER_ANSWER_AFTER_STEP,
    BrowserEngine,
    EngineSwitchReason,
    SensitiveCategory,
)
from app.core.stream_manager import StreamManager
from app.models.hil_models import HILPreferences
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.exceptions import BrowserSessionGone
from app.workers.tasks import browser_tasks
from shared.py import wide_events

#: What the fake CDN hands back for a step screenshot, per step index.
SHOT_URL_TEMPLATE = "https://cdn.test/shot-{index}.png"

#: The live-view link a bot conversation is given.
LIVE_VIEW_LINK = "https://gaia.test/live/take-a-look"

#: The recap slideshow link every run closes with.
REPLAY_URL = "https://gaia.test/replay/the-run"

#: How long a wait of a second or more takes inside long_waits_pass_quickly.
_LONG_WAIT_TICK_SECONDS = 0.005

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


def _agent_state(outputs: list[str]) -> AgentState:
    """Browser-Use's own agent state after a step, carrying each action's output."""
    return AgentState(last_result=[ActionResult(extracted_content=text) for text in outputs])


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

    def errors(self) -> list[str | None]:
        return [None]

    def number_of_steps(self) -> int:
        return 1


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
        self.takeover: Callable[[str, SensitiveCategory], Any] | None = None
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


class _Browser:
    """Browser-Use's Browser, as the run wires it: its event bus fires the connect the real one does."""

    def __init__(self) -> None:
        self._handlers: dict[object, list[Callable[[object], object]]] = {}
        self.event_bus = SimpleNamespace(on=self._on)
        self.cdp_client = MagicMock()

    def _on(self, event: object, handler: Callable[[object], object]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    async def connect(self) -> None:
        for handler in self._handlers.get(BrowserConnectedEvent, []):
            fired = handler(SimpleNamespace())
            if inspect.isawaitable(fired):
                await fired


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
        self._browser: _Browser = kwargs["browser"]
        self._stopped = False
        self.state = kwargs.get("injected_agent_state") or _agent_state([])
        # Its steps are scripted results, not model outputs: nothing it read to report.
        self.history = AgentHistoryList(history=[])
        self.browser_session = _BrowserSession(double)
        self.new_tasks: list[str] = []
        self.message_manager = SimpleNamespace(add_new_task=self.new_tasks.append)
        # Where the real agent writes its file system and step screenshots; the run removes it.
        self.agent_directory = tempfile.mkdtemp(prefix="browser_use_agent_")
        self.file_system_path = self.agent_directory

    def stop(self) -> None:
        self._stopped = True

    async def run(
        self, max_steps: int, on_step_start: Any = None, on_step_end: Any = None
    ) -> _History:
        double = self._double
        await self._browser.connect()
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
        step_actions = _reported_actions(step)
        self._double.url = step.url
        actions = [_Action(name, params) for name, params in step_actions]
        await self._on_step(_PageState(step.url, step.fields), _AgentOutput(actions), index)
        asked = await self._act(step)
        if on_step_end is not None:
            self.state.last_result = _agent_state(step.outputs).last_result
            # A handoff's wait runs here, after the step, and its answer joins the step's results.
            await on_step_end(self)
            if asked == BROWSER_ANSWER_AFTER_STEP:
                answer = self.state.last_result[-1]
                if answer.error is not None:
                    # The run's own flags decide the outcome; the loop has nothing left to do.
                    raise _RunHalted
                asked = answer.long_term_memory
            if step.takeover is not None:
                self._double.takeover_notes.append(asked)
            elif step.guidance is not None:
                self._double.guidance_notes.append(asked)
        # A done action ends the run where Browser-Use ends it, with its own text and verdict.
        return _ended_by(step_actions)

    async def _act(self, step: ScriptedStep) -> object:
        """Run the step's takeover, guidance or switch; return what a takeover or guidance answered."""
        if step.takeover is not None:
            return await self._hand_over(*step.takeover)
        if step.guidance is not None:
            return await self._ask_the_agent(step.guidance)
        if step.switch is not None:
            assert self._double.switch is not None, "the run was not offered the full browser"
            await self._double.switch(step.switch)
        return None

    async def _hand_over(self, reason: str, category: str) -> object:
        assert self._double.takeover is not None, "the takeover action was never built"
        # Browser-Use validates the action's arguments into its param model first.
        return await self._double.takeover(reason, SensitiveCategory(category))

    async def _wait_for_joiner(self) -> None:
        from app.services.browser.jobs import joiner_lease_held

        for _ in range(500):
            if await joiner_lease_held(self._double.job_id):
                return
            await asyncio.sleep(0.01)
        raise AssertionError("no executor ever joined the job")

    async def _ask_the_agent(self, reason: str) -> object:
        assert self._double.guidance is not None, "the guidance action was never built"
        self._double.guidance_reasons.append(reason)
        return await self._double.guidance(reason)

    async def _wait_for_stop(self) -> None:
        """Sit on the page until the user's stop reaches the agent, as a real run would."""
        for _ in range(500):
            if self._stopped or await self._should_stop():
                self._double.stop_observed = True
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the browser run was never told to stop")


def _reported_actions(step: ScriptedStep) -> list[tuple[str, dict[str, Any]]]:
    """Return the actions the step reports; a takeover, guidance or switch replaces the scripted ones."""
    if step.takeover is not None:
        reason, category = step.takeover
        return [("request_human_takeover", {"reason": reason, "category": category})]
    if step.guidance is not None:
        return [("request_agent_guidance", {"reason": step.guidance})]
    if step.switch is not None:
        return [("continue_in_full_browser", {"category": step.switch.value})]
    return list(step.actions)


def _ended_by(step_actions: list[tuple[str, dict[str, Any]]]) -> _History | None:
    """Return the history a done action among step_actions ends the run with, if one is there."""
    for name, params in step_actions:
        if name == "done":
            return _History(str(params.get("text", "")), bool(params.get("success")))
    return None


class JobWorld:
    """Everything the run touched outside its own process, recorded."""

    def __init__(self, double: BrowserDouble, stream_id: str) -> None:
        self.browser = double
        self.stream_id = stream_id
        self.enqueued: list[BrowserJobRequest] = []
        self.chunks: list[str] = []
        #: What reached any other turn's stream, by stream id.
        self.other_streams: dict[str, list[str]] = {}
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
        #: Each session whose host lease the job renewed.
        self.lease_renewals: list[str] = []
        #: Each job a stop asked ARQ to abort.
        self.aborted: list[str] = []

    def frames(self, stream_id: str | None = None) -> list[dict[str, Any]]:
        """Return each SSE chunk the turn's stream (or another one) carried, decoded."""
        chunks = self.chunks if stream_id is None else self.other_streams.get(stream_id, [])
        return [json.loads(chunk.removeprefix("data: ").strip()) for chunk in chunks]

    def cards(self, stream_id: str | None = None) -> list[dict[str, Any]]:
        """Return the browser card payloads a stream carried, in publish order."""
        return [
            frame["tool_data"]["data"]
            for frame in self.frames(stream_id)
            if "tool_data" in frame and frame["tool_data"].get("tool_name") == "browser_task_data"
        ]

    async def sit_through_lease_renewals(self, count: int) -> int:
        """Wait until the job has renewed its browser's lease count times in all, half a minute of the user's time each; return how many it did.

        Fewer than count means the session ended first.
        """
        for _ in range(500):
            if len(self.lease_renewals) >= count:
                break
            await asyncio.sleep(0.01)
        return len(self.lease_renewals)

    async def settle(self) -> None:
        """End the turn's executor run, then wait out the worker task and the publishes it left behind."""
        # What executor_runner does when the run ends: the relay stops holding the result for it.
        signal_executor_done(self.stream_id)
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        # The relays, which end on the job's terminal frame and the run's end.
        relays = [task for task in wide_events._spawned_tasks if not task.done()]
        await asyncio.gather(*relays, return_exceptions=True)
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
    world = JobWorld(double, stream_id)
    scripted_host = host if host is not None else ScriptedHost()
    browser = _Browser()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    create_session(stream_id, RunKind.LIVE)

    async def _enqueue(
        pool: Any, name: str, payload: dict[str, Any], *, _queue_name: str, _job_id: str
    ) -> object:
        world.enqueued.append(BrowserJobRequest.model_validate(payload))
        double.job_id = world.enqueued[-1].job_id
        world.jobs.append(asyncio.create_task(browser_tasks.run_browser_job({}, payload)))
        return object()

    async def _abort(job_id: str) -> bool:
        """Cancel the job's task, as ARQ's abort cancels the task of a job a worker is running."""
        running = [task for task in world.jobs if not task.done()]
        for task in running:
            task.cancel()
        world.aborted.append(job_id)
        return bool(running)

    patches = [
        patch("app.db.redis.redis_cache.redis", redis),
        patch("app.services.browser.job_stop._abort_if_started", _abort),
        # A guidance request nobody answers must fail the journey in seconds, not
        # sit out the real two-minute budget.
        patch("app.services.browser.job_runner.BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS", 2),
        patch("app.services.browser.agent_run.Agent", double.agent),
        patch("app.services.browser.agent_run.GaiaBrowserSession", lambda **kwargs: browser),
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
        # The models and Jev's gateway are never called: the agent and Jev are scripted.
        patch("app.services.browser.agent_run.build_agent_llm", MagicMock(return_value=object())),
        patch("app.services.browser.agent_run.build_text_model", lambda ledger: object()),
        patch("app.services.browser.agent_run.open_jev_client", _unused_jev_client),
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
        # The turn's stream is live for the whole journey, as a chat turn's is while it streams.
        await StreamManager.start_stream(stream_id, "conv-of-the-turn", "user-of-the-turn")
        try:
            yield world
        finally:
            for task in [*world.jobs, *wide_events._spawned_tasks]:
                task.cancel()
            await asyncio.gather(*world.jobs, *wide_events._spawned_tasks, return_exceptions=True)
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
        # A world with a fallback host has Obscura on its primary and Chrome behind it.
        on_obscura = (
            scripted_host.fallback_url is not None and host_url != scripted_host.fallback_url
        )
        return MagicMock(
            session_id=f"sess-{world.host_sessions}",
            cdp_ws="ws://browser.test/cdp",
            live_ws="ws://browser.test/live",
            engine=BrowserEngine.OBSCURA if on_obscura else BrowserEngine.CHROMIUM,
        )

    def _kill_engine() -> None:
        world.dead_sessions.add(f"sess-{world.host_sessions}")

    double.kill_engine = _kill_engine

    async def _get_host_session(
        session_id: str, host_url: str, *, timeout: float | None = None
    ) -> SessionInfo:
        if session_id in world.dead_sessions:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}"
            )
        return SessionInfo(
            session_id=session_id,
            live=True,
            url=double.url,
        )

    async def _renew_host_lease(session_id: str, host_url: str) -> None:
        if session_id in world.dead_sessions:
            raise BrowserSessionGone(
                f"Browser host returned 404 for {host_url}/sessions/{session_id}/lease"
            )
        world.lease_renewals.append(session_id)

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
        patch("app.services.browser.session.host_client.renew_session_lease", _renew_host_lease),
        patch.object(settings, "BROWSER_FALLBACK_HOST_URL", scripted_host.fallback_url),
        patch("app.services.browser.session.load_storage_state", AsyncMock(return_value=None)),
        patch("app.services.browser.session.save_storage_state", AsyncMock()),
    ]


@contextmanager
def long_waits_pass_quickly() -> Iterator[None]:
    """Make every wait of a second or more take a few milliseconds, so a journey can sit through minutes of a paused run.

    Every such timer then ticks at the same rate; the sub-second polls the
    journeys themselves wait on keep their real length.
    """
    real_sleep = asyncio.sleep

    async def _sleep(delay: float, result: Any = None) -> Any:
        return await real_sleep(_LONG_WAIT_TICK_SECONDS if delay >= 1 else delay, result)

    with patch("asyncio.sleep", _sleep):
        yield


def _delivery_patches(world: JobWorld, stream_id: str) -> list[AbstractContextManager[object]]:
    """Record what reaches the user: the turn's stream, bot messages and photos, and the conversation."""

    async def _publish_chunk(chunk_stream_id: str, chunk: str) -> None:
        if chunk_stream_id == stream_id:
            world.chunks.append(chunk)
        else:
            world.other_streams.setdefault(chunk_stream_id, []).append(chunk)

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
        user_sites: object,
        handle_takeover: Callable[[str, SensitiveCategory], Any],
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

    def __init__(self, browser: _BrowserSession, engine: BrowserEngine) -> None:
        self._browser = browser

    async def screenshot(self) -> str:
        return "ZmFrZS1zY3JlZW5zaG90"

    async def observe(self) -> Any:
        url = await self._browser.get_current_page_url()
        return SimpleNamespace(url=url or "", title="Example", text="", actions=[])


async def _shot_url(index: int) -> str:
    return SHOT_URL_TEMPLATE.format(index=index)


@asynccontextmanager
async def _unused_jev_client() -> AsyncIterator[object]:
    """Jev's gateway, never called: the bursts are scripted."""
    yield object()


async def _narrate(
    result_text: str, msg_type: str, conversation_id: str, user: Any, *, preamble: str
) -> str:
    """Stand in for the comms re-voicing, which is an LLM call; the run's own text is what matters here."""
    return f"NARRATED: {result_text}"


def _user() -> Any:
    return MagicMock(user_id="user-e2e", email="e2e@example.test")
