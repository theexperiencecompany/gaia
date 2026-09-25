"""A Jev burst: why it stops, what it hands the agent, what Jev is asked, and that no secret leaves the page."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field, replace
import itertools
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from browser_use.llm.exceptions import ModelProviderError
import pytest

from app.constants.browser import (
    JEV_SECRET_MASK,
    JEV_STALE_LIMIT,
    JEV_UNCHANGED_LIMIT,
    JevOperation,
    JevStop,
)
from app.services.browser.jev import loop as loop_mod
from app.services.browser.jev.decision import (
    GENERATE,
    NONE_VALUE,
    Decision,
    RecentAction,
    Visited,
    describe_field,
)
from app.services.browser.jev.gateway import JevEvaluation, JevGatewayError, JevUsage
from app.services.browser.jev.loop import BurstContext, BurstResult, JevRunner, JevStep, OpenedPage
from app.services.browser.jev.page import (
    Covered,
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
from tests.unit.services.browser.jev.conftest import (
    FIELD,
    FakePage,
    decision,
    page_state,
)

pytestmark = pytest.mark.unit

SECRET = "hunter2-secret"
MASKED = "<secret>password</secret>"
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down", delta=560)


def _secrets(*sites: str) -> RunSecrets:
    return RunSecrets({"password": SECRET}, list(sites or ["site.test"]))


class _Stalls:
    def __init__(self, notes: list[str] | None = None) -> None:
        self._notes = notes or []

    def take(self) -> list[str]:
        taken, self._notes = self._notes, []
        return taken


@dataclass
class _Jev:
    """Jev's two questions, scripted: each decision is taken in turn, and what Jev was asked is kept."""

    decisions: list[Decision]
    value: str = NONE_VALUE
    value_error: Exception | None = None
    #: Runs as Jev answers each decision, for a page that moves while Jev decides.
    on_decide: Callable[[], None] | None = None
    decided: list[dict[str, Any]] = field(default_factory=list)
    chosen: list[dict[str, Any]] = field(default_factory=list)

    async def decide(
        self,
        client: object,
        page: PageState,
        goal: str,
        history: list[RecentAction],
        visited: list[Visited],
        addresses: list[str],
    ) -> Decision:
        self.decided.append(
            {
                "client": client,
                "page": page,
                "goal": goal,
                "history": history,
                "visited": list(visited),
                "addresses": addresses,
            }
        )
        if self.on_decide is not None:
            self.on_decide()
        return self.decisions.pop(0)

    async def choose_value(
        self,
        client: object,
        page: PageState,
        goal: str,
        target: PageAction,
        history: list[RecentAction],
        secrets: list[str],
    ) -> tuple[str, JevEvaluation]:
        self.chosen.append(
            {
                "client": client,
                "page": page,
                "goal": goal,
                "target": target,
                "history": history,
                "secrets": secrets,
            }
        )
        if self.value_error is not None:
            raise self.value_error
        return self.value, JevEvaluation(answers={}, provider="openrouter")


