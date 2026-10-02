"""A Jev burst: why it stops, what it hands the agent, what Jev is asked, and that no secret leaves the page."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field, replace
import itertools
import json
from typing import Any
from unittest.mock import MagicMock

from browser_use.llm.exceptions import ModelError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.views import ChatInvokeCompletion
import pytest

from app.constants.browser import (
    JEV_BURST_MAX_ACTIONS,
    JEV_SECRET_DIFFERS,
    JEV_SECRET_MASK,
    JEV_SECRET_WRITTEN,
    JEV_STALE_LIMIT,
    JEV_UNCHANGED_LIMIT,
    JEV_VISITED_PAGES,
    JevOperation,
    JevStop,
)
from app.schemas.browser import BrowserTaskSecret
from app.services.browser.jev import loop as loop_mod
from app.services.browser.jev.decision import (
    GENERATE,
    NONE_VALUE,
    Decision,
    RecentAction,
    Situation,
    Visited,
    describe_field,
)
from app.services.browser.jev.gateway import (
    JevEvaluation,
    JevEvaluationRequest,
    JevGatewayError,
    JevUsage,
)
from app.services.browser.jev.loop import BurstContext, BurstResult, JevRunner, JevStep, OpenedPage
from app.services.browser.jev.page import (
    Covered,
    EngineScriptError,
    FieldUnfocused,
    NavigationFailed,
    PageAction,
    PageLoading,
    PageScriptError,
    PageState,
    PageUnresponsive,
    StalePage,
    TabUnavailable,
)
from app.services.browser.jev.secrets import RunSecrets
from app.services.browser.ledger import CallComponent, ExecutedAction, ModelCall, RunLedger
from tests.unit.services.browser.jev.conftest import (
    BACK,
    BUTTON,
    ENTER,
    FIELD,
    PASSWORD,
    FakePage,
    decision,
    page_state,
)

pytestmark = pytest.mark.unit

SECRET = "hunter2-secret"
MASKED = "<secret>password</secret>"
SCROLL = PageAction(id="scroll_down", kind="scroll", label="Scroll down", delta=560)


def _secrets(site: str = "site.test") -> RunSecrets:
    return RunSecrets({"password": BrowserTaskSecret(value=SECRET, site=site)})


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
    #: The value chosen for every field, or one per field in turn.
    value: str | list[str] = NONE_VALUE
    #: The option a chosen dropdown is set to, by its value, and what each option question saw.
    option: str = ""
    optioned: list[tuple[object, str, str, list[RecentAction], str]] = field(default_factory=list)
    value_error: Exception | None = None
    #: Runs as Jev answers each decision, for a page that moves while Jev decides.
    on_decide: Callable[[], None] | None = None
    decided: list[dict[str, Any]] = field(default_factory=list)
    chosen: list[dict[str, Any]] = field(default_factory=list)

    async def decide(
        self, client: object, situation: Situation, visited: list[Visited], addresses: list[str]
    ) -> Decision:
        self.decided.append(
            {
                "client": client,
                "page": situation.page,
                "goal": situation.goal,
                "history": situation.history,
                "visited": list(visited),
                "addresses": addresses,
            }
        )
        if self.on_decide is not None:
            self.on_decide()
        return self.decisions.pop(0)

    async def choose_value(
        self, client: object, situation: Situation, target: PageAction, secrets: list[str]
    ) -> tuple[str, JevEvaluation]:
        self.chosen.append(
            {
                "client": client,
                "page": situation.page,
                "goal": situation.goal,
                "target": target,
                "history": situation.history,
                "secrets": secrets,
            }
        )
        if self.value_error is not None:
            raise self.value_error
        value = self.value.pop(0) if isinstance(self.value, list) else self.value
        return value, JevEvaluation(answers={}, provider="openrouter")

    async def choose_option(
        self, client: object, situation: Situation, dropdown: PageAction
    ) -> tuple[PageAction, JevEvaluation]:
        self.optioned.append(
            (client, situation.page.url, situation.goal, situation.history, situation.mask(SECRET))
        )
        [option] = [o for o in dropdown["options"] if o["value"] == self.option]
        chosen = dropdown.copy()
        del chosen["options"]
        chosen["value"], chosen["current_value"] = option["value"], option["label"]
        return chosen, JevEvaluation(answers={}, provider="openrouter")


class _TextModel:
    """The tiny model that writes a value the goal implies; keeps what it was asked."""

    def __init__(
        self,
        text: str | None | list[str | None] = "Ada Lovelace",
        *,
        hangs: bool = False,
        raises: Exception | None = None,
    ) -> None:
        self._text = text
        self._hangs = hangs
        self._raises = raises
        self.asked: list[tuple[list[BaseMessage], type[loop_mod._TextValue]]] = []

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[loop_mod._TextValue]
    ) -> ChatInvokeCompletion[loop_mod._TextValue]:
        self.asked.append((messages, output_format))
        if self._hangs:
            await asyncio.Event().wait()
        if self._raises is not None:
            raise self._raises
        text = self._text.pop(0) if isinstance(self._text, list) else self._text
        return ChatInvokeCompletion(completion=output_format(text=text), usage=None)


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


@dataclass
class _Around:
    """What the run around a burst tells it: the loads the browser stopped, and its two signals."""

    stalls: _Stalls = field(default_factory=_Stalls)
    should_stop: Callable[[], Awaitable[bool]] = field(default=_flag(False))
    user_waiting: Callable[[], Awaitable[bool]] = field(default=_flag(False))


def _run(
    monkeypatch: pytest.MonkeyPatch,
    page: FakePage,
    *decisions: Decision,
    value: str | list[str] = NONE_VALUE,
    secrets: RunSecrets | None = None,
    text_model: _TextModel | None = None,
    around: _Around | None = None,
) -> _Run:
    jev = _Jev(list(decisions), value=value)
    monkeypatch.setattr(loop_mod, "decide", jev.decide)
    monkeypatch.setattr(loop_mod, "choose_value", jev.choose_value)
    monkeypatch.setattr(loop_mod, "choose_option", jev.choose_option)
    ledger = RunLedger()
    around = around or _Around()
    runner = JevRunner(
        page=page,
        client=MagicMock(model="jev"),
        text_model=text_model or _TextModel(),
        run=BurstContext(
            ledger=ledger,
            secrets=secrets or RunSecrets({}),
            stalls=around.stalls,
            should_stop=around.should_stop,
            user_waiting=around.user_waiting,
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


@pytest.mark.parametrize(
    ("judged", "stop"),
    [(JevOperation.DONE, JevStop.DONE), (JevOperation.BLOCKED, JevStop.BLOCKED)],
)
async def test_a_burst_ends_when_jev_judges_the_goal_done_and_reports_what_it_did(
    monkeypatch: pytest.MonkeyPatch, judged: JevOperation, stop: JevStop
) -> None:
    final = replace(page_state(url="https://site.test/b", text="done page"), omitted_actions=4)
    page = FakePage(page_state(), final)
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), decision(judged))

    result = await run.burst("go next")

    assert (result.goal, result.stop, result.omitted_controls) == ("go next", stop, 4)
    assert [d["goal"] for d in run.jev.decided] == ["go next", "go next"]
    assert result.steps == [
        JevStep(
            operation=JevOperation.CLICK,
            label="Next",
            ident="",
            href="",
            text=None,
            url="https://site.test/a",
            page_changed=True,
            landed="https://site.test/b",
        )
    ]
    assert (result.url, result.title, result.text) == ("https://site.test/b", "Site", "done page")
    assert page.acted == ["e1"]
    assert [v.url for v in run.runner.visited] == ["https://site.test/a", "https://site.test/b"]


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


async def test_a_burst_asks_jev_a_bounded_number_of_times_even_when_nothing_it_decides_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(monkeypatch, page, *[decision(JevOperation.DONE)] * (4 * JEV_BURST_MAX_ACTIONS))
    moves = itertools.count()

    def _moves() -> None:
        # Every judgement lands on a page that moved on while Jev decided.
        page.current = page_state(url=f"https://site.test/{next(moves)}")

    run.jev.on_decide = _moves

    result = await run.burst()

    assert result.stop is JevStop.MAX_DECISIONS
    assert len(run.jev.decided) == 2 * JEV_BURST_MAX_ACTIONS


async def test_a_run_asked_to_stop_ends_the_burst_before_jev_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()), around=_Around(should_stop=_flag(True)))

    result = await run.burst()

    assert result.stop is JevStop.STOPPED
    assert run.jev.decided == []


async def test_a_user_message_hands_the_run_back_before_another_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(monkeypatch, FakePage(page_state()), around=_Around(user_waiting=_flag(True)))

    result = await run.burst()

    assert result.stop is JevStop.USER_MESSAGE
    assert run.jev.decided == []


async def test_a_burst_stops_at_its_action_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loop_mod, "JEV_BURST_MAX_ACTIONS", 2)
    page = FakePage(*_pages("a", "b", "c"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, BUTTON)] * 2)

    result = await run.burst()

    assert result.stop is JevStop.MAX_ACTIONS
    assert len(result.steps) == 2


async def test_actions_that_change_nothing_end_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(*[page_state()] * (JEV_UNCHANGED_LIMIT + 1))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, BUTTON)] * JEV_UNCHANGED_LIMIT)

    result = await run.burst()

    assert result.stop is JevStop.NO_PROGRESS
    assert len(result.steps) == JEV_UNCHANGED_LIMIT


async def test_going_back_and_forth_between_two_moves_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, a, b = _pages("start", "a", "b")
    page = FakePage(start, a, b, a, b, a)
    back_and_forth = [
        decision(JevOperation.CLICK, BUTTON),
        decision(JevOperation.GO_BACK, BACK),
    ] * 2
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), *back_and_forth)

    result = await run.burst()

    assert result.stop is JevStop.CYCLE
    assert len(result.steps) == 4


async def test_repeating_one_move_on_a_page_that_changes_each_time_is_progress_not_a_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add = PageAction(id="e9", node=9, kind="click", label="Add to cart", role="button", value="")
    carts = [replace(page_state(url="https://shop.test/"), text=f"{n} in cart") for n in range(5)]
    carts = [replace(cart, fingerprint=cart.text) for cart in carts]
    page = FakePage(*carts)
    moves = [decision(JevOperation.CLICK, add), decision(JevOperation.CLICK, BUTTON)] * 2
    run = _run(monkeypatch, page, *moves, decision(JevOperation.DONE))

    result = await run.burst()

    assert (result.stop, len(result.steps)) == (JevStop.DONE, 4)


async def test_a_page_that_keeps_changing_under_each_decision_ends_the_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), act_raises=StalePage("moved"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, BUTTON)] * JEV_STALE_LIMIT)

    result = await run.burst()

    assert (result.stop, result.steps) == (JevStop.STALE, [])


async def test_a_covered_control_twice_ends_the_burst(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(page_state(), act_raises=Covered("covered"))
    run = _run(monkeypatch, page, *[decision(JevOperation.CLICK, BUTTON)] * 2)

    result = await run.burst()

    assert (result.stop, result.steps, len(run.jev.decided)) == (JevStop.COVERED, [], 2)


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
        decision(JevOperation.CLICK, BUTTON),
        around=_Around(stalls=_Stalls(notes)),
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
    page = FakePage(page_state(), navigate_fails=NavigationFailed("net::ERR_NAME_NOT_RESOLVED"))
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


async def test_a_field_the_goal_gives_no_value_for_asks_the_agent_naming_the_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(monkeypatch, page, decision(JevOperation.TYPE_TEXT, FIELD))

    result = await run.burst("fill the form")

    assert result.stop is JevStop.NEEDS_INPUT
    assert FIELD["label"] in result.detail
    assert page.typed == []


@pytest.mark.parametrize(
    ("error", "stop"),
    [
        (TabUnavailable("No valid agent focus available"), JevStop.TAB_UNAVAILABLE),
        (PageUnresponsive("Runtime.evaluate got no answer in 20s"), JevStop.UNRESPONSIVE),
        (PageLoading("The page is still loading: https://site.test/b"), JevStop.LOADING),
        (PageScriptError("Jev's page script failed: Error: x"), JevStop.PAGE_SCRIPT_ERROR),
        (EngineScriptError("Jev's page script failed: TypeError"), JevStop.ENGINE_SCRIPT_ERROR),
    ],
)
async def test_a_tab_that_goes_away_mid_burst_ends_it_with_every_step_it_took(
    monkeypatch: pytest.MonkeyPatch, error: Exception, stop: JevStop
) -> None:
    # The burst's first read and the read before deciding; the tab goes under the read after the click.
    page = FakePage(*_pages("a", "b"), read_fails=(2, error))
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), decision(JevOperation.DONE))

    result = await run.burst()

    assert (result.stop, result.detail) == (stop, str(error))
    assert [step.label for step in result.steps] == ["Next"]


async def test_a_blank_tab_is_never_an_address_and_with_none_to_open_the_burst_ends_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: from about:blank with no start_url, Jev reopened about:blank to its action budget."""
    wait = PageAction(id="wait", kind="wait", label="Wait for the page to update")
    blank = replace(page_state(url="about:blank"), actions=[wait])
    page = FakePage(blank, *_pages("a", "b"))
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), decision(JevOperation.DONE))

    stranded = await run.burst("open the docs")
    await run.burst("open the docs", "https://site.test/a")

    assert (stranded.stop, stranded.steps) == (JevStop.NO_PAGE, [])
    # The page Jev is on is no address to open either.
    assert [d["addresses"] for d in run.jev.decided] == [[], ["https://site.test/a"]]


