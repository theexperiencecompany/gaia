"""The browser_task tool: the settings and URL gates, the job it describes, and where its frames go."""

from typing import Any
from unittest.mock import MagicMock

from langchain_core.runnables.config import RunnableConfig
import pytest

from app.agents.tools import browser_tool as tool_mod
from app.agents.tools.browser_tool import browser_task
from app.config.settings import settings
from app.constants.browser import BROWSER_TASK_EVENT, BrowserSessionStatus
from app.models.chat_models import ConversationSource
from app.schemas.browser import BrowserResultSnapshot, BrowserStepSnapshot
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.job_runner import agent_result_message

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
    """The job the tool asked for, and the frames it let the run publish."""

    def __init__(self) -> None:
        self.requests: list[BrowserJobRequest] = []
        self.writes: list[dict[str, Any]] = []

    @property
    def request(self) -> BrowserJobRequest:
        (request,) = self.requests
        return request


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: BrowserResultSnapshot | None = None,
    cards: list[BrowserStepSnapshot] | None = None,
) -> Recorder:
    """Stand in for the job body: record the request, replay any cards through its publisher."""
    recorder = Recorder()
    final = result or BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, success=True, summary="Done"
    )

    async def _execute(request: BrowserJobRequest, *, publish: Any = None) -> BrowserResultSnapshot:
        recorder.requests.append(request)
        for card in cards or []:
            await publish({BROWSER_TASK_EVENT: card.model_dump(mode="json")})
        return final

    monkeypatch.setattr(tool_mod, "execute_browser_job", _execute)
    monkeypatch.setattr(tool_mod, "get_stream_writer", lambda: recorder.writes.append)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", True)
    return recorder


# ---------------------------------------------------------------------------
# the gates — what never reaches the browser at all
# ---------------------------------------------------------------------------


async def test_disabled_message_is_exact_and_no_job_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch)
    monkeypatch.setattr(tool_mod.settings, "BROWSER_USE_ENABLED", False)

    out = await browser_task.ainvoke({"task": "do it"}, config=UI_CONFIG)

    assert out == "Browser automation is currently disabled."
    assert recorder.requests == []


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
    assert recorder.requests == []


async def test_the_private_network_switch_lets_a_local_start_url_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch)
    monkeypatch.setattr(settings, "BROWSER_HOST_ALLOW_PRIVATE_NETWORK", True)

    await browser_task.ainvoke(
        {"task": "check the dev site", "start_url": "http://127.0.0.1:3000"}, config=UI_CONFIG
    )

    assert recorder.request.start_url == "http://127.0.0.1:3000"


# ---------------------------------------------------------------------------
# the job the tool describes
# ---------------------------------------------------------------------------


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
    }


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

    first, second = recorder.requests
    assert len(first.job_id) == 32
    assert first.job_id != second.job_id


# ---------------------------------------------------------------------------
# what the turn sees
# ---------------------------------------------------------------------------


async def test_the_runs_cards_go_straight_onto_this_turns_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run still belongs to the turn, so its frames reach the graph's writer unchanged — normalization happens downstream, exactly as before."""
    recorder = _install(
        monkeypatch, cards=[BrowserStepSnapshot(index=2, goal="find the menu", url="https://x")]
    )

    await browser_task.ainvoke({"task": "x"}, config=UI_CONFIG)

    assert [list(write) for write in recorder.writes] == [[BROWSER_TASK_EVENT]]
    assert recorder.writes[0][BROWSER_TASK_EVENT]["goal"] == "find the menu"


async def test_the_result_is_handed_back_as_the_runs_own_guidance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.COMPLETED, success=True, summary="Booked the table."
    )
    _install(monkeypatch, result=result)

    out = await browser_task.ainvoke({"task": "book a table"}, config=UI_CONFIG)

    assert out == agent_result_message(result)
    assert out.startswith("Booked the table.")


async def test_the_surface_the_task_came_from_is_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    fake_log = MagicMock()
    monkeypatch.setattr(tool_mod, "log", fake_log)

    await browser_task.ainvoke({"task": "x"}, config=BOT_CONFIG)

    logged = [call.kwargs["browser"] for call in fake_log.set.call_args_list]
    assert {"operation": "task", "source_category": "bot"} in logged