class _TextModel:
    """The tiny model that writes a value the goal implies; keeps what it was asked."""

    def __init__(
        self,
        text: str | None = "Ada Lovelace",
        *,
        hangs: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self._text = text
        self._hangs = hangs
        self._raises = raises
        self.asked: list[tuple[list[Any], type[Any]]] = []

    async def ainvoke(self, messages: list[Any], output_format: type[Any]) -> SimpleNamespace:
        self.asked.append((messages, output_format))
        if self._hangs:
            await asyncio.Event().wait()
        if self._raises is not None:
            raise self._raises
        return SimpleNamespace(completion=output_format(text=self._text))


@dataclass
class _Run:
    runner: JevRunner
    jev: _Jev
    ledger: RunLedger

    async def burst(self, goal: str = "go next", start_url: str | None = None) -> BurstResult:
        return await self.runner.burst(goal, start_url)


def _flag(value: bool) -> Callable[[], Awaitable[bool]]:
    async def _read() -> bool:
        return value

    return _read


def _run(
    monkeypatch: pytest.MonkeyPatch,
    page: FakePage,
    *decisions: Decision,
    value: str = NONE_VALUE,
    stalls: _Stalls | None = None,
    secrets: RunSecrets | None = None,
    text_model: _TextModel | None = None,
    should_stop: Callable[[], Awaitable[bool]] = _flag(False),
    user_waiting: Callable[[], Awaitable[bool]] = _flag(False),
) -> _Run:
    jev = _Jev(list(decisions), value=value)
    monkeypatch.setattr(loop_mod, "decide", jev.decide)
    monkeypatch.setattr(loop_mod, "choose_value", jev.choose_value)
    ledger = RunLedger()
    runner = JevRunner(
        page=page,  # type: ignore[arg-type]  # the tab, scripted
        client=MagicMock(model="jev"),
        text_model=text_model or _TextModel(),  # type: ignore[arg-type]  # the one call the loop makes
        run=BurstContext(
            ledger=ledger,
            secrets=secrets or RunSecrets({}, []),
            stalls=stalls or _Stalls(),  # type: ignore[arg-type]  # the one method the loop reads
            should_stop=should_stop,
            user_waiting=user_waiting,
        ),
    )
    return _Run(runner, jev, ledger)


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance the loop's clock one second per reading, so every measured call takes 1000 ms."""
    ticks: Iterator[float] = itertools.count(0.0, 1.0)
    monkeypatch.setattr(loop_mod, "perf_counter", lambda: next(ticks))


def _pages(*urls: str) -> list[PageState]:
    return [page_state(url=f"https://site.test/{url}") for url in urls]


# --- why a burst stops -------------------------------------------------------------------


async def test_a_burst_ends_when_jev_judges_the_goal_done_and_reports_what_it_did(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), page_state(url="https://site.test/b", text="done page"))
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, "e1"), decision(JevOperation.DONE))

    result = await run.burst("go next")

    assert (result.goal, result.stop) == ("go next", JevStop.DONE)
    assert result.steps == [
        JevStep(
            operation=JevOperation.CLICK,
            label="Next",
            ident="",
            href="",
            text=None,
            url="https://site.test/a",
            page_changed=True,
            decision_ms=5,
        )
    ]
    assert result.progressed is True
    assert (result.url, result.title, result.text) == ("https://site.test/b", "Site", "done page")
    assert page.acted == ["e1"]
    assert [v.url for v in run.runner.visited] == ["https://site.test/a", "https://site.test/b"]


async def test_a_burst_ends_when_jev_finds_nothing_that_makes_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()), decision(JevOperation.BLOCKED))

    result = await run.burst()

    assert (result.stop, result.steps) == (JevStop.BLOCKED, [])


async def test_a_judgement_on_a_page_that_moved_on_is_made_again_on_the_new_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = _pages("a", "b")
    page = FakePage(before)
    run = _run(monkeypatch, page, decision(JevOperation.DONE), decision(JevOperation.DONE))

    def _moves() -> None:
        page.current = after

    run.jev.on_decide = _moves

    result = await run.burst()

    assert (result.stop, result.url) == (JevStop.DONE, after.url)
    assert run.jev.decided[1]["page"].url == after.url


async def test_a_run_asked_to_stop_ends_the_burst_before_jev_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()), should_stop=_flag(True))

    result = await run.burst()

    assert result.stop is JevStop.STOPPED
    assert run.jev.decided == []


async def test_a_user_message_hands_the_run_back_before_another_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()), user_waiting=_flag(True))

    result = await run.burst()

    assert result.stop is JevStop.USER_MESSAGE
    assert run.jev.decided == []