@pytest.mark.parametrize(
    "tab",
    [
        # A window its opener wrote a form into.
        page_state(url="about:blank"),
        replace(page_state(), actions=[]),
    ],
    ids=["blank-with-a-control", "web-page-with-none"],
)
async def test_a_tab_with_a_control_or_on_the_web_is_decided_on_though_nothing_is_to_open(
    monkeypatch: pytest.MonkeyPatch, tab: PageState
) -> None:
    run = _run(monkeypatch, FakePage(tab), decision(JevOperation.DONE))

    result = await run.burst()

    assert (result.stop, run.jev.decided[0]["addresses"]) == (JevStop.DONE, [])


async def test_a_start_address_on_a_tab_that_is_gone_ends_the_burst_with_no_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state(), navigate_fails=TabUnavailable("Target tab-1 has detached"))
    run = _run(monkeypatch, page)

    result = await run.burst("go", "https://site.test/a")

    assert (result.stop, result.url, result.title, result.text) == (
        JevStop.TAB_UNAVAILABLE,
        "",
        "",
        "",
    )
    assert (result.steps, result.hidden_frames, result.omitted_controls) == ([], [], 0)


async def test_a_field_that_did_not_take_focus_ends_the_burst_with_the_click_it_took(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unfocused = FieldUnfocused("The field did not take focus when clicked; nothing was typed.")
    page = FakePage(page_state(), act_raises=unfocused)
    run = _run(monkeypatch, page, decision(JevOperation.TYPE_TEXT, FIELD), value="Ada")

    result = await run.burst('type "Ada"')

    assert (result.stop, [s.label for s in result.steps]) == (JevStop.FIELD_UNFOCUSED, ["Name"])
    assert result.detail == str(unfocused)


async def test_a_burst_sets_a_dropdown_and_types_what_each_field_takes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    size = PageAction(
        id="e7",
        node=7,
        kind="select",
        label="Size",
        role="combobox",
        value="m",
        current_value="Medium",
        options=[{"value": "l", "label": f"Large {SECRET}"}],
    )
    pages = [replace(p, actions=[size, FIELD]) for p in _pages("a", "b", "c", "d")]
    # The second input meets a page that moved; the phone field keeps four digits.
    page = FakePage(
        *pages, act_raises=[None, StalePage("moved"), None, None], holds={"5551234": "5551"}
    )
    text_model = _TextModel(["Ada Lovelace", "   "])
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.SELECT, size),
        *[decision(JevOperation.TYPE_TEXT, FIELD)] * 4,
        value=[GENERATE, GENERATE, "5551234", GENERATE],
        text_model=text_model,
        secrets=_secrets(),
    )
    run.jev.option = "l"

    result = await run.burst("sign up as the first programmer")

    assert [(s.label, s.option, s.text, s.held) for s in result.steps] == [
        ("Size", f"Large {MASKED}", None, None),
        # Written once: the value the moved page kept from typing is typed without asking again.
        ("Name", None, "Ada Lovelace", None),
        ("Name", None, "5551234", '"5551"'),
    ]
    assert page.typed == [None, "Ada Lovelace", "5551234"]
    # A blank written value is no value.
    assert result.stop is JevStop.NEEDS_INPUT
    assert len(text_model.asked) == 2
    asked = json.loads(str(text_model.asked[0][0][1].content))
    assert run.jev.optioned == [
        (run.runner._client, "https://site.test/a", "sign up as the first programmer", [], MASKED)
    ]
    assert {call.latency_ms for call in run.ledger.calls} == {1000}
    assert asked == {
        "goal": "sign up as the first programmer",
        "field": describe_field(FIELD),
        "page": {"title": "Site", "text": "page"},
        "recent_actions": [{"action": f"Size: Large {MASKED}", "text": None}],
    }


