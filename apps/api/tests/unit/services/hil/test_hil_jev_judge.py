"""JEV choice judge (app/services/hil/jev_judge.py).

The Decisions API is mocked — the network boundary. map_jev_choice,
ungrounded_targets, and the vetoes around the verdict are the production
code under test and run for real. Every test assumes the classifier at its
most confident and asks whether the code around it still refuses.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants import hil as hil_constants
from app.constants.hil import HIL_JEV_TIMEOUT_SECONDS, JevChoice
from app.constants.providers import CredentialProviderName
from app.models.jev_models import JevDecisionsResponse
from app.services.hil import intent, jev_judge, prompts
from app.services.hil.intent import (
    AutoHistory,
    IntentDecision,
    JudgedCall,
    ungrounded_targets,
)
from app.services.hil.jev_client import decisions_url, jev_http_client
from app.services.hil.jev_judge import (
    JevCase,
    JevIntentJudge,
    JevVerdict,
    ask_jev,
    decide_from_verdict,
    forbid_tripwire,
    map_jev_choice,
)
from app.services.hil.prompts import JEV_QUESTION
from app.services.hil.utils import PriorCall
from app.services.providers.provider_credentials_service import ProviderConfig

MODULE = "app.services.hil.jev_judge"
# The Decisions transport: the network boundary every JEV question crosses.
CLIENT_MODULE = "app.services.hil.jev_client"


def _call(**overrides: Any) -> JudgedCall:
    return JudgedCall(
        **{
            "tool_name": "send_email",
            "description": "Send an email.",
            "args": {"to": "bob@example.com", "subject": "deck"},
            "summary": "Send email — to: bob@example.com",
            **overrides,
        }
    )


def _answer(
    choice: str,
    confidence: float,
    probs: dict[str, float] | None = None,
    contained: float = 0.05,
) -> dict[str, Any]:
    return {
        "answers": {
            "decision": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": probs if probs is not None else {choice: confidence},
            },
            "contained": {"type": "noul", "noul": contained},
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


def _client(answer: dict[str, Any] | Exception) -> AsyncMock:
    """Fake JEV HTTP client serving one Decisions answer (or raising)."""
    response = MagicMock()
    response.json.return_value = answer
    client = AsyncMock()
    if isinstance(answer, Exception):
        client.post.side_effect = answer
    else:
        client.post.return_value = response
    return client


async def _decide(
    answer: dict[str, Any] | Exception,
    call: JudgedCall | None = None,
    history: AutoHistory | None = None,
) -> IntentDecision:
    judge = JevIntentJudge()
    with patch(f"{CLIENT_MODULE}.jev_http_client", _client(answer)):
        with _openrouter_key("or-key"):
            return await judge.decide(
                user_id="u",
                user_messages=["draft an email to bob@example.com about the deck"],
                call=call or _call(),
                prior_calls=[],
                history=history or AutoHistory(),
            )


class TestMapping:
    async def test_confident_authorized_is_accept(self) -> None:
        assert map_jev_choice("authorized", 0.9, accept_line=0.5) == "accept"

    async def test_below_line_authorized_is_ask_not_accept(self) -> None:
        # Confidence lines are load-bearing: a 0.49 authorized must not run.
        assert map_jev_choice("authorized", 0.49, accept_line=0.5) == "ask"

    async def test_forbidden_asks_however_confident(self) -> None:
        assert map_jev_choice("forbidden", 0.4, accept_line=0.5) == "ask"
        assert map_jev_choice("forbidden", 1.0, accept_line=0.5) == "ask"

    async def test_unclear_is_always_ask(self) -> None:
        assert map_jev_choice("unclear", 1.0, accept_line=0.5) == "ask"

    async def test_unknown_choice_is_ask(self) -> None:
        assert map_jev_choice("maybe", 1.0, accept_line=0.5) == "ask"


class TestForbiddenAsks:
    """A forbidden verdict is a question for the user, never a silent refusal."""

    async def test_a_runaway_forbidden_asks(self) -> None:
        d = await _decide(
            _answer("forbidden", 0.95, {"forbidden": 0.95, "unclear": 0.05, "authorized": 0.0})
        )
        assert d.outcome == "ask"


class TestForbidTripwire:
    """The tripwire only ever downgrades an accept into an ask."""

    async def test_forbid_without_lift_trips(self) -> None:
        assert forbid_tripwire(["keep everything for now", "delete thread t5"]) is True
        assert forbid_tripwire(["never pay anyone", "pay $10 now"]) is True

    async def test_lift_language_clears_the_tripwire(self) -> None:
        assert forbid_tripwire(["don't send anything yet", "actually, go ahead and send"]) is False

    async def test_clean_history_never_trips(self) -> None:
        assert forbid_tripwire(["draft an email to bob", "looks good, send it"]) is False

    async def test_forbid_language_floors_an_authorized_verdict_to_ask(self) -> None:
        d = decide_from_verdict(
            JevVerdict(choice="authorized", confidence=0.9, probabilities={"authorized": 0.9}),
            JevCase(
                call=_call(),
                user_messages=["don't send anything yet", "send it"],
                prior_calls=[],
                history=AutoHistory(),
            ),
        )
        assert d.outcome == "ask"
        assert "earlier message" in d.reason


class TestGrounding:
    async def test_an_address_from_the_users_words_is_grounded(self) -> None:
        assert (
            ungrounded_targets({"to": "bob@example.com"}, ["draft an email to bob@example.com"], [])
            == []
        )

    async def test_an_address_from_nowhere_blocks_accept(self) -> None:
        assert ungrounded_targets({"to": "mallory@evil.com"}, ["send the deck"], []) == [
            "mallory@evil.com"
        ]

    async def test_an_id_from_a_prior_lookup_is_grounded(self) -> None:
        priors = [PriorCall(name="FIND", args={"id": "d123"})]
        assert ungrounded_targets({"id": "d123"}, ["delete it"], priors) == []

    async def test_an_id_minted_in_a_prior_output_is_grounded(self) -> None:
        # The reported Gmail case: SEND_DRAFT carries only a draft id, which no
        # user ever typed. The create call's result minted it, so it traces to
        # the run — not to nowhere.
        priors = [
            PriorCall(
                name="GMAIL_CREATE_DRAFT",
                args={"to": "maradiyadhruv0@gmail.com", "subject": "Test email"},
                output='{"draft_id": "r6898160653200701840", "to": "maradiyadhruv0@gmail.com"}',
            )
        ]
        assert (
            ungrounded_targets(
                {"draft_id": "r6898160653200701840"},
                ["send test mail to maradiyadhruv0@gmail.com", "send"],
                priors,
            )
            == []
        )

    async def test_an_id_picked_from_a_list_is_not_grounded(self) -> None:
        # A result that lists several ids presents a choice: acting on one of
        # them involves agent judgment, so the veto stands even though the id
        # appears in a prior output.
        priors = [
            PriorCall(
                name="FIND",
                args={"query": "standup"},
                output='[{"event_id": "evt-4"}, {"event_id": "evt-5"}]',
            )
        ]
        assert ungrounded_targets({"event_id": "evt-4"}, ["cancel it"], priors) == ["evt-4"]

    async def test_an_unparseable_output_identifies_nothing(self) -> None:
        priors = [PriorCall(name="FIND", args={}, output="two things happened")]
        assert ungrounded_targets({"event_id": "evt-4"}, ["cancel it"], priors) == ["evt-4"]

    async def test_a_name_in_words_grounds_its_email(self) -> None:
        # "Sarah's" grounds sarah@x.com; the domain was resolved, not chosen.
        assert ungrounded_targets({"to": "sarah@x.com"}, ["reply yes to sarah's thread"], []) == []

    async def test_a_name_prefix_never_grounds_a_longer_address(self) -> None:
        # "bob" must not ground bobby@evil.com — equality on the local part.
        assert ungrounded_targets({"to": "bobby@evil.com"}, ["email bob now"], []) == [
            "bobby@evil.com"
        ]

    async def test_a_known_address_is_provenance_not_novelty(self) -> None:
        assert (
            ungrounded_targets(
                {"to": "bob@x.com"}, ["yes, send it"], [], known=frozenset({"bob@x.com"})
            )
            == []
        )

    async def test_boolean_flags_are_never_targets(self) -> None:
        # Python's bool subclasses int: without the guard, create_meeting_room
        # becomes the target "True" and every meet-link booking asks forever.
        assert ungrounded_targets({"create_meeting_room": True}, ["book it"], []) == []

    async def test_prose_bodies_are_not_targets(self) -> None:
        # The body is judged by the choice criteria, not by provenance.
        assert ungrounded_targets({"body": "hello world 123"}, ["send it"], []) == []

    async def test_ungrounded_target_downgrades_a_confident_authorized_to_ask(
        self,
    ) -> None:
        d = await _decide(
            _answer("authorized", 0.99),
            call=_call(args={"to": "mallory@evil.com"}),
        )
        assert d.outcome == "ask"
        assert "mallory@evil.com" in d.reason

    async def test_authorized_send_of_a_minted_draft_id_stays_accepted(self) -> None:
        # The reported Gmail case at the pure seam (no network): a confident
        # authorized verdict plus the create call's output carrying the draft
        # id. The id traces to the run, so the veto stands down.
        d = decide_from_verdict(
            JevVerdict(
                choice="authorized",
                confidence=0.9,
                probabilities={"authorized": 0.9},
            ),
            JevCase(
                call=_call(args={"draft_id": "r6898160653200701840"}),
                user_messages=["send test mail to maradiyadhruv0@gmail.com", "send"],
                prior_calls=[
                    PriorCall(
                        name="GMAIL_CREATE_DRAFT",
                        args={"to": "maradiyadhruv0@gmail.com", "subject": "Test email"},
                        output='{"draft_id": "r6898160653200701840"}',
                    )
                ],
                history=AutoHistory(),
            ),
        )
        assert d.outcome == "accept"


class TestVetoes:
    async def test_forbidden_is_ask_with_a_reason(self) -> None:
        d = await _decide(_answer("forbidden", 0.9))
        assert d.outcome == "ask"
        assert d.reason

    async def test_unclear_is_ask_carrying_tool_and_choice(self) -> None:
        # The gate adds the "Auto mode wasn't sure:" prefix uniformly;
        # the judge's job is naming the tool and the verdict behind it.
        d = await _decide(_answer("unclear", 0.9))
        assert d.outcome == "ask"
        assert "send_email" in d.reason and "unclear" in d.reason

    async def test_history_of_denies_blocks_an_authorized_call(self) -> None:
        d = await _decide(
            _answer("authorized", 0.99),
            history=AutoHistory(approved_recent=0, denied_recent=2),
        )
        assert d.outcome == "ask"
        assert "denied" in d.reason

    async def test_clean_history_leaves_authorized_accepted(self) -> None:
        d = await _decide(
            _answer("authorized", 0.99),
            history=AutoHistory(approved_recent=4, denied_recent=0),
        )
        assert d.outcome == "accept"


class TestWire:
    async def test_state_names_its_evidence_fields(self) -> None:
        """The criteria reference these names; a renamed field blinds the judge."""
        client = _client(_answer("unclear", 0.5))
        with patch(f"{CLIENT_MODULE}.jev_http_client", client):
            with _openrouter_key("or-key"):
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[],
                    history=AutoHistory(),
                )
        posted = client.post.await_args.kwargs["json"]
        assert set(posted["state"]) == {
            "user_messages",
            "pending_action",
            "prior_actions",
            "recent_history",
            "now",
        }
        assert set(posted["state"]["pending_action"]) == {
            "tool",
            "description",
            "summary",
            "args",
        }
        assert posted["questions"]["decision"]["type"] == "choice"

    async def test_enrichment_rides_only_when_it_exists(self) -> None:
        """Empty evidence reads as missing evidence and costs confidence, so an old-shape call posts the old-shape state — and a rich call carries it all."""
        client = _client(_answer("unclear", 0.5))
        with patch(f"{CLIENT_MODULE}.jev_http_client", client):
            with _openrouter_key("or-key"):
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[PriorCall(name="FIND", args={})],
                    history=AutoHistory(),
                )
        posted = client.post.await_args.kwargs["json"]
        assert set(posted["state"]["pending_action"]) == {
            "tool",
            "description",
            "summary",
            "args",
        }
        assert posted["state"]["prior_actions"] == [{"tool": "FIND", "args": {}}]
        assert "assistant_turns" not in posted["state"]

        client = _client(_answer("unclear", 0.5))
        with patch(f"{CLIENT_MODULE}.jev_http_client", client):
            with _openrouter_key("or-key"):
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(
                        args={"draft_id": "r1"},
                        tool_schema={"properties": {"draft_id": {"type": "string"}}},
                    ),
                    prior_calls=[PriorCall(name="CREATE", args={}, output='{"draft_id": "r1"}')],
                    history=AutoHistory(),
                    assistant_turns=["your draft is ready"],
                )
        posted = client.post.await_args.kwargs["json"]
        assert posted["state"]["pending_action"]["tool_schema"] == {
            "properties": {"draft_id": {"type": "string"}}
        }
        assert posted["state"]["prior_actions"] == [
            {"tool": "CREATE", "args": {}, "output": '{"draft_id": "r1"}'}
        ]
        assert posted["state"]["assistant_turns"] == ["your draft is ready"]

    async def test_usage_is_reported(self) -> None:
        with patch(f"{CLIENT_MODULE}.jev_http_client", _client(_answer("unclear", 0.5))):
            with _openrouter_key("or-key"):
                verdict, tokens_in, tokens_out = await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[],
                    history=AutoHistory(),
                )
        assert verdict == JevVerdict(
            choice="unclear", confidence=0.5, probabilities={"unclear": 0.5}, contained=0.05
        )
        assert (tokens_in, tokens_out) == (300, 20)


def _sequence_client(*answers: dict[str, Any] | Exception) -> AsyncMock:
    """Fake JEV HTTP client serving one answer per post, in order."""
    effects: list[Any] = []
    for answer in answers:
        if isinstance(answer, Exception):
            effects.append(answer)
        else:
            response = MagicMock()
            response.json.return_value = answer
            effects.append(response)
    client = AsyncMock()
    client.post.side_effect = effects
    return client


@contextmanager
def _jev(client: AsyncMock, key: str | None = "or-key") -> Iterator[None]:
    """Serve client as the Decisions API with key configured."""
    with patch(f"{CLIENT_MODULE}.jev_http_client", client), _openrouter_key(key):
        yield


def _openrouter_key(key: str | None) -> AbstractContextManager[AsyncMock]:
    """Serve key as the resolved OpenRouter credential; every other provider resolves to nothing."""

    async def resolve(provider: str) -> ProviderConfig | None:
        if key is None or provider != CredentialProviderName.OPENROUTER:
            return None
        return ProviderConfig(api_key=key)

    return patch(f"{CLIENT_MODULE}.resolve", AsyncMock(side_effect=resolve))


FORBID_TURNS = ["never email bob@example.com", "email bob@example.com the deck"]


class TestTheLinesAreInclusive:
    async def test_confidence_exactly_on_the_accept_line_accepts(self) -> None:
        assert map_jev_choice("authorized", 0.5, accept_line=0.5) == "accept"


class TestTheTripwireReadsEachLaterTurn:
    async def test_a_lift_in_any_later_turn_clears_it(self) -> None:
        assert forbid_tripwire(["don't send it", "actually", "ok"]) is False

    async def test_a_lift_is_never_assembled_from_two_turns(self) -> None:
        assert forbid_tripwire(["don't send it", "go", "ahead"]) is True


class TestTheDecisionsWire:
    async def test_every_request_is_bounded_by_the_jev_timeout(self) -> None:
        assert jev_http_client.timeout == httpx.Timeout(HIL_JEV_TIMEOUT_SECONDS)

    async def test_the_request_is_bounded_authenticated_and_names_its_model(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with _jev(client):
            await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        post = client.post.await_args
        assert post.args == (decisions_url(None),)
        assert post.kwargs["headers"] == {"Authorization": "Bearer or-key"}
        posted = post.kwargs["json"]
        # The judge asks the model its lines were tuned on; other JEV callers keep theirs.
        assert posted["model"] == hil_constants.HIL_JEV_JUDGE_MODEL_NAME
        # Authorization and containment are asked together, in one request.
        assert posted["questions"] == {
            "decision": JEV_QUESTION,
            "contained": prompts.JEV_CONTAINED_QUESTION,
        }
        assert posted["state"]["recent_history"] == "No recent decisions on send_email."
        assert datetime.fromisoformat(posted["state"]["now"]).tzinfo == UTC

    async def test_no_key_means_no_request(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with (
            _jev(client, key=None),
            pytest.raises(
                RuntimeError, match="^No OpenRouter key saved or set; cannot reach the JEV judge$"
            ),
        ):
            await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )
        client.post.assert_not_awaited()

    async def test_a_non_choice_answer_is_refused_with_a_bounded_message(self) -> None:
        answer = {"answers": {"decision": {"type": "text", "choice": "x" * 400}}}
        with _jev(_sequence_client(answer)), pytest.raises(ValueError) as caught:
            await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        assert str(caught.value).startswith("non-choice JEV answer: ")
        assert len(str(caught.value)) == 300

    async def test_an_unknown_choice_is_refused_by_name(self) -> None:
        with _jev(_sequence_client(_answer("maybe", 0.9))), pytest.raises(ValueError) as caught:
            await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        assert str(caught.value) == "unknown JEV choice: 'maybe'"

    async def test_missing_confidence_and_usage_read_as_zero(self) -> None:
        answer = {
            "answers": {
                "decision": {"type": "choice", "choice": "authorized"},
                "contained": {"type": "noul", "noul": 0.1},
            }
        }
        with _jev(_sequence_client(answer)):
            result = await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        assert result == (
            JevVerdict(choice="authorized", confidence=0.0, probabilities={}, contained=0.1),
            0,
            0,
        )


class TestTheJudgeAroundTheWire:
    async def test_the_users_and_assistants_turns_reach_jev(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with _jev(client):
            await JevIntentJudge().decide(
                user_id="u",
                user_messages=["draft it", "send it"],
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
                assistant=intent.AssistantTurns(shown=("Your draft is ready.",)),
            )

        state = client.post.await_args.kwargs["json"]["state"]
        assert state["user_messages"] == ["draft it", "send it"]
        assert state["assistant_turns"] == ["Your draft is ready."]

    async def test_forbid_language_the_focused_check_upholds_asks(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9), _forbid_answer("forbidden", 0.9))
        with _jev(client):
            decision = await JevIntentJudge().decide(
                user_id="u",
                user_messages=FORBID_TURNS,
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )

        assert decision == IntentDecision(
            "ask",
            "an earlier message argues against this send_email call and nothing since lifted it.",
        )
        assert client.post.await_count == 2

    async def test_a_dont_that_forbids_nothing_lets_an_authorized_send_run(self) -> None:
        """'Don't we have the draft ready?' is a question, not a rule against sending."""
        turns = ["Don't we have the draft ready for bob@example.com?", "send it to bob@example.com"]
        client = _sequence_client(_answer("authorized", 0.9), _forbid_answer("permitted", 0.9))
        with _jev(client):
            decision = await JevIntentJudge().decide(
                user_id="u",
                user_messages=turns,
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )

        assert decision.outcome == "accept"
        assert client.post.await_count == 2

    async def test_a_failed_focused_check_on_an_authorized_call_asks(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9), httpx.ConnectError("down"))
        with _jev(client):
            decision = await JevIntentJudge().decide(
                user_id="u",
                user_messages=FORBID_TURNS,
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )

        assert decision.outcome == "ask"

    async def test_no_forbid_language_accepts(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9))
        with _jev(client):
            decision = await JevIntentJudge().decide(
                user_id="u",
                user_messages=["draft an email to bob@example.com about the deck"],
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )

        assert decision == IntentDecision(
            "accept", "Auto mode matched this to your request (authorized 0.90)."
        )
        assert client.post.await_count == 1