async def test_a_visible_captcha_frame_hands_the_run_back_naming_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captcha = "https://www.google.com/recaptcha/api2/anchor?k=" + "x" * 200
    frames = [
        {"src": captcha, "same_origin": False, "visible": True},
        {"src": "https://ads.test/frame", "same_origin": False, "visible": True},
        {"src": "https://site.test/inner", "same_origin": True, "visible": True},
        {"src": "https://hidden.test/frame", "same_origin": False, "visible": False},
        {"src": "", "same_origin": False, "visible": True},
    ]
    run = _run(monkeypatch, FakePage(page_state(frames=frames)))

    result = await run.burst()

    assert result.stop is JevStop.CAPTCHA
    assert captcha[: loop_mod._CAPTCHA_SRC_CHARS] in result.detail
    assert captcha not in result.detail
    # What Jev cannot see into: visible, cross-origin frames with an address.
    assert result.hidden_frames == [captcha, "https://ads.test/frame"]


async def test_a_captcha_frame_that_is_not_shown_does_not_stop_jev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = [
        {
            "src": "https://www.google.com/recaptcha/api2/anchor",
            "same_origin": False,
            "visible": False,
        },
        {"src": "https://ads.test/frame", "same_origin": False, "visible": True},
    ]
    run = _run(monkeypatch, FakePage(page_state(frames=frames)), decision(JevOperation.DONE))

    result = await run.burst()

    assert result.stop is JevStop.DONE


async def test_a_burst_stops_at_its_action_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_mod, "JEV_BURST_MAX_ACTIONS", 2)
    page = FakePage(*_pages("a", "b", "c"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * 2)

    result = await run.burst()

    assert result.stop is JevStop.MAX_ACTIONS
    assert len(result.steps) == 2


async def test_actions_that_change_nothing_end_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(*[page_state()] * (JEV_UNCHANGED_LIMIT + 1))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * JEV_UNCHANGED_LIMIT)

    result = await run.burst()

    assert result.stop is JevStop.NO_PROGRESS
    assert len(result.steps) == JEV_UNCHANGED_LIMIT
    assert result.progressed is False


async def test_going_back_and_forth_between_two_moves_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, a, b = _pages("start", "a", "b")
    page = FakePage(start, a, b, a, b, a)
    back_and_forth = [decision(JevOperation.CLICK, "e1"), decision(JevOperation.GO_BACK)] * 2
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, "e1"), *back_and_forth)

    result = await run.burst()

    assert result.stop is JevStop.CYCLE
    assert len(result.steps) == 5


async def test_a_page_that_keeps_changing_under_each_decision_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), act_raises=StalePage("moved"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * JEV_STALE_LIMIT)

    result = await run.burst()

    assert (result.stop, result.steps) == (JevStop.STALE, [])


async def test_a_decision_the_page_outran_is_made_again_until_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[Exception | None] = [StalePage("moved")] * (JEV_STALE_LIMIT - 1) + [None]
    page = FakePage(*_pages("a", "b"), act_raises=outcomes)
    clicks = [decision(JevOperation.CLICK, "e1")] * JEV_STALE_LIMIT
    run = _run(monkeypatch, page, *clicks, decision(JevOperation.DONE))

    result = await run.burst()

    assert result.stop is JevStop.DONE
    assert page.acted == ["e1"]


async def test_a_covered_control_twice_ends_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(page_state(), act_raises=Covered("covered"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, "e1")] * 2)

    result = await run.burst()

    assert (result.stop, result.steps) == (JevStop.COVERED, [])


@pytest.mark.parametrize(
    "outcomes",
    [
        pytest.param([Covered("covered"), None], id="covered-once"),
        pytest.param([Covered("covered"), None, Covered("covered"), None], id="covered-apart"),
    ],
)
async def test_a_control_covered_once_at_a_time_is_decided_again(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[Exception | None]
) -> None:
    page = FakePage(*_pages("a", "b", "c"), act_raises=list(outcomes))
    clicks = [decision(JevOperation.CLICK, "e1")] * len(outcomes)
    run = _run(monkeypatch, page, *clicks, decision(JevOperation.DONE))

    result = await run.burst()

    assert result.stop is JevStop.DONE
    assert len(result.steps) == outcomes.count(None)