async def test_a_page_the_burst_outran_resets_only_when_an_input_lands_and_the_start_page_stays_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moved = StalePage("moved")
    outran = [moved] * (JEV_STALE_LIMIT - 1)
    page = FakePage(*_pages("start", "b", "c", "d"), act_raises=[*outran, None, *outran, None])
    clicks = [decision(JevOperation.CLICK, BUTTON)] * (2 * JEV_STALE_LIMIT)
    run = _run(monkeypatch, page, *clicks, decision(JevOperation.DONE), decision(JevOperation.DONE))

    first = await run.burst(start_url="https://site.test/start")
    await run.burst(start_url="https://site.test/start")

    assert (first.stop, len(first.steps)) == (JevStop.DONE, 2)
    assert run.jev.decided[-1]["addresses"][0] == "https://site.test/start"
    assert run.jev.decided[-1]["addresses"].count("https://site.test/start") == 1


async def test_a_page_is_one_address_however_it_was_written_and_never_the_page_jev_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A start written without its slash sat beside the same page visited: Jev opened the page it was on six times."""
    front = replace(page_state(url="https://news.test/"), actions=[BUTTON])
    page = FakePage(page_state(), front, page_state(url="https://news.test/item"))
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), decision(JevOperation.DONE))

    await run.burst(start_url="https://news.test")

    assert [d["addresses"] for d in run.jev.decided] == [[], ["https://news.test"]]


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
    # An operation that came without its target is no step either.
    targetless = _run(monkeypatch, FakePage(page_state()), decision(JevOperation.CLICK))
    assert loop_mod._NO_TARGET in (await targetless.burst()).detail


async def test_a_gateway_failure_choosing_a_value_ends_the_burst_with_its_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(*_pages("a", "b"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.CLICK, BUTTON),
        decision(JevOperation.TYPE_TEXT, FIELD),
    )
    run.jev.value_error = JevGatewayError("503 from the gateway")

    result = await run.burst("fill the form")

    assert result.stop is JevStop.GATEWAY
    assert "503 from the gateway" in result.detail
    assert [step.label for step in result.steps] == ["Next"]


@pytest.mark.parametrize(
    ("text_model", "failure"),
    [
        (_TextModel(hangs=True), "TimeoutError"),
        (_TextModel(raises=ModelError("busy")), "ModelError"),
    ],
)
async def test_a_value_the_text_model_never_writes_ends_the_burst_with_nothing_typed(
    monkeypatch: pytest.MonkeyPatch, text_model: _TextModel, failure: str
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_TEXT_TIMEOUT_SECONDS", 0.01)
    page = FakePage(page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, FIELD),
        value=GENERATE,
        text_model=text_model,
    )

    result = await run.burst("sign up")

    assert (result.stop, result.detail) == (
        JevStop.GATEWAY,
        f"Jev could not decide this step: The value could not be written ({failure}).",
    )
    assert page.typed == []


async def test_jev_is_shown_the_pages_it_visited_last(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = _pages(*(str(n) for n in range(JEV_VISITED_PAGES + 2)))
    clicks = [decision(JevOperation.CLICK, BUTTON)] * (len(pages) - 1)
    run = _run(monkeypatch, FakePage(*pages), *clicks, decision(JevOperation.DONE))

    await run.burst()

    assert run.runner.visited == [Visited("Site", p.url) for p in pages[-JEV_VISITED_PAGES:]]


async def test_a_page_that_never_settles_after_an_action_ends_the_burst_with_the_action_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(
        monkeypatch, FakePage(page_state(), unsettled=True), decision(JevOperation.CLICK, BUTTON)
    )

    result = await run.burst()

    assert (result.stop, result.detail) == (JevStop.STALE, "The page did not settle.")
    assert [(step.label, step.page_changed) for step in result.steps] == [("Next", None)]


# --- what Jev is asked -------------------------------------------------------------------


class _RecordingJev:
    """The real decisions protocol, answered by script: each question's choice, and every request kept."""

    model = "jev"

    def __init__(self, operations: list[str], **choices: Callable[[list[str]], str]) -> None:
        self._operations = operations
        self._choices = choices
        self.sent: list[str] = []

    async def evaluate(self, request: JevEvaluationRequest) -> JevEvaluation:
        self.sent.append(request.model_dump_json())
        answers = {}
        for name, question in request.questions.items():
            ids = list(question.criteria)
            if name == "operation":
                choice = self._operations.pop(0)
            elif name in self._choices:
                choice = self._choices[name](ids)
            else:
                continue
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "probabilities": {i: float(i == choice) for i in ids},
            }
        return JevEvaluation.model_validate({"answers": answers, "provider": "openrouter"})