def _verdict_case(
    args: dict[str, object], turns: list[str], history: AutoHistory | None = None
) -> IntentDecision:
    return decide_from_verdict(
        JevVerdict(choice="authorized", confidence=0.9, probabilities={"authorized": 0.9}),
        JevCase(
            call=_call(args=args),
            user_messages=turns,
            prior_calls=[],
            history=history or AutoHistory(),
        ),
    )


class TestWhatTheUserIsTold:
    async def test_a_history_hold_says_how_many_denials(self) -> None:
        decision = _verdict_case(
            {"to": "bob@example.com"},
            ["email bob@example.com"],
            AutoHistory(approved_recent=1, denied_recent=2),
        )

        assert decision == IntentDecision(
            "ask",
            "You denied 2 recent send_email call(s), so this one needs your go-ahead even "
            "though it looks authorized.",
        )

    async def test_untraced_targets_are_named_three_at_most(self) -> None:
        args: dict[str, object] = {"to": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}

        decision = _verdict_case(args, ["send it"])

        assert decision == IntentDecision(
            "ask", "the target (a@x.com, b@x.com, c@x.com) doesn't trace to your words."
        )

    async def test_a_target_from_the_users_approved_runs_is_known(self) -> None:
        history = AutoHistory(approved_recent=3, known_targets=("bob@x.com",))

        decision = _verdict_case({"to": "bob@x.com"}, ["send it"], history)

        assert decision.outcome == "accept"

    async def test_a_target_split_across_two_turns_traces_to_neither(self) -> None:
        decision = _verdict_case({"ref": "order-77"}, ["cancel order", "77 please"])

        assert decision.outcome == "ask"