async def test_a_dropdown_change_that_may_have_fired_ends_the_burst_saying_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uncertain = UncertainSelect("The dropdown change was interrupted.")
    run = _run(
        monkeypatch,
        FakePage(page_state(), act_raises=uncertain),
        decision(JevOperation.CLICK, "e1"),
    )

    result = await run.burst()

    assert (result.stop, result.detail) == (JevStop.STALE, str(uncertain))


async def test_a_page_the_browser_stopped_loading_ends_the_burst_with_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = [
        "https://slow.test/ did not respond",
        f"https://site.test/?pw={SECRET} did not respond",
    ]
    page = FakePage(page_state(), page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e1"),
        stalls=_Stalls(notes),
        secrets=_secrets(),
    )

    result = await run.burst()

    assert result.stop is JevStop.LOAD_STALLED
    assert result.detail == (
        f"https://slow.test/ did not respond https://site.test/?pw={MASKED} did not respond"
    )
    assert [step.label for step in result.steps] == ["Next"]


async def test_an_address_that_cannot_be_opened_ends_the_burst_on_the_page_it_was_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())

    async def _fails(url: str) -> None:
        raise NavigationFailed("net::ERR_NAME_NOT_RESOLVED")

    page.navigate = _fails  # type: ignore[method-assign]  # this one tab's navigation fails
    gone = f"https://gone.test/?pw={SECRET}"
    run = _run(
        monkeypatch, page, decision(JevOperation.NAVIGATE, url=gone), secrets=_secrets("gone.test")
    )

    result = await run.burst("open gone.test")

    assert result.stop is JevStop.NAVIGATION_FAILED
    assert f"https://gone.test/?pw={MASKED}" in result.detail
    assert "ERR_NAME_NOT_RESOLVED" in result.detail
    assert SECRET not in result.detail
    assert result.url == "https://site.test/a"


async def test_a_navigation_the_browser_stopped_ends_the_burst_as_a_stalled_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())

    async def _fails(url: str) -> None:
        raise NavigationFailed("net::ERR_ABORTED")

    page.navigate = _fails  # type: ignore[method-assign]  # the browser stopped this load
    note = "https://slow.test/ did not respond within 15 s"
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.NAVIGATE, url="https://slow.test/"),
        stalls=_Stalls([note]),
    )

    result = await run.burst()

    assert (result.stop, result.detail) == (JevStop.LOAD_STALLED, note)


async def test_a_burst_given_a_start_address_opens_it_before_jev_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, start = _pages("home", "start")
    page = FakePage(home, start)
    run = _run(monkeypatch, page, decision(JevOperation.DONE))

    result = await run.burst(start_url="https://site.test/start")

    assert page.navigated == ["https://site.test/start"]
    assert run.jev.decided[0]["page"].url == start.url
    assert result.url == start.url


async def test_a_start_address_that_cannot_be_opened_ends_the_burst_undecided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())

    async def _fails(url: str) -> None:
        raise NavigationFailed("net::ERR_CONNECTION_REFUSED")

    page.navigate = _fails  # type: ignore[method-assign]  # the start page never opens
    run = _run(monkeypatch, page)

    result = await run.burst(start_url="https://down.test/")

    assert result.stop is JevStop.NAVIGATION_FAILED
    assert "https://down.test/" in result.detail
    assert run.jev.decided == []


async def test_a_field_the_goal_gives_no_value_for_asks_the_agent_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(monkeypatch, page, decision(JevOperation.TYPE_TEXT, "e2"))

    result = await run.burst("fill the form")

    assert result.stop is JevStop.NEEDS_INPUT
    assert FIELD["label"] in result.detail
    assert page.typed == []


