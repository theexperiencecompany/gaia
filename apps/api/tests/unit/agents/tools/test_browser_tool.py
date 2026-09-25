"""The browser_task tool: the gates, the slot it claims, the job it enqueues, and the relay it leaves behind."""

from collections.abc import Coroutine
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.constants.browser import BROWSER_JOB_QUEUE, BROWSER_JOB_TASK
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.schemas.browser_job import BrowserJobRequest, BrowserJobState, BrowserJobStatus
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

UI_CONFIG: RunnableConfig = {
    "configurable": {"user_id": "u1", "thread_id": "c1", "stream_id": "s1", "source_category": "ui"}
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
        self.relays: list[tuple[str, str]] = []
        self.spawned: list[str] = []
        self.queues: list[str | None] = []
        self.pools: list[object] = []
        self.pool = MagicMock(name="pool")

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
) -> Recorder:
    """Wire every seam the enqueue touches; holder is the job already owning the slot."""
    recorder = Recorder()

    async def _claim(conversation_id: str, job_id: str) -> str | None:
        recorder.claims.append((conversation_id, job_id))
        return holder

    async def _put_state(state: BrowserJobState) -> None:
        recorder.states.append(state)

    async def _release(conversation_id: str, job_id: str) -> None:
        recorder.released.append((conversation_id, job_id))

    async def _enqueue(
        pool: object, function: str, payload: dict[str, Any], *, _queue_name: str | None = None
    ) -> object | None:
        recorder.enqueued.append((function, payload))
        recorder.pools.append(pool)
        recorder.queues.append(_queue_name)
        if enqueue_error is not None:
            raise enqueue_error
        return enqueued_job

    async def _relayed() -> None:
        return None

    def _relay(job_id: str, stream_id: str) -> Coroutine[Any, Any, None]:
        # Recorded on the call, not in the body: the tool spawns this coroutine
        # rather than awaiting it, so a body-side record would never run.
        recorder.relays.append((job_id, stream_id))
        return _relayed()

    def _spawn(operation: str, coro: Any, **_context: Any) -> MagicMock:
        recorder.spawned.append(operation)
        coro.close()
        return MagicMock()

    monkeypatch.setattr(tool_mod, "claim_conversation_slot", _claim)
    monkeypatch.setattr(tool_mod, "put_job_state", _put_state)
    monkeypatch.setattr(tool_mod, "release_conversation_slot", _release)
    monkeypatch.setattr(tool_mod, "enqueue_worker_job", _enqueue)
    monkeypatch.setattr(tool_mod, "relay_job_events", _relay)
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

    out = await browser_task.ainvoke(
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
        await browser_task.ainvoke(
            {"task": "x", "start_url": "http://169.254.169.254/latest/meta-data"},
            config=UI_CONFIG,
        )

    # The rate limiter warns too when the turn carries no user; only the refusal carries an error.
    (warning,) = [w for w in event["warnings"] if "error" in w]
    assert warning["msg"].startswith(LogTag.BROWSER)
    assert warning["error"] == "refusing to connect to non-public address 169.254.169.254"
    assert event["browser"] == {"operation": "task", "source_category": "ui"}


# ---------------------------------------------------------------------------
# the job the tool enqueues
# ---------------------------------------------------------------------------


async def test_the_job_crosses_the_queue_under_the_name_the_worker_registers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enqueue site and worker.py share one constant; a drifting string enqueues a job nobody runs."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

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

    await browser_task.ainvoke(
        {"task": "book a table", "start_url": "https://resy.com"}, config=config
    )

    request = recorder.request
    assert request.model_dump(exclude={"job_id"}) == {
        "user_id": "u1",
        "conversation_id": "conv-9",
        "task": "book a table",
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

    await browser_task.ainvoke(
        {
            "task": "log in with hunter2-secret",
            "secrets": {"password": "hunter2-secret", "otp": ""},
        },
        config=UI_CONFIG,
    )

    assert recorder.request.secrets == {"password": "hunter2-secret"}
    assert "hunter2-secret" not in recorder.request.task
    assert "hunter2-secret" not in recorder.states[0].task


async def test_the_claimed_slot_the_queued_state_and_the_job_all_name_one_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three keys are minted from this id; a mismatch orphans the state a joiner reads or the slot the worker releases."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": "book a table"}, config=UI_CONFIG)

    job_id = recorder.request.job_id
    assert recorder.claims == [("c1", job_id)]
    assert recorder.states == [
        BrowserJobState(job_id=job_id, status=BrowserJobStatus.QUEUED, task="book a table")
    ]


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

    await browser_task.ainvoke({"task": "x"}, config=config)

    assert recorder.request.conversation_id == "conv-9"