def _forbid_answer(choice: str, confidence: float | None) -> dict[str, Any]:
    return {"answers": {"forbid": {"type": "choice", "choice": choice, "confidence": confidence}}}


class TestSettleForbid:
    """Only a confident "permitted" clears an earlier forbid; doubt asks."""

    def test_forbidden_at_the_floor_forbids(self) -> None:
        floor = hil_constants.HIL_JEV_FORBID_FLOOR
        assert jev_judge.settle_forbid("forbidden", floor) is JevChoice.FORBIDDEN

    def test_forbidden_below_the_floor_still_forbids(self) -> None:
        floor = hil_constants.HIL_JEV_FORBID_FLOOR
        assert jev_judge.settle_forbid("forbidden", floor - 0.01) is JevChoice.FORBIDDEN

    def test_permitted_at_the_floor_permits(self) -> None:
        floor = hil_constants.HIL_JEV_FORBID_FLOOR
        assert jev_judge.settle_forbid("permitted", floor) is JevChoice.PERMITTED

    def test_an_unsure_permitted_forbids(self) -> None:
        """'keep everything for now' then 'delete t5': JEV said permitted at 0.04."""
        assert jev_judge.settle_forbid("permitted", 0.04) is JevChoice.FORBIDDEN

    def test_the_sweep_can_move_the_floor(self) -> None:
        assert jev_judge.settle_forbid("permitted", 0.6, floor=0.7) is JevChoice.FORBIDDEN
        assert jev_judge.settle_forbid("permitted", 0.6, floor=0.5) is JevChoice.PERMITTED