async def test_a_tab_that_stops_answering_ends_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    unresponsive = PageUnresponsive("Runtime.evaluate got no answer in 20s")
    run = _run(
        monkeypatch,
        FakePage(page_state(), act_raises=unresponsive),
        decision(JevOperation.CLICK, "e1"),
    )

    result = await run.burst()

    assert (result.stop, result.detail) == (JevStop.UNRESPONSIVE, str(unresponsive))


async def test_a_step_jev_could_not_decide_ends_the_burst_saying_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()))

    async def _fails(*args: Any, **kwargs: Any) -> Decision:
        raise JevGatewayError("503 from the gateway")

    monkeypatch.setattr(loop_mod, "decide", _fails)

    result = await run.burst()

    assert result.stop is JevStop.GATEWAY
    assert "503 from the gateway" in result.detail


async def test_a_gateway_failure_choosing_a_value_ends_the_burst_with_its_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(*_pages("a", "b"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.TYPE_TEXT, "e2"),
    )
    run.jev.value_error = JevGatewayError("503 from the gateway")

    result = await run.burst("fill the form")

    assert result.stop is JevStop.GATEWAY
    assert "503 from the gateway" in result.detail
    assert [step.label for step in result.steps] == ["Next"]


@pytest.mark.parametrize(
    ("text_model", "failure"),
    [
        pytest.param(_TextModel(hangs=True), "TimeoutError", id="never-answers"),
        pytest.param(
            _TextModel(raises=ModelProviderError("upstream 502")), "ModelProviderError", id="fails"
        ),
    ],
)
async def test_a_text_model_that_fails_ends_the_burst_with_its_steps(
    monkeypatch: pytest.MonkeyPatch, text_model: _TextModel, failure: str
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_TEXT_TIMEOUT_SECONDS", 0.01)
    page = FakePage(*_pages("a", "b"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.TYPE_TEXT, "e2"),
        value=GENERATE,
        text_model=text_model,
    )

    result = await run.burst("fill the form")

    assert result.stop is JevStop.GATEWAY
    assert failure in result.detail
    assert [step.label for step in result.steps] == ["Next"]


async def test_a_page_that_never_settles_on_a_reread_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Covered, then read again while the page is still being replaced.
    page = FakePage(page_state(), act_raises=Covered("covered"))
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, "e1"))
    reads = iter([page.current])

    async def _observe() -> PageState:
        read = next(reads, None)
        if read is None:
            raise StalePage("The page did not settle.")
        return read

    page.observe = _observe  # type: ignore[method-assign]  # only the burst's first read settles

    result = await run.burst()

    assert (result.stop, result.detail) == (JevStop.STALE, "The page did not settle.")


async def test_a_page_that_never_settles_after_an_action_ends_the_burst_with_the_action_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(
        monkeypatch, FakePage(page_state(), unsettled=True), decision(JevOperation.CLICK, "e1")
    )

    result = await run.burst()

    assert result.stop is JevStop.STALE
    assert [(step.label, step.page_changed) for step in result.steps] == [("Next", None)]


# --- what Jev is asked -------------------------------------------------------------------