async def test_no_secret_reaches_jev_or_the_text_model_and_a_masked_address_still_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The value sits in every field a page can carry it in, and cut short where the text ends.
    link = PageAction(
        id="e4",
        node=4,
        kind="click",
        label=f"Signed in as {SECRET}",
        role="link",
        ident=SECRET,
        href=f"https://site.test/me?u={SECRET}",
        value=SECRET,
    )
    named = PageAction(
        id="e5", node=5, kind="fill", label=f"Name for {SECRET}", role="textbox", value=SECRET
    )
    choice = PageAction(
        id="e6",
        node=6,
        kind="select",
        label="Account",
        role="combobox",
        value="a",
        current_value=SECRET,
        options=[{"value": SECRET, "label": f"Use {SECRET}"}],
    )
    home = f"https://site.test/a?pw={SECRET}"
    first = replace(
        page_state(url=home, text=f"hi {SECRET} and {SECRET[:7]}", text_cut=True),
        title=f"Account of {SECRET}",
        actions=[link, named, choice],
    )
    # It ends on a page whose text was cut inside the value, beside a frame named with it.
    final = page_state(url=home, text=f"bye {SECRET[:9]}", text_cut=True)
    final = replace(
        final,
        frames=[
            {"src": f"https://pay.test/?u={SECRET}", "same_origin": False, "visible": True},
            # Jev reads a same-origin frame, and an unseen or unnamed one is nothing to report.
            {"src": "https://site.test/inner", "same_origin": True, "visible": True},
            {"src": "https://ads.test/", "same_origin": False, "visible": False},
            {"src": "", "same_origin": False, "visible": True},
        ],
    )
    page = FakePage(first, page_state(url="https://site.test/b"), final)
    jev = _RecordingJev(
        ["TYPE_TEXT", "NAVIGATE", "DONE"],
        type_text_target=lambda ids: ids[0],
        value=lambda ids: GENERATE,
        navigate_target=lambda ids: ids[0],
    )
    text_model = _TextModel("Ada")
    runner = JevRunner(
        page=page,
        client=jev,
        text_model=text_model,
        run=BurstContext(
            ledger=RunLedger(),
            secrets=_secrets(),
            stalls=_Stalls(),
            should_stop=_flag(False),
            user_waiting=_flag(False),
        ),
    )

    result = await runner.burst(f"rename {SECRET} to Ada", None)
    assert (result.text, result.hidden_frames) == ("bye ", [f"https://pay.test/?u={MASKED}"])

    sent = [*jev.sent, *(message.content for message in text_model.asked[0][0])]
    assert len(jev.sent) == 4
    assert not [request for request in sent if SECRET[:7] in request]
    assert SECRET[:7] not in repr(result)
    # Shown masked, opened as it is.
    assert page.navigated == [home]