class TestTheForbidWire:
    async def test_the_focused_question_sees_earlier_and_latest_turns_apart(self) -> None:
        turns = ["never email bob", "hold on", "email bob the deck"]
        client = _sequence_client(_forbid_answer("forbidden", 0.8))
        with _jev(client):
            result = await jev_judge.ask_jev_forbid(user_messages=turns, call=_call())

        assert result == ("forbidden", 0.8, 0, 0)
        assert client.post.await_args.kwargs["json"] == {
            "model": hil_constants.HIL_JEV_JUDGE_MODEL_NAME,
            "state": {
                "earlier_turns": ["never email bob", "hold on"],
                "latest_turns": ["email bob the deck"],
                "pending_action": {"tool": "send_email", "args": _call().args},
            },
            "questions": {"forbid": prompts.JEV_FORBID_QUESTION},
        }

    async def test_an_unknown_choice_is_refused_by_name(self) -> None:
        with (
            _jev(_sequence_client(_forbid_answer("authorized", 0.9))),
            pytest.raises(ValueError, match="^unknown JEV forbid choice: 'authorized'$"),
        ):
            await jev_judge.ask_jev_forbid(user_messages=FORBID_TURNS, call=_call())


_FULL_PROBS = {"unclear": 0.6, "authorized": 0.4, "forbidden": 0.0}