async def test_conversation_id_falls_back_to_thread_id(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch)
    config: RunnableConfig = {"configurable": {"user_id": "u1", "thread_id": "t-7"}}

    await browser_task.ainvoke({"task": "x"}, config=config)

    assert recorder.request.conversation_id == "t-7"


async def test_an_unknown_conversation_source_is_dropped_rather_than_carried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker compares the source against the platforms it can deliver to; an unparsed string would be a platform nobody can send on."""
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {"user_id": "u1", "thread_id": "c1", "conversation_source": "carrier-dove"}
    }

    await browser_task.ainvoke({"task": "x"}, config=config)

    assert recorder.request.conversation_source is None


async def test_missing_identifiers_degrade_to_blank_and_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": "x"}, config={"configurable": {}})

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

    await browser_task.coroutine(config={}, task="x")

    assert recorder.request.user_id == ""


async def test_each_call_describes_its_own_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job id keys the run's state, feed and cancel flag; a shared id would cross two runs' wires."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)
    await browser_task.ainvoke({"task": "y"}, config=UI_CONFIG)

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

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert recorder.released == []
    assert recorder.spawned == []


async def test_a_second_task_is_pointed_at_the_run_already_holding_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model has to collect the running job, not start another; the event names both sides of the refusal."""
    recorder = _install(monkeypatch, holder="job-already-running")

    async with captured_wide_event() as event:
        out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert out == tool_mod._SLOT_HELD.format(holder="job-already-running")
    assert recorder.enqueued == []
    assert event["browser"] == {
        "operation": "task",
        "source_category": "ui",
        "refused": "slot_held",
        "slot_holder": "job-already-running",
    }


# ---------------------------------------------------------------------------
# the enqueue failing
# ---------------------------------------------------------------------------


async def test_a_dropped_enqueue_frees_the_slot_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged slot would refuse every later browser task in this conversation for a run that never started."""
    recorder = _install(monkeypatch, enqueued_job=None)

    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert out == "I couldn't start the browser task right now. Try again in a moment."
    assert recorder.released == [("c1", recorder.request.job_id)]
    assert recorder.spawned == []


async def test_a_job_the_queue_did_not_take_is_an_error_on_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARQ answers None for a job id it already holds; the run never starts, so it must page as an error, naming the job."""
    recorder = _install(monkeypatch, enqueued_job=None)

    async with captured_wide_event() as event:
        await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    (error,) = event["errors"]
    assert error["msg"].startswith(LogTag.BROWSER)
    assert error["browser"] == {"job_id": recorder.request.job_id}


async def test_an_enqueue_that_raises_is_reported_and_frees_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redis being down must not surface as a tool exception the model narrates as a browser failure."""
    recorder = _install(monkeypatch, enqueue_error=ConnectionError("redis is down"))

    out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert out == "I couldn't start the browser task right now. Try again in a moment."
    assert recorder.released == [("c1", recorder.request.job_id)]


async def test_an_enqueue_that_raises_carries_the_cause_on_the_wide_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool swallows the exception, so the event is where "redis is down" has to surface."""
    recorder = _install(monkeypatch, enqueue_error=ConnectionError("redis is down"))

    async with captured_wide_event() as event:
        await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    (error,) = event["errors"]
    assert error["msg"].startswith(LogTag.BROWSER)
    assert error["error_type"] == "ConnectionError"
    assert error["error"] == "redis is down"
    assert error["browser"] == {"job_id": recorder.request.job_id}