async def test_a_page_that_changed_since_it_was_read_is_read_again_before_jev_decides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before, after = _pages("a", "b")
    page = FakePage(before)

    async def _moves_meanwhile() -> bool:
        page.current = after
        return False

    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.DONE),
        around=_Around(user_waiting=_moves_meanwhile),
    )

    await run.burst()

    assert run.jev.decided[0]["page"].url == after.url


async def test_jev_sees_what_it_typed_with_a_secret_left_as_its_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(*_pages("a", "b", "c"))
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, PASSWORD),
        decision(JevOperation.DONE),
        value=MASKED,
        secrets=_secrets(),
    )

    await run.burst(f"log in with {MASKED}")

    typed_secret = RecentAction(
        action="Password",
        kind="TYPE_TEXT",
        text=MASKED,
        page_changed=True,
        led_to="https://site.test/b",
    )
    assert run.jev.decided[1]["history"] == [typed_secret]
    assert page.typed[0] == SECRET


# --- secrets -----------------------------------------------------------------------------


async def test_a_secret_is_typed_into_the_page_and_never_into_what_the_agent_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landed = page_state(url=f"https://site.test/b?pw={SECRET}", text=f"welcome {SECRET}")
    page = FakePage(page_state(), landed)
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, PASSWORD),
        decision(JevOperation.DONE),
        value=MASKED,
        secrets=_secrets(),
    )

    result = await run.burst(f"log in with {MASKED}")

    assert page.typed == [SECRET]
    assert SECRET not in repr(result)
    assert result.steps[0].text == MASKED
    assert (result.url, result.text) == (f"https://site.test/b?pw={MASKED}", f"welcome {MASKED}")