def _transport(*bodies: dict[str, Any]) -> AsyncMock:
    return AsyncMock(side_effect=[JevDecisionsResponse.model_validate(body) for body in bodies])


class TestAContainedCallWithForbidWords:
    """An unclear call can still run on containment, so containment alone earns the forbid check."""

    async def test_both_questions_go_through_the_transport_the_judge_was_given(self) -> None:
        transport = _transport(
            _answer("unclear", 0.6, _FULL_PROBS, contained=0.95),
            _forbid_answer("permitted", 0.9),
        )

        decision = await JevIntentJudge(transport=transport).decide(
            user_id="u",
            user_messages=["don't worry about the formatting", "tidy my notes page"],
            call=_call(tool_name="NOTION_INSERT_MARKDOWN", args={"page_id": "p1"}),
            prior_calls=[],
            history=AutoHistory(),
        )

        assert transport.await_count == 2
        assert decision == IntentDecision(
            "accept",
            "Auto mode ran this: it stays in your account and can be undone (contained 0.95).",
        )

    async def test_a_failed_focused_check_asks(self) -> None:
        transport = AsyncMock(
            side_effect=[
                JevDecisionsResponse.model_validate(
                    _answer("unclear", 0.6, _FULL_PROBS, contained=0.95)
                ),
                httpx.ConnectError("down"),
            ]
        )

        decision = await JevIntentJudge(transport=transport).decide(
            user_id="u",
            user_messages=["never share my notes", "tidy my notes page"],
            call=_call(tool_name="NOTION_INSERT_MARKDOWN", args={"page_id": "p1"}),
            prior_calls=[],
            history=AutoHistory(),
        )

        assert decision.outcome == "ask"

    async def test_an_uncontained_call_never_spends_the_focused_check(self) -> None:
        transport = _transport(_answer("unclear", 0.6, _FULL_PROBS, contained=0.1))

        await JevIntentJudge(transport=transport).decide(
            user_id="u",
            user_messages=FORBID_TURNS,
            call=_call(),
            prior_calls=[],
            history=AutoHistory(),
        )

        assert transport.await_count == 1


