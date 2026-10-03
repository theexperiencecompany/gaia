"""The browser_task tool: the gates, the slot it claims, the job it enqueues, and how its ending comes back."""

from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.session import RunKind, create_session, teardown_session
from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.constants.browser import (
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_STOPPED_NOTICE,
    BROWSER_JOB_TASK,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskSecret
from app.schemas.browser_job import (
    BrowserJobFinished,
    BrowserJobRequest,
    BrowserJobState,
    BrowserJobStatus,
)
from app.services.browser import job_relay, jobs
from app.services.browser.job_events import JOB_TERMINAL_FRAME, publish_job_event
from app.services.browser.job_stop import stop_browser_job
from app.services.browser.job_teller import end_job
from tests.helpers import captured_wide_event

# A job that never runs records its ending in Redis (jobs.record_ending), so each test gets its own fakeredis.
pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("fake_redis")]

TOOL_CALL_ID = "call-browser-1"
#: One card a run publishes to its feed.
CARD: dict[str, object] = {
    "tool_data": {"tool_name": "browser_task_data", "data": {"kind": "step"}}
}


async def _start(args: dict[str, Any], config: RunnableConfig) -> str:
    """Call browser_task as the tool node does: a model tool call carrying its id."""
    message = await browser_task.ainvoke(
        {"args": args, "name": "browser_task", "type": "tool_call", "id": TOOL_CALL_ID},
        config=config,
    )
    return str(message.content)


UI_CONFIG: RunnableConfig = {
    "configurable": {
        "user_id": "u1",
        "conversation_id": "c1",
        "stream_id": "s1",
        "source_category": "ui",
        "bot_message_id": "bot-msg-1",
    }
}
#: A workflow's run: no live conversation to collect a background result, so the call blocks.
HEADLESS_CONFIG: RunnableConfig = {
    "configurable": {
        "user_id": "u1",
        "conversation_id": "c1",
        "stream_id": "s1",
        "execution_mode": "background",
    }
}
BOT_CONFIG: RunnableConfig = {
    "configurable": {
        "user_id": "u1",
        "conversation_id": "c1",
        "stream_id": "s1",
        "source_category": "bot",
        "conversation_source": "discord",
    }
}


class Recorder:
    """Everything the tool did to the world before returning."""

    def __init__(self) -> None:
        self.claims: list[tuple[str, str]] = []
        self.states: list[BrowserJobState] = []
        self.enqueued: list[tuple[str, dict[str, Any]]] = []
        self.released: list[tuple[str, str]] = []
        #: Each background relay: (job, the message its cards fold into).
        self.relays: list[tuple[str, str | None]] = []
        #: Each job a headless call followed to its end: (job, conversation, shown on a stream).
        self.followed: list[tuple[str, str, bool]] = []
        self.spawned: list[str] = []
        self.queues: list[str | None] = []
        self.pools: list[object] = []
        self.pool = MagicMock(name="pool")
        #: The ARQ job id each enqueue asked for: the one a stop aborts.
        self.job_ids: list[str | None] = []
        #: The conversation's latest job, as the join and a stop find it.
        self.latest: list[tuple[str, str]] = []
        #: Latest-job pointers put back after a job that never ran.
        self.restored: list[tuple[str, str, str | None]] = []

    @property
    def request(self) -> BrowserJobRequest:
        """The one job that crossed the queue, as the worker will read it back."""
        ((_function, payload),) = self.enqueued
        return BrowserJobRequest.model_validate(payload)


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    holder: str | None = None,
    enqueued_job: object | None = object(),
    enqueue_error: Exception | None = None,
    latest_before: dict[str, str] | None = None,
) -> Recorder:
    """Wire every seam the enqueue touches; holder is the job already owning the slot."""
    recorder = Recorder()
    latest_before = latest_before or {}

    async def _claim(conversation_id: str, job_id: str) -> str | None:
        recorder.claims.append((conversation_id, job_id))
        return holder

    async def _put_state(state: BrowserJobState) -> None:
        recorder.states.append(state)

    async def _release(conversation_id: str, job_id: str) -> None:
        recorder.released.append((conversation_id, job_id))

    async def _enqueue(
        pool: object,
        function: str,
        payload: dict[str, Any],
        *,
        _queue_name: str | None = None,
        _job_id: str | None = None,
    ) -> object | None:
        recorder.enqueued.append((function, payload))
        recorder.job_ids.append(_job_id)
        recorder.pools.append(pool)
        recorder.queues.append(_queue_name)
        if enqueue_error is not None:
            raise enqueue_error
        return enqueued_job

    async def _relayed() -> None:
        return None

    def _relay(request: BrowserJobRequest, message_id: str | None) -> Coroutine[Any, Any, None]:
        # Recorded on the call, not in the body: the tool spawns this coroutine
        # rather than awaiting it, so a body-side record would never run.
        recorder.relays.append((request.job_id, message_id))
        return _relayed()

    async def _follow(job_id: str, conversation_id: str, sink: object) -> None:
        recorder.followed.append((job_id, conversation_id, sink is not tool_mod._ignore))

    def _spawn(operation: str, coro: Any, **_context: Any) -> MagicMock:
        recorder.spawned.append(operation)
        coro.close()
        return MagicMock()

    monkeypatch.setattr(tool_mod, "claim_conversation_slot", _claim)
    monkeypatch.setattr(tool_mod, "put_job_state", _put_state)
    monkeypatch.setattr(tool_mod, "release_conversation_slot", _release)

    async def _latest(key: str, job_id: str) -> str | None:
        recorder.latest.append((key, job_id))
        return latest_before.get(key)

    async def _restore(key: str, job_id: str, previous: str | None) -> None:
        recorder.restored.append((key, job_id, previous))

    monkeypatch.setattr(tool_mod, "restore_latest_job", _restore)

    monkeypatch.setattr(tool_mod, "set_latest_job", _latest)
    monkeypatch.setattr(tool_mod, "enqueue_worker_job", _enqueue)
    monkeypatch.setattr(tool_mod, "relay_job_cards", _relay)
    monkeypatch.setattr(tool_mod, "follow_job_cards", _follow)
    monkeypatch.setattr(tool_mod, "spawn_logged_task", _spawn)
    monkeypatch.setattr(
        tool_mod.RedisPoolManager, "get_pool", AsyncMock(return_value=recorder.pool)
    )
    return recorder