async def test_a_password_field_holding_something_else_never_shows_what(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The field cut the secret at its maxlength: its start must not reach anyone.
    page = FakePage(page_state(), page_state(url="https://site.test/b"), holds={SECRET: SECRET[:7]})
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, PASSWORD),
        decision(JevOperation.DONE),
        value=MASKED,
        secrets=_secrets(),
    )

    result = await run.burst(f"log in with {MASKED}")

    assert result.steps[0].held == JEV_SECRET_DIFFERS
    assert SECRET[:7] not in repr(result)


async def test_a_written_value_that_names_a_secret_is_never_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, FIELD),
        value=GENERATE,
        text_model=_TextModel(f"user {MASKED}"),
        secrets=_secrets(),
    )

    result = await run.burst("sign in")

    assert result.stop is JevStop.GATEWAY
    assert JEV_SECRET_WRITTEN in result.detail
    assert page.typed == []


async def test_a_secret_is_never_typed_off_its_own_site_and_the_agent_is_told_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(page_state())
    run = _run(
        monkeypatch,
        page,
        decision(JevOperation.TYPE_TEXT, FIELD),
        value=MASKED,
        secrets=_secrets("bank.test"),
    )

    result = await run.burst(f"log in with {MASKED}")

    assert result.stop is JevStop.SECRET_WITHHELD
    assert "bank.test" in result.detail
    assert page.typed == []