def _verdict(
    choice: str = "unclear",
    confidence: float = 0.6,
    contained: float | None = 0.95,
    forbid: str | None = None,
) -> JevVerdict:
    return JevVerdict(
        choice=choice,
        confidence=confidence,
        # Real answers carry all three choices; the rest goes to the non-forbidden side.
        probabilities={
            **dict.fromkeys(("authorized", "unclear"), (1 - confidence) / 2),
            "forbidden": 0.0,
            choice: confidence,
        },
        contained=contained,
        forbid=forbid,
    )


def _contained_case(
    verdict: JevVerdict | None = None,
    *,
    turns: list[str] | None = None,
    history: AutoHistory | None = None,
    args: dict[str, object] | None = None,
) -> IntentDecision:
    return decide_from_verdict(
        verdict or _verdict(),
        JevCase(
            call=_call(tool_name="exec", args=args or {"command": "call query-run SELECT 1"}),
            user_messages=turns or ["how many users signed up in the last 9 days?"],
            prior_calls=[],
            history=history or AutoHistory(),
        ),
    )


class TestContainedActionsRunWithoutExplicitWords:
    """An action that stays in the user's account and can be undone needs no authorizing words."""

    @pytest.mark.regression
    async def test_a_contained_call_the_judge_was_unsure_about_runs(self) -> None:
        """Prod 2026-11-15: read-only queries the user asked for scored authorized 0.28-0.46."""
        decision = _contained_case(_verdict(choice="authorized", confidence=0.28))

        assert decision == IntentDecision(
            "accept",
            "Auto mode ran this: it stays in your account and can be undone (contained 0.95).",
        )

    async def test_an_unclear_contained_call_runs(self) -> None:
        assert _contained_case(_verdict(choice="unclear")).outcome == "accept"

    async def test_a_contained_call_with_an_untraced_target_runs(self) -> None:
        decision = _contained_case(
            _verdict(choice="authorized", confidence=0.9), args={"page_id": "4147df99-77ba"}
        )

        assert decision.outcome == "accept"

    async def test_containment_just_under_the_line_still_asks(self) -> None:
        assert (
            _contained_case(_verdict(contained=hil_constants.HIL_JEV_CONTAINED_LINE - 0.01)).outcome
            == "ask"
        )

    async def test_containment_at_the_line_runs(self) -> None:
        assert (
            _contained_case(_verdict(contained=hil_constants.HIL_JEV_CONTAINED_LINE)).outcome
            == "accept"
        )

    async def test_no_containment_answer_changes_nothing(self) -> None:
        assert _contained_case(_verdict(contained=None)).outcome == "ask"

    async def test_any_argument_the_judge_sees_against_it_asks(self) -> None:
        """A notification after "no notifications after 6pm" scored contained 0.96, P(forbidden) 0.25."""
        decision = decide_from_verdict(
            JevVerdict(
                choice="authorized",
                confidence=0.31,
                probabilities={
                    "authorized": 0.54,
                    "forbidden": hil_constants.HIL_JEV_CONTAINED_MAX_FORBIDDEN,
                    "unclear": 0.21,
                },
                contained=0.96,
            ),
            JevCase(
                call=_call(),
                user_messages=["notify me the deploy finished"],
                prior_calls=[],
                history=AutoHistory(),
            ),
        )

        assert decision.outcome == "ask"

    async def test_an_answer_without_a_forbidden_probability_never_runs(self) -> None:
        decision = decide_from_verdict(
            JevVerdict(choice="unclear", confidence=0.6, probabilities={}, contained=0.95),
            JevCase(
                call=_call(tool_name="exec"),
                user_messages=["how many users signed up?"],
                prior_calls=[],
                history=AutoHistory(),
            ),
        )

        assert decision.outcome == "ask"

    async def test_a_forbidden_leaning_call_never_runs(self) -> None:
        assert _contained_case(_verdict(choice="forbidden", confidence=0.4)).outcome == "ask"

    async def test_a_confident_forbid_asks_never_refuses(self) -> None:
        assert _contained_case(_verdict(choice="forbidden", confidence=0.9)).outcome == "ask"

    async def test_forbid_language_without_the_focused_check_holds_it(self) -> None:
        assert _contained_case(turns=["don't touch my notes", "tidy the notes"]).outcome == "ask"

    @pytest.mark.regression
    async def test_casual_forbid_words_cleared_by_the_focused_check_run(self) -> None:
        """Prod 2026-11: "can't"/"never" in ordinary chat tripped 26 of 61 real asked calls."""
        turns = ["for MCP we can't generate a link?", "ok check the flags in posthog"]

        assert (
            _contained_case(_verdict(forbid=JevChoice.PERMITTED), turns=turns).outcome == "accept"
        )

    async def test_a_focused_forbid_holds_it(self) -> None:
        turns = ["never touch my notes", "tidy the notes page"]

        assert _contained_case(_verdict(forbid=JevChoice.FORBIDDEN), turns=turns).outcome == "ask"

    async def test_only_a_call_that_may_run_with_forbid_words_earns_the_focused_check(
        self,
    ) -> None:
        turns = ["we can't ship today", "check the flags"]
        line = hil_constants.HIL_JEV_CONTAINED_LINE
        accept = hil_constants.HIL_JEV_ACCEPT_LINE

        assert jev_judge.needs_forbid_check(turns, _verdict(contained=line)) is True
        assert jev_judge.needs_forbid_check(turns, _verdict(contained=line - 0.01)) is False
        assert jev_judge.needs_forbid_check(turns, _verdict(contained=None)) is False
        assert jev_judge.needs_forbid_check(["check the flags"], _verdict(contained=0.99)) is False
        # Authorized by the user's words: forbid words earn the same focused question.
        assert (
            jev_judge.needs_forbid_check(
                turns, _verdict(choice="authorized", confidence=accept, contained=0.0)
            )
            is True
        )
        assert (
            jev_judge.needs_forbid_check(
                turns, _verdict(choice="authorized", confidence=accept - 0.01, contained=0.0)
            )
            is False
        )

    @pytest.mark.parametrize(
        "hold",
        [
            "hold off on my notes for now",
            "wait for my approval before editing my notes",
            "don't touch the notes page yet",
            "anything on my notes needs my go-ahead",
        ],
    )
    async def test_a_hold_the_user_set_keeps_it_asking(self, hold: str) -> None:
        assert _contained_case(turns=[hold, "summarize the page"]).outcome == "ask"

    @pytest.mark.parametrize(
        "later",
        ["actually, just summarize the page", "go ahead and summarize the page"],
    )
    async def test_a_go_ahead_for_something_else_does_not_lift_a_hold(self, later: str) -> None:
        turns = ["check with me first before changing my notes", later]

        assert _contained_case(turns=turns).outcome == "ask"

    async def test_a_bare_go_ahead_lifts_a_hold(self) -> None:
        turns = ["check with me first before changing my notes", "ok, go ahead"]

        assert _contained_case(turns=turns).outcome == "accept"

    @pytest.mark.parametrize(
        ("history", "outcome"),
        [
            (AutoHistory(approved_recent=2, denied_recent=1), "ask"),
            (AutoHistory(approved_recent=3), "accept"),
            (AutoHistory(), "accept"),
        ],
    )
    async def test_any_recent_denial_holds_it(self, history: AutoHistory, outcome: str) -> None:
        assert _contained_case(history=history).outcome == outcome