# ---------------------------------------------------------------------------
# the gates — what never reaches the queue at all
# ---------------------------------------------------------------------------


async def test_a_private_start_url_is_refused_before_any_job_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A literal loopback/metadata start URL never reaches the host; the model is told why."""
    recorder = _install(monkeypatch)

    out = await _start(
        {"task": "read the metadata", "start_url": "http://169.254.169.254/latest/meta-data"},
        config=UI_CONFIG,
    )

    assert out == (
        "I can't open http://169.254.169.254/latest/meta-data: refusing to connect to "
        "non-public address 169.254.169.254. Only public http(s) sites are reachable."
    )
    assert recorder.claims == []
    assert recorder.enqueued == []


async def test_a_refused_start_url_is_reported_on_the_wide_event_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal never reaches a job, so the wide event is the only record of why a run did not start."""
    _install(monkeypatch)

    async with captured_wide_event() as event:
        await _start(
            {"task": "x", "start_url": "http://169.254.169.254/latest/meta-data"},
            config=UI_CONFIG,
        )

    # The rate limiter warns too when the turn carries no user; only the refusal carries an error.
    (warning,) = [w for w in event["warnings"] if "error" in w]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["error"] == "refusing to connect to non-public address 169.254.169.254"
    assert event["browser"] == {"operation": "task", "source_category": "ui", "in_background": True}


# ---------------------------------------------------------------------------
# the job the tool enqueues
# ---------------------------------------------------------------------------