async def test_a_password_field_with_no_stored_secret_is_left_to_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Jev types into a password field only a secret the run was given; the agent
    # types anything else, and the run learns it as a secret there.
    page = FakePage(page_state())
    run = _run(monkeypatch, page, decision(JevOperation.TYPE_TEXT, PASSWORD), value=NONE_VALUE)

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
        decision(JevOperation.CLICK, link),
        decision(JevOperation.SCROLL_DOWN, SCROLL),
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
            landed="https://site.test/b",
        ),
        JevStep(
            operation=JevOperation.SCROLL_DOWN,
            label="Scroll down",
            ident="",
            href="",
            text=None,
            url="https://site.test/b",
            page_changed=True,
            landed="https://site.test/c",
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
        decision(JevOperation.GO_BACK, BACK),
        decision(JevOperation.PRESS_ENTER, ENTER),
        decision(JevOperation.NAVIGATE, url=f"https://docs.test/?pw={SECRET}"),
        decision(JevOperation.DONE),
        secrets=_secrets(),
    )

    result = await run.burst()

    assert (page.acted, page.navigated) == (
        ["go_back", "enter"],
        [f"https://docs.test/?pw={SECRET}"],
    )
    assert [(step.label, step.opened) for step in result.steps] == [
        ("Go back to Site", None),
        ("Press Enter in Name", None),
        (f"Open https://docs.test/?pw={MASKED}", f"https://docs.test/?pw={MASKED}"),
    ]


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
        *[decision(JevOperation.CLICK, BUTTON)] * 4,
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