class TestAConfirmationOfWhatTheUserWasShown:
    _LISTING = (
        "Visible drafts (id | to | subject | gist):\n"
        '1. r2569937965309608501 | boardy@x.com | "Intro" | intro\n'
        '2. r8807310570127663349 | simonne@intrinsicurlyme.co.za | "Re: October Invoice" | pdf'
    )

    @pytest.mark.regression
    async def test_send_after_the_drafted_reply_was_described_runs(self) -> None:
        """Prod 2026-11-15: JEV said authorized 0.92, the list-pick backstop still asked."""
        transport = _transport(_answer("authorized", 0.92))

        decision = await JevIntentJudge(transport=transport).decide(
            user_id="u",
            user_messages=["Send"],
            call=_call(tool_name="GMAIL_SEND_DRAFT", args={"draft_id": "r8807310570127663349"}),
            prior_calls=[PriorCall(name="GMAIL_LIST_DRAFTS", args={}, output=self._LISTING)],
            history=AutoHistory(),
            assistant=intent.AssistantTurns(
                shown=("I drafted the reply to Simonne with the October invoice attached.",)
            ),
        )

        assert decision.outcome == "accept"

    async def test_only_what_the_user_saw_grounds_the_pick(self) -> None:
        """The judge's context may hold a run's internal messages; they never ground a pick."""
        transport = _transport(_answer("authorized", 0.92))

        decision = await JevIntentJudge(transport=transport).decide(
            user_id="u",
            user_messages=["Send"],
            call=_call(tool_name="GMAIL_SEND_DRAFT", args={"draft_id": "r8807310570127663349"}),
            prior_calls=[PriorCall(name="GMAIL_LIST_DRAFTS", args={}, output=self._LISTING)],
            history=AutoHistory(),
            assistant=intent.AssistantTurns(run=("Picked the draft for simonne.",)),
        )

        assert decision.outcome == "ask"