async def test_jev_decides_on_the_masked_page_with_the_goal_its_recent_actions_and_where_it_has_been(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_RECENT_ACTIONS", 2)
    first = page_state(url=f"https://site.test/a?pw={SECRET}", text=f"hi {SECRET}")
    page = FakePage(first, *_pages("b", "c", "d"))
    clicks = [decision(JevOperation.CLICK, "e1")] * 3
    run = _run(monkeypatch, page, *clicks, decision(JevOperation.DONE), secrets=_secrets())

    await run.burst("open https://docs.test/ then log in")

    asked = run.jev.decided
    assert (asked[0]["page"].url, asked[0]["page"].text) == (
        f"https://site.test/a?pw={MASKED}",
        f"hi {MASKED}",
    )
    last = asked[3]
    assert last["goal"] == "open https://docs.test/ then log in"
    assert last["client"] is run.runner._client
    step = RecentAction(action="Next", kind="CLICK", text=None, page_changed=True)
    assert last["history"] == [step, step]
    visited = [
        f"https://site.test/a?pw={MASKED}",
        "https://site.test/b",
        "https://site.test/c",
        "https://site.test/d",
    ]
    assert [v.url for v in last["visited"]] == visited
    assert [v.title for v in last["visited"]] == ["Site"] * 4
    # The pages the goal names, then every page visited, each once.
    assert last["addresses"] == ["https://docs.test/", *visited]


async def test_a_page_that_changed_since_it_was_read_is_read_again_before_jev_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = _pages("a", "b")
    page = FakePage(before)

    async def _moves_meanwhile() -> bool:
        page.current = after
        return False

    run = _run(monkeypatch, page, decision(JevOperation.DONE), user_waiting=_moves_meanwhile)

    await run.burst()

    assert run.jev.decided[0]["page"].url == after.url


async def test_jev_picks_a_value_on_the_masked_page_for_the_field_from_the_goal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = page_state(url="https://site.test/form", text=f"hi {SECRET}")
    page = FakePage(page_state(), form, page_state(url="https://site.test/c"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.TYPE_TEXT, "e2"),
        decision(JevOperation.DONE),
        value="Ada",
        secrets=_secrets(),
    )

    result = await run.burst('type "Ada"')

    [chosen] = run.jev.chosen
    assert chosen["client"] is run.runner._client
    assert chosen["page"].text == f"hi {MASKED}"
    assert (chosen["goal"], chosen["target"], chosen["secrets"]) == (
        'type "Ada"',
        FIELD,
        ["password"],
    )
    assert chosen["history"] == [
        RecentAction(action="Next", kind="CLICK", text=None, page_changed=True)
    ]
    assert page.typed == [None, "Ada"]
    assert result.steps[1].text == "Ada"


async def test_a_value_the_goal_only_implies_is_written_by_the_text_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_PAGE_TEXT_MAX_CHARS", 12)
    form = page_state(url="https://site.test/form", text=f"{SECRET} and the rest of a long page")
    page = FakePage(page_state(), form, page_state(url="https://site.test/c"))
    text_model = _TextModel("Ada Lovelace")
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.TYPE_TEXT, "e2"),
        decision(JevOperation.DONE),
        value=GENERATE,
        text_model=text_model,
        secrets=_secrets(),
    )

    result = await run.burst("sign up as the first programmer")

    assert page.typed == [None, "Ada Lovelace"]
    assert result.steps[1].text == "Ada Lovelace"
    [(messages, output_format)] = text_model.asked
    assert output_format is loop_mod._TextValue
    assert messages[0].content == TEXT_VALUE
    assert json.loads(messages[1].content) == {
        "goal": "sign up as the first programmer",
        "field": describe_field(FIELD),
        "page": {"title": "Site", "text": f"{MASKED}"[:12]},
        "recent_actions": [{"action": "Next", "text": None}],
    }


@pytest.mark.parametrize("written", [None, "   "])
async def test_a_written_value_that_is_blank_asks_the_agent(
    monkeypatch: pytest.MonkeyPatch, written: str | None
) -> None:
    page = FakePage(page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, "e2"),
        value=GENERATE,
        text_model=_TextModel(written),
    )

    result = await run.burst("fill the form")

    assert result.stop is JevStop.NEEDS_INPUT
    assert page.typed == []


# --- secrets -----------------------------------------------------------------------------


async def test_a_secret_is_typed_into_the_page_and_never_into_what_the_agent_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landed = page_state(url=f"https://site.test/b?pw={SECRET}", text=f"welcome {SECRET}")
    page = FakePage(page_state(), landed)
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, "e3"),
        decision(JevOperation.DONE),
        value=MASKED,
        secrets=_secrets(),
    )

    result = await run.burst(f"log in with {MASKED}")

    assert page.typed == [SECRET]
    assert SECRET not in repr(result)
    assert result.steps[0].text == MASKED
    assert (result.url, result.text) == (f"https://site.test/b?pw={MASKED}", f"welcome {MASKED}")