async def test_a_page_read_at_its_limit_keeps_no_start_of_a_value_cut_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop_mod, "JEV_REPORT_OPENED_PAGE_CHARS", 12)
    start, b, c = _pages("start", "b", "c")
    b = replace(b, text=f"welcome {SECRET}", fingerprint="b")
    page = FakePage(start, b, c)
    run = _run(
        monkeypatch,
        page,
        *[decision(JevOperation.CLICK, BUTTON)] * 2,
        decision(JevOperation.DONE),
        secrets=_secrets(),
    )

    result = await run.burst()

    assert result.opened[-1] == OpenedPage(url=b.url, title="Site", text="welcome ")


async def test_a_judgement_on_a_page_whose_controls_changed_in_place_is_made_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spinner = page_state()
    results = replace(spinner, actions=[replace_label(BUTTON, "Result 1"), FIELD, PASSWORD])
    page = FakePage(spinner)
    run = _run(monkeypatch, page, decision(JevOperation.DONE), decision(JevOperation.DONE))

    def _results_arrive() -> None:
        page.current = results

    run.jev.on_decide = _results_arrive

    await run.burst()

    assert run.jev.decided[1]["page"].actions[0]["label"] == "Result 1"


def replace_label(action: PageAction, label: str) -> PageAction:
    changed = action.copy()
    changed["label"] = label
    return changed


async def test_a_click_that_opens_a_tab_continues_on_that_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start, b, tab = _pages("start", "b", "tab")
    page = FakePage(start, b, new_tab=tab)
    run = _run(monkeypatch, page, decision(JevOperation.CLICK, BUTTON), decision(JevOperation.DONE))

    result = await run.burst()

    assert page.followed == 1
    assert (result.url, result.opened) == (tab.url, [])
    assert result.steps[0].page_changed is True


async def test_every_jev_call_and_action_lands_in_the_run_ledger_with_secrets_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pay = PageAction(id="e1", node=1, kind="click", label=f"Pay {SECRET}", role="button")
    evaluation = JevEvaluation(
        answers={},
        provider="vercel",
        usage=JevUsage(inputTokens=12, outputTokens=3, cost=0.002),
    )
    click = replace(decision(JevOperation.CLICK, pay), evaluation=evaluation)
    page = FakePage(replace(page_state(), actions=[pay, FIELD]), *_pages("b", "c"))
    run = _run(
        monkeypatch,
        page,
        click,
        decision(JevOperation.TYPE_TEXT, FIELD),
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