async def test_the_job_is_queued_on_the_shared_worker_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert recorder.pools == [recorder.pool]


# ---------------------------------------------------------------------------
# the relay and the notice
# ---------------------------------------------------------------------------


async def test_a_started_task_keeps_its_slot_and_relays_its_cards_onto_this_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model is told the run started under its job id, and the run's cards follow on this turn's stream."""
    recorder = _install(monkeypatch)

    async with captured_wide_event() as event:
        out = await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    job_id = recorder.request.job_id
    assert out == tool_mod._STARTED.format(job_id=job_id)
    assert recorder.released == []
    assert recorder.relays == [(job_id, "s1")]
    # The spawned task's wide event is named by this operation.
    assert recorder.spawned == ["browser_job_relay"]
    assert event["browser"] == {"operation": "task", "source_category": "ui", "job_id": job_id}


async def test_no_stream_means_no_relay_but_the_job_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn with no stream has nowhere to replay to; the worker still runs the job and delivers the result itself."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke(
        {"task": "x"}, config={"configurable": {"user_id": "u1", "thread_id": "c1"}}
    )

    assert recorder.relays == []
    assert len(recorder.enqueued) == 1


async def test_the_users_own_words_ride_along_with_the_executors_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The executor twice rewrote "tick the second checkbox" into an invented label, and the step was skipped."""
    recorder = _install(monkeypatch)
    config: RunnableConfig = {
        "configurable": {
            "user_id": "u1",
            "conversation_id": "conv-9",
            "user_request": "use the browser:   tick the second checkbox\nand submit",
        }
    }

    await browser_task.ainvoke(
        {"task": "Tick the box labeled Checked, then submit."}, config=config
    )

    task = recorder.request.task
    assert task.startswith("Tick the box labeled Checked, then submit.")
    assert "own words" in task
    assert "use the browser: tick the second checkbox and submit" in task


async def test_a_turn_with_no_user_request_leaves_the_task_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)
    config: RunnableConfig = {"configurable": {"user_id": "u1", "conversation_id": "conv-9"}}

    await browser_task.ainvoke({"task": "book a table"}, config=config)

    assert recorder.request.task == "book a table"


async def test_a_task_that_names_one_page_starts_there_so_its_saved_login_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: with no start URL, a signed-in /secure bounced to login and its login saved nowhere."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke(
        {"task": "Open https://the-internet.herokuapp.com/secure and read the heading."},
        config=UI_CONFIG,
    )

    assert recorder.request.start_url == "https://the-internet.herokuapp.com/secure"


@pytest.mark.parametrize(
    ("task", "page"),
    [
        ("Read https://en.wikipedia.org/wiki/SpaceX.", "https://en.wikipedia.org/wiki/SpaceX"),
        ("Is it up? https://example.com/status?", "https://example.com/status"),
        ("Check the rules.https://example.com/rules", "https://example.com/rules"),
    ],
    ids=["full-stop-after", "question-mark-after", "full-stop-before"],
)
async def test_the_sentence_around_the_one_page_is_not_part_of_it(
    monkeypatch: pytest.MonkeyPatch, task: str, page: str
) -> None:
    """Punctuation closing the sentence is not in the URL, and a full stop typed right before it names no second site."""
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": task}, config=UI_CONFIG)

    assert recorder.request.start_url == page


@pytest.mark.parametrize(
    "task",
    [
        "Go to news.ycombinator.com, then https://en.wikipedia.org and compare them.",
        "Find the cheapest flight to London.",
    ],
    ids=["two-sites", "no-url"],
)
async def test_a_task_without_exactly_one_page_gets_no_start_url(
    monkeypatch: pytest.MonkeyPatch, task: str
) -> None:
    recorder = _install(monkeypatch)

    await browser_task.ainvoke({"task": task}, config=UI_CONFIG)

    assert recorder.request.start_url is None


async def test_a_private_page_named_in_the_task_is_refused_before_any_job_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)

    reply = await browser_task.ainvoke(
        {"task": "read http://169.254.169.254/latest/meta-data for me"}, config=UI_CONFIG
    )

    assert "can't open" in reply
    assert recorder.enqueued == []