async def test_a_secret_is_never_typed_on_a_site_the_task_does_not_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, "e3"),
        value=MASKED,
        secrets=_secrets("bank.test"),
    )

    result = await run.burst(f"log in with {MASKED}")

    assert result.stop is JevStop.NEEDS_INPUT
    assert page.typed == []


async def test_a_password_field_with_no_stored_secret_is_left_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Jev types into a password field only a secret the run was given; the agent
    # types anything else, and the run learns it as a secret there.
    page = FakePage(page_state())
    run = _run(monkeypatch, page, decision(JevOperation.TYPE_TEXT, "e3"), value=NONE_VALUE)

    result = await run.burst('log in with password "gaia-test-123"')

    assert result.stop is JevStop.NEEDS_INPUT
    assert page.typed == []


# --- what the burst reports --------------------------------------------------------------


async def test_each_step_names_its_target_where_a_link_points_and_the_page_it_was_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = PageAction(
        id="e4",
        node=4,
        kind="click",
        label="Docs",
        role="link",
        ident="docs-link",
        href=f"https://site.test/docs?pw={SECRET}",
    )
    first = replace(page_state(url=f"https://site.test/a?pw={SECRET}"), actions=[link, SCROLL])
    b, c = _pages("b", "c")
    page = FakePage(first, replace(b, actions=[SCROLL]), c)
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, "e4"),
        decision(JevOperation.SCROLL_DOWN, "scroll_down"),
        decision(JevOperation.DONE),
        secrets=_secrets(),
    )

    result = await run.burst()

    assert result.steps == [
        JevStep(
            operation=JevOperation.CLICK,
            label="Docs",
            ident="docs-link",
            href=f"https://site.test/docs?pw={MASKED}",
            text=None,
            url=f"https://site.test/a?pw={MASKED}",
            page_changed=True,
            decision_ms=5,
        ),
        JevStep(
            operation=JevOperation.SCROLL_DOWN,
            label="Scroll down",
            ident="",
            href="",
            text=None,
            url="https://site.test/b",
            page_changed=True,
            decision_ms=5,
        ),
    ]
    assert page.acted == ["e4", "scroll_down"]


async def test_page_level_steps_go_back_press_enter_and_open_an_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(*_pages("a", "b", "c", "d", "e"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.GO_BACK),
        decision(JevOperation.GO_BACK),
        decision(JevOperation.PRESS_ENTER),
        decision(JevOperation.NAVIGATE, url="https://docs.test/"),
        decision(JevOperation.DONE),
    )

    result = await run.burst()

    assert (page.went_back, page.entered, page.navigated) == (2, 1, ["https://docs.test/"])
    labels = [step.label for step in result.steps]
    assert labels[:3] == [
        loop_mod._PAGE_LEVEL_LABELS[JevOperation.GO_BACK],
        loop_mod._PAGE_LEVEL_LABELS[JevOperation.GO_BACK],
        loop_mod._PAGE_LEVEL_LABELS[JevOperation.PRESS_ENTER],
    ]
    assert "https://docs.test/" in labels[3]


async def test_pages_opened_along_the_way_are_read_once_masked_and_listed_in_the_order_last_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long = f"{SECRET} " + "article text " * 200
    start, b, c, d = _pages("start", "b", "c", "d")
    b = replace(b, text=long, fingerprint="b1")
    b_again = replace(b, text="b, read a second time", fingerprint="b2")
    page = FakePage(start, b, c, b_again, d)
    run = _run(
        monkeypatch,
        page,
        *[decision(JevOperation.CLICK, "e1")] * 4,
        decision(JevOperation.DONE),
        secrets=_secrets(),
    )

    result = await run.burst()

    read = long[: loop_mod.JEV_REPORT_OPENED_PAGE_CHARS].replace(SECRET, MASKED)
    # The page the burst ended on is its final page, not an opened one.
    assert result.opened == [
        OpenedPage(url=c.url, title="Site", text=c.text),
        OpenedPage(url=b.url, title="Site", text=read),
    ]
    assert result.url == d.url