async def test_the_job_crosses_the_queue_under_the_name_the_worker_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enqueue site and worker.py share one constant; a drifting string enqueues a job nobody runs."""
    recorder = _install(monkeypatch)

    await _start({"task": "x"}, config=UI_CONFIG)

    ((function, _payload),) = recorder.enqueued
    assert function == BROWSER_JOB_TASK
    assert recorder.queues == [BROWSER_JOB_QUEUE]


async def test_the_job_carries_the_turns_identity_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "stream_id": "s1",
            "root_request_id": "req-42",
            "source_category": "bot",
            "conversation_source": "discord",
        }
    }

    await _start({"task": "book a table", "start_url": "https://resy.com"}, config=config)

    request = recorder.request
    assert request.model_dump(exclude={"job_id"}) == {
        "tool_call_id": TOOL_CALL_ID,
        "user_id": "u1",
        "conversation_id": "conv-9",
        "task": "book a table",
        "in_background": True,
        "start_url": "https://resy.com",
        "stream_id": "s1",
        "root_request_id": "req-42",
        "source_category": "bot",
        "conversation_source": ConversationSource.DISCORD,
        "secrets": {},
    }


async def test_a_credential_reaches_the_job_and_never_the_task_anyone_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await _start(
        {
            "task": "log in with hunter2-secret",
            "secrets": {
                "password": {"value": "hunter2-secret", "site": "https://www.Shop.test/login"},
                "otp": {"value": "", "site": "shop.test"},
            },
        },
        config=UI_CONFIG,
    )

    assert recorder.request.secrets == {
        "password": BrowserTaskSecret(value="hunter2-secret", site="shop.test")
    }
    assert "hunter2-secret" not in recorder.request.task
    assert "hunter2-secret" not in recorder.states[0].task


async def test_the_claimed_slot_the_queued_state_and_the_job_all_name_one_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three keys are minted from this id; a mismatch orphans the state a stop reads or the slot the worker releases."""
    recorder = _install(monkeypatch)

    await _start({"task": "book a table"}, config=UI_CONFIG)

    job_id = recorder.request.job_id
    assert recorder.claims == [("c1", job_id)]
    assert recorder.states == [
        BrowserJobState(
            job_id=job_id,
            status=BrowserJobStatus.QUEUED,
            task="book a table",
            conversation_id="c1",
            user_id="u1",
            in_background=True,
        )
    ]
    # The ARQ job a stop aborts, and the job a stop finds once the slot lapses.
    assert recorder.job_ids == [job_id]
    assert recorder.latest == [("c1", job_id)]


async def test_a_bot_run_is_found_from_the_requesters_bot_chat_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its handoffs are answered, and a /stop reaches it, from the chat the bot talks to the user in."""
    recorder = _install(monkeypatch)

    await _start({"task": "book a table"}, config=BOT_CONFIG)

    job_id = recorder.request.job_id
    assert recorder.latest == [("c1", job_id), ("discord:u1", job_id)]


async def test_conversation_id_prefers_the_user_facing_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handoff is resolved by a chat reply keyed on the comms conversation id, so the executor's derived thread_id must never win."""
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "thread_id": "executor_conv-9",
        }
    }

    await _start({"task": "x"}, config=config)

    assert recorder.request.conversation_id == "conv-9"


async def test_conversation_id_falls_back_to_thread_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch)
    config: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "t-7"}}

    await _start({"task": "x"}, config=config)

    assert recorder.request.conversation_id == "t-7"


async def test_an_unknown_conversation_source_is_dropped_rather_than_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker compares the source against the platforms it can deliver to; an unparsed string would be a platform nobody can send on."""
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {"user_id": "u1", "thread_id": "c1", "conversation_source": "carrier-dove"}
    }

    await _start({"task": "x"}, config=config)

    assert recorder.request.conversation_source is None


async def test_missing_identifiers_degrade_to_blank_and_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await _start({"task": "x"}, config={"configurable": {}})

    request = recorder.request
    assert request.user_id == ""
    assert request.conversation_id == ""
    assert request.stream_id is None
    assert request.root_request_id is None


async def test_a_config_with_no_configurable_key_still_degrades_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the raw coroutine, not ainvoke, because LangChain's ensure_config always injects configurable; without the empty-dict fallback the next line raises AttributeError on None."""
    recorder = _install(monkeypatch)

    await browser_task.coroutine(config={}, tool_call_id=TOOL_CALL_ID, task="x")

    assert recorder.request.user_id == ""


async def test_each_call_describes_its_own_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job id keys the run's state, feed and cancel flag; a shared id would cross two runs' wires."""
    recorder = _install(monkeypatch)

    await _start({"task": "x"}, config=UI_CONFIG)
    await _start({"task": "y"}, config=UI_CONFIG)

    first, second = (BrowserJobRequest.model_validate(p) for _, p in recorder.enqueued)
    assert len(first.job_id) == 32
    assert first.job_id != second.job_id


# ---------------------------------------------------------------------------
# one browser task per conversation
# ---------------------------------------------------------------------------


async def test_a_refused_task_does_not_release_the_running_jobs_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Releasing here would free the slot out from under the run that owns it."""
    recorder = _install(monkeypatch, holder="job-already-running")

    await _start({"task": "x"}, config=UI_CONFIG)

    assert recorder.released == []
    assert recorder.spawned == []