def _standing_answer(choice: str, confidence: float) -> dict[str, Any]:
    return {
        "answers": {
            hil_constants.JEV_STANDING_QUESTION_KEY: {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
            }
        }
    }


class TestTheUsersSavedInstructions:
    """Only the instructions and the pending action reach the question: no turns to lift them."""

    RULES = ("Always ask me before emailing my boss.", "Reply in English.")

    async def test_the_question_sees_the_instructions_and_the_action_alone(self) -> None:
        transport = _transport(_standing_answer("forbidden", 0.9))
        await JevIntentJudge(transport=transport).standing_rules_hold(
            standing_rules=self.RULES, call=_call()
        )
        state, questions = transport.await_args.args
        assert state == {
            "standing_instructions": list(self.RULES),
            "pending_action": {"tool": "send_email", "args": _call().args},
        }
        assert questions == {hil_constants.JEV_STANDING_QUESTION_KEY: prompts.JEV_STANDING_QUESTION}

    @pytest.mark.parametrize(
        ("choice", "offset", "holds"),
        [
            ("forbidden", 0.0, True),
            ("forbidden", -0.01, True),
            ("permitted", -0.01, True),
            ("permitted", 0.0, False),
        ],
        ids=["forbidden", "unsure-forbidden", "unsure-permitted", "permitted-at-floor"],
    )
    async def test_a_rule_lets_the_call_run_only_when_confidently_permitted(
        self, choice: str, offset: float, holds: bool
    ) -> None:
        confidence = hil_constants.HIL_JEV_FORBID_FLOOR + offset
        transport = _transport(_standing_answer(choice, confidence))
        assert (
            await JevIntentJudge(transport=transport).standing_rules_hold(
                standing_rules=self.RULES, call=_call()
            )
            is holds
        )