async def test_a_click_that_opens_a_tab_continues_on_that_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, b, tab = _pages("start", "b", "tab")
    page = FakePage(start, b, new_tab=tab)
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, "e1"), decision(JevOperation.DONE))

    result = await run.burst()

    assert page.followed == [{"tab-1"}]
    assert (result.url, result.opened) == (tab.url, [])
    assert result.steps[0].page_changed is True


async def test_only_a_click_follows_a_tab_that_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    start, b, tab = _pages("start", "b", "tab")
    page = FakePage(start, b, new_tab=tab)
    run = _run(monkeypatch, page, decision(JevOperation.PRESS_ENTER), decision(JevOperation.DONE))

    result = await run.burst()

    assert page.followed == []
    assert result.url == b.url


async def test_the_pages_visited_are_kept_to_the_latest_few_across_bursts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_VISITED_PAGES", 3)
    page = FakePage(*_pages("a", "b", "a", "c", "d"))
    run = _run(
        monkeypatch,
        page,
        *[decision(JevOperation.CLICK, "e1")] * 3,
        decision(JevOperation.DONE),
        decision(JevOperation.CLICK, "e1"),
        decision(JevOperation.DONE),
    )

    await run.burst()
    # A revisited page moves to the end instead of appearing twice.
    assert [v.url for v in run.runner.visited] == [
        "https://site.test/b",
        "https://site.test/a",
        "https://site.test/c",
    ]
    await run.burst()

    assert [v.url for v in run.runner.visited] == [
        "https://site.test/a",
        "https://site.test/c",
        "https://site.test/d",
    ]


async def test_every_jev_call_and_action_lands_in_the_run_ledger_with_secrets_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pay = PageAction(id="e1", node=1, kind="click", label=f"Pay {SECRET}", role="button")
    evaluation = JevEvaluation(
        answers={},
        provider="vercel",
        usage=JevUsage(inputTokens=12, outputTokens=3, cost=0.002),
    )
    click = replace(decision(JevOperation.CLICK, "e1"), evaluation=evaluation)
    page = FakePage(replace(page_state(), actions=[pay, FIELD]), *_pages("b", "c"))
    run = _run(
        monkeypatch,
        page,
        click,
        decision(JevOperation.TYPE_TEXT, "e2"),
        decision(JevOperation.DONE),
        value="Ada",
        secrets=_secrets(),
    )

    await run.burst()

    assert run.ledger.calls == [
        ModelCall(CallComponent.JEV, "vercel", "jev", 1000, 12, 3, 0.002),
        ModelCall(CallComponent.JEV, "openrouter", "jev", 1000, 0, 0, None),
        ModelCall(CallComponent.JEV, "openrouter", "jev", 1000, 0, 0, None),
        ModelCall(CallComponent.JEV, "openrouter", "jev", 1000, 0, 0, None),
    ]
    assert run.ledger.actions == [
        ExecutedAction(CallComponent.JEV, f"CLICK Pay {JEV_SECRET_MASK}", 1000),
        # Choosing the value was part of typing it.
        ExecutedAction(CallComponent.JEV, "TYPE_TEXT Name", 3000),
    ]


def test_a_burst_that_never_changed_the_page_did_not_progress() -> None:
    step = JevStep(
        operation=JevOperation.CLICK,
        label="Next",
        ident="",
        href="",
        text=None,
        url="https://site.test/a",
        page_changed=False,
        decision_ms=5,
    )
    result = BurstResult(
        goal="g",
        stop=JevStop.NO_PROGRESS,
        detail="",
        steps=[step],
        url="",
        title="",
        text="",
        opened=[],
        hidden_frames=[],
    )

    assert result.progressed is False
    assert replace(result, steps=[replace(step, page_changed=True)]).progressed is True