async def test_a_second_task_is_pointed_at_the_run_already_holding_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model has to collect the running job, not start another; the event names both sides of the refusal."""
    recorder = _install(monkeypatch, holder="job-already-running")

    async with captured_wide_event() as event:
        out = await _start({"task": "x"}, config=UI_CONFIG)

    assert out == tool_mod._SLOT_HELD.format(holder="job-already-running")
    assert recorder.enqueued == []
    assert event["browser"] == {
        "operation": "task",
        "source_category": "ui",
        "in_background": True,
        "refused": "slot_held",
        "slot_holder": "job-already-running",
    }


async def test_a_stop_while_the_job_is_being_queued_reaches_it_before_it_runs(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A worker may take the job the moment it is queued; a stop from then on must find it."""
    _install(monkeypatch)
    monkeypatch.setattr(tool_mod, "put_job_state", jobs.put_job_state)
    monkeypatch.setattr(tool_mod, "set_latest_job", jobs.set_latest_job)
    monkeypatch.setattr(tool_mod.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    stopped: list[str | None] = []

    async def _stop_lands_as_it_queues(*_args: object, _job_id: str, **_kwargs: object) -> object:
        stopped.append(await stop_browser_job("c1"))
        return object()

    monkeypatch.setattr(tool_mod, "enqueue_worker_job", _stop_lands_as_it_queues)

    await _start({"task": "book a table"}, config=UI_CONFIG)

    [job_id] = stopped
    assert job_id is not None
    assert await jobs.job_cancel_requested(job_id)


# ---------------------------------------------------------------------------
# the enqueue failing
# ---------------------------------------------------------------------------


async def test_a_dropped_enqueue_frees_the_slot_and_says_so(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A wedged slot would refuse every later browser task in this conversation for a run that never started."""
    recorder = _install(monkeypatch, enqueued_job=None)

    out = await _start({"task": "x"}, config=UI_CONFIG)

    # Already findable by a stop, so its ending is recorded: over, not queued forever.
    ending = await jobs.done_state(recorder.request.job_id)
    assert isinstance(ending, BrowserJobFinished)
    assert (ending.result.status, ending.result.success) == (BrowserSessionStatus.FAILED, False)

    assert out == "I couldn't start the browser task right now. Try again in a moment."
    assert recorder.released == [("c1", recorder.request.job_id)]
    assert recorder.spawned == []
    # This reply told it: nothing lands in the inbox to tell it again.
    assert await ExecutorInbox("c1").read() == []


async def test_a_job_the_queue_did_not_take_leaves_the_chats_latest_job_where_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A /stop in the requester's bot chat found the job that never ran, not the one still running."""
    recorder = _install(monkeypatch, enqueued_job=None, latest_before={"discord:u1": "job-running"})

    await _start({"task": "x"}, config=BOT_CONFIG)

    job_id = recorder.request.job_id
    assert recorder.restored == [("c1", job_id, None), ("discord:u1", job_id, "job-running")]


async def test_a_job_the_queue_did_not_take_is_an_error_on_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARQ answers None for a job id it already holds; the run never starts, so it must page as an error, naming the job."""
    recorder = _install(monkeypatch, enqueued_job=None)

    async with captured_wide_event() as event:
        await _start({"task": "x"}, config=UI_CONFIG)

    (error,) = event["errors"]
    assert error["msg"].startswith(LogTag.BROWSER)
    assert error["browser"] == {"job_id": recorder.request.job_id}


async def test_an_enqueue_that_raises_is_reported_and_frees_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis being down must not surface as a tool exception the model narrates as a browser failure."""
    recorder = _install(monkeypatch, enqueue_error=ConnectionError("redis is down"))

    out = await _start({"task": "x"}, config=UI_CONFIG)

    assert out == "I couldn't start the browser task right now. Try again in a moment."
    assert recorder.released == [("c1", recorder.request.job_id)]


async def test_an_enqueue_that_raises_carries_the_cause_on_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool swallows the exception, so the event is where "redis is down" has to surface."""
    recorder = _install(monkeypatch, enqueue_error=ConnectionError("redis is down"))

    async with captured_wide_event() as event:
        await _start({"task": "x"}, config=UI_CONFIG)

    (error,) = event["errors"]
    assert error["msg"].startswith(LogTag.BROWSER)
    assert error["error_type"] == "ConnectionError"
    assert error["error"] == "redis is down"
    assert error["browser"] == {"job_id": recorder.request.job_id}


async def test_the_job_is_queued_on_the_shared_worker_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await _start({"task": "x"}, config=UI_CONFIG)

    assert recorder.pools == [recorder.pool]


# ---------------------------------------------------------------------------
# the relay and the notice
# ---------------------------------------------------------------------------


async def test_a_started_task_acks_at_once_and_folds_its_cards_into_this_turns_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model is told the run started and its result arrives on its own; the cards fold into the turn's message."""
    recorder = _install(monkeypatch)

    async with captured_wide_event() as event:
        out = await _start({"task": "x"}, config=UI_CONFIG)

    job_id = recorder.request.job_id
    assert out == tool_mod._STARTED.format(job_id=job_id)
    assert recorder.released == []
    assert recorder.relays == [(job_id, "bot-msg-1")]
    assert recorder.followed == []
    # The spawned task's wide event is named by this operation.
    assert recorder.spawned == ["browser_job_relay"]
    assert event["browser"] == {
        "operation": "task",
        "source_category": "ui",
        "in_background": True,
        "job_id": job_id,
    }


async def _run_headless_until(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
    ending: BrowserJobFinished | None,
) -> tuple[str, Recorder]:
    """Start a headless task whose worker ends the job as it is queued: on ending, or on a stop."""
    recorder = _install(monkeypatch)
    # A stop reads ARQ's keys on the same fake Redis.
    monkeypatch.setattr(tool_mod.RedisPoolManager, "get_pool", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(tool_mod, "put_job_state", jobs.put_job_state)
    monkeypatch.setattr(tool_mod, "follow_job_cards", job_relay.follow_job_cards)

    async def _worker_ends_it(
        _pool: object, function: str, payload: dict[str, Any], *, _job_id: str, **_kwargs: object
    ) -> object:
        recorder.enqueued.append((function, payload))
        if ending is None:
            await stop_browser_job("c1")
        else:
            await end_job(_job_id, ending)
        await publish_job_event(_job_id, CARD)
        await publish_job_event(_job_id, JOB_TERMINAL_FRAME)
        return object()

    monkeypatch.setattr(tool_mod, "enqueue_worker_job", _worker_ends_it)
    monkeypatch.setattr(tool_mod, "set_latest_job", jobs.set_latest_job)
    return await _start({"task": "book a table"}, config=HEADLESS_CONFIG), recorder


async def test_a_headless_task_blocks_until_the_job_ends_and_returns_its_result(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    """A workflow has no inbox to be woken by: the result must come back on the call itself, told once."""
    done = BrowserJobFinished(
        result=BrowserResultSnapshot(
            status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked for 7pm."
        )
    )

    session = create_session("s1", RunKind.LIVE)
    try:
        async with captured_wide_event() as event:
            out, recorder = await _run_headless_until(monkeypatch, fake_redis, done)
    finally:
        teardown_session("s1")

    assert recorder.request.in_background is False
    # The run's cards reach the run's own stream while it waits, as a workflow saves them.
    assert session.tool_events == [CARD]
    assert event["browser"]["ending"] == "finished"
    assert out.startswith(
        f"The browser task you started (job {recorder.request.job_id}) has ended."
    )
    assert "Booked for 7pm." in out
    assert recorder.relays == []
    assert await ExecutorInbox("c1").read() == []


async def test_a_stopped_headless_task_returns_the_stop(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.aioredis.FakeRedis
) -> None:
    out, recorder = await _run_headless_until(monkeypatch, fake_redis, None)

    assert out == BROWSER_JOB_STOPPED_NOTICE.format(job_id=recorder.request.job_id)
    assert await ExecutorInbox("c1").read() == []


async def test_the_job_runs_the_executors_task_never_the_users_raw_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A password typed in chat must not ride into the task, the job state and the run's logs."""
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "user_request": "log into my bank, my password is hunter2",
        }
    }

    await _start({"task": "Log into the bank"}, config=config)

    assert recorder.request.task == "Log into the bank"


async def test_a_feed_that_closed_with_no_ending_is_reported_as_a_run_that_could_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    async with captured_wide_event() as event:
        out = await _start({"task": "x"}, config=HEADLESS_CONFIG)

    job_id = recorder.request.job_id
    assert recorder.followed == [(job_id, "c1", True)]
    assert out == tool_mod._NO_ENDING.format(job_id=job_id)
    [error] = event["errors"]
    assert error["msg"] == f"{LogTag.BROWSER} Browser job feed closed with no ending recorded"
    assert error["browser"] == {"job_id": job_id}


async def test_a_headless_run_with_no_stream_follows_the_feed_without_showing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await _start({"task": "x"}, config={"configurable": {"user_id": "u1", "thread_id": "c9"}})

    assert recorder.followed == [(recorder.request.job_id, "c9", False)]
