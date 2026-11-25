"""JEV choice judge (app/services/hil/jev_judge.py).

The Decisions API is mocked — the network boundary. map_jev_choice,
ungrounded_targets, and the vetoes around the verdict are the production
code under test and run for real. Every test assumes the classifier at its
most confident and asks whether the code around it still refuses. One gated
call is one request: every question rides in it, and no word list second-guesses
what the user wrote.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.constants import hil as hil_constants
from app.constants.hil import HIL_JEV_TIMEOUT_SECONDS, JevChoice
from app.constants.providers import CredentialProviderName
from app.models.jev_models import JevDecisionsResponse
from app.services.hil import intent, prompts
from app.services.hil.intent import (
    AutoContext,
    AutoHistory,
    IntentDecision,
    JudgedCall,
    judge_intent,
    ungrounded_targets,
)
from app.services.hil.jev_client import decisions_url, jev_http_client
from app.services.hil.jev_judge import (
    JevCase,
    JevIntentJudge,
    JevVerdict,
    ask_jev,
    decide_from_verdict,
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


#: Nothing objects, with confidence to spare: the answer a plain request gets.
_NOTHING_OBJECTS = ("permitted", 0.95)


def _choice_answer(choice: str, confidence: float | None) -> dict[str, Any]:
    return {"type": "choice", "choice": choice, "confidence": confidence}


def _full_probabilities(choice: str, confidence: float) -> dict[str, float]:
    """All three choices, as a real answer carries them: what the pick leaves goes to "unclear" (else "authorized")."""
    rest = "authorized" if choice == JevChoice.UNCLEAR else "unclear"
    return {"authorized": 0.0, "forbidden": 0.0, "unclear": 0.0} | {
        choice: confidence,
        rest: 1.0 - confidence,
    }


def _answer(
    choice: str,
    confidence: float,
    probs: dict[str, float] | None = None,
    contained: float = 0.05,
    objection: tuple[str, float | None] | None = _NOTHING_OBJECTS,
    go_ahead: tuple[str, float | None] | None = None,
) -> dict[str, Any]:
    """One Decisions body answering every question: objection and go_ahead only when given."""
    answers: dict[str, Any] = {
        "decision": {
            **_choice_answer(choice, confidence),
            "probabilities": probs
            if probs is not None
            else _full_probabilities(choice, confidence),
        },
        "contained": {"type": "noul", "noul": contained},
    }
    if objection is not None:
        answers["objection"] = _choice_answer(*objection)
    if go_ahead is not None:
        answers["go_ahead"] = _choice_answer(*go_ahead)
    return {"answers": answers, "usage": {"input_tokens": 300, "output_tokens": 20}}


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
                auto=AutoContext(user_id="u", history=history or AutoHistory()),
                user_messages=["draft an email to bob@example.com about the deck"],
                call=call or _call(),
                prior_calls=[],
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
                probabilities={"authorized": 0.9, "forbidden": 0.0},
                objection=0.95,
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
                    auto=AutoContext(user_id="u"),
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
                    auto=AutoContext(user_id="u"),
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
        assert "run_messages" not in posted["state"]

        client = _client(_answer("unclear", 0.5, go_ahead=_NOT_A_GO_AHEAD))
        with patch(f"{CLIENT_MODULE}.jev_http_client", client):
            with _openrouter_key("or-key"):
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(
                        args={"draft_id": "r1"},
                        tool_schema={"properties": {"draft_id": {"type": "string"}}},
                    ),
                    prior_calls=[PriorCall(name="CREATE", args={}, output='{"draft_id": "r1"}')],
                    auto=AutoContext(user_id="u"),
                    assistant=intent.AssistantTurns(shown=("your draft is ready",)),
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
                    auto=AutoContext(user_id="u"),
                )
        assert verdict == JevVerdict(
            choice="unclear",
            confidence=0.5,
            probabilities=_full_probabilities("unclear", 0.5),
            contained=0.05,
            objection=0.95,
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

#: JEV's go-ahead answer when the reply is not one: the call can then run only on its own merits.
_NOT_A_GO_AHEAD = ("unclear", 0.9)


class TestTheLinesAreInclusive:
    async def test_confidence_exactly_on_the_accept_line_accepts(self) -> None:
        assert map_jev_choice("authorized", 0.5, accept_line=0.5) == "accept"


class TestTheDecisionsWire:
    async def test_every_request_is_bounded_by_the_jev_timeout(self) -> None:
        assert jev_http_client.timeout == httpx.Timeout(HIL_JEV_TIMEOUT_SECONDS)

    async def test_the_request_is_bounded_authenticated_and_names_its_model(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with _jev(client):
            await ask_jev(
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
            )

        post = client.post.await_args
        assert post.args == (decisions_url(None),)
        assert post.kwargs["headers"] == {"Authorization": "Bearer or-key"}
        posted = post.kwargs["json"]
        # The judge asks the model its lines were tuned on; other JEV callers keep theirs.
        assert posted["model"] == hil_constants.HIL_JEV_JUDGE_MODEL_NAME
        # Every question rides in the one request.
        assert posted["questions"] == {
            "decision": JEV_QUESTION,
            "contained": prompts.JEV_CONTAINED_QUESTION,
            "objection": prompts.JEV_OBJECTION_QUESTION,
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
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
            )
        client.post.assert_not_awaited()

    async def test_a_non_choice_answer_is_refused_with_a_bounded_message(self) -> None:
        answer = {"answers": {"decision": {"type": "text", "choice": "x" * 400}}}
        with _jev(_sequence_client(answer)), pytest.raises(ValueError) as caught:
            await ask_jev(
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
            )

        assert str(caught.value).startswith("non-choice JEV answer: ")
        assert len(str(caught.value)) == 300

    async def test_an_unknown_choice_is_refused_by_name(self) -> None:
        with _jev(_sequence_client(_answer("maybe", 0.9))), pytest.raises(ValueError) as caught:
            await ask_jev(
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
            )

        assert str(caught.value) == "unknown JEV choice: 'maybe'"

    async def test_missing_confidence_and_usage_read_as_zero(self) -> None:
        answer = {
            "answers": {
                "decision": {"type": "choice", "choice": "authorized"},
                "contained": {"type": "noul", "noul": 0.1},
                "objection": {"type": "choice", "choice": "permitted"},
            }
        }
        with _jev(_sequence_client(answer)):
            result = await ask_jev(
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
            )

        assert result == (
            JevVerdict(
                choice="authorized",
                confidence=0.0,
                probabilities={},
                contained=0.1,
                objection=0.0,
            ),
            0,
            0,
        )


class TestOneRequestCarriesEveryQuestion:
    """A gated call costs one Decisions request, however many questions it needs."""

    async def _posted(
        self,
        *,
        shown: tuple[str, ...] = (),
        rules: tuple[str, ...] = (),
        answer: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], AsyncMock]:
        client = _sequence_client(answer or _answer("unclear", 0.5, go_ahead=_NOT_A_GO_AHEAD))
        with _jev(client):
            await JevIntentJudge().decide(
                auto=AutoContext(user_id="u", standing_rules=rules),
                user_messages=["draft it", "send it"],
                call=_call(),
                prior_calls=[],
                assistant=intent.AssistantTurns(shown=shown),
            )
        return client.post.await_args.kwargs["json"], client

    @pytest.mark.regression
    async def test_a_call_with_nothing_shown_asks_the_decision_contained_and_objection_questions(
        self,
    ) -> None:
        posted, client = await self._posted(answer=_answer("unclear", 0.5))

        assert client.post.await_count == 1
        assert list(posted["questions"]) == [
            hil_constants.JEV_DECISION_QUESTION_KEY,
            hil_constants.JEV_CONTAINED_QUESTION_KEY,
            hil_constants.JEV_OBJECTION_QUESTION_KEY,
        ]
        assert posted["questions"][hil_constants.JEV_OBJECTION_QUESTION_KEY] == (
            prompts.JEV_OBJECTION_QUESTION
        )
        assert "assistant_turns" not in posted["state"]
        assert "standing_instructions" not in posted["state"]

    @pytest.mark.regression
    async def test_the_go_ahead_question_rides_along_only_when_the_user_was_shown_a_reply(
        self,
    ) -> None:
        posted, client = await self._posted(shown=("Your draft is ready. Reply YES to send.",))

        assert client.post.await_count == 1
        assert posted["questions"][hil_constants.JEV_GO_AHEAD_QUESTION_KEY] == (
            prompts.JEV_GO_AHEAD_QUESTION
        )
        assert posted["state"]["assistant_turns"] == ["Your draft is ready. Reply YES to send."]

    @pytest.mark.regression
    async def test_saved_instructions_ride_in_the_state_only_when_they_reach_the_call(
        self,
    ) -> None:
        rules = ("Always ask me before emailing my boss.", "Reply in English.")

        posted, client = await self._posted(rules=rules)

        assert client.post.await_count == 1
        assert posted["state"]["standing_instructions"] == list(rules)

    async def test_the_users_turns_and_the_runs_messages_share_one_state(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5, go_ahead=_NOT_A_GO_AHEAD))
        with _jev(client):
            await JevIntentJudge().decide(
                auto=AutoContext(user_id="u"),
                user_messages=["draft it", "send it"],
                call=_call(),
                prior_calls=[PriorCall(name="FIND", args={})],
                assistant=intent.AssistantTurns(
                    shown=("Drafted the reply to Simonne.",), run=("Prepared a reply to Bob.",)
                ),
            )

        state = client.post.await_args.kwargs["json"]["state"]
        assert state["user_messages"] == ["draft it", "send it"]
        assert state["assistant_turns"] == ["Drafted the reply to Simonne."]
        assert state["run_messages"] == ["Prepared a reply to Bob."]
        assert state["prior_actions"] == [{"tool": "FIND", "args": {}}]

    async def test_words_that_look_like_holds_never_cost_a_second_request(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9))
        with _jev(client):
            await JevIntentJudge().decide(
                auto=AutoContext(user_id="u"),
                user_messages=FORBID_TURNS,
                call=_call(),
                prior_calls=[],
            )

        assert client.post.await_count == 1


class TestTheAnswersBecomeAVerdict:
    async def _verdict(self, answer: dict[str, Any], *, shown: bool = False) -> JevVerdict:
        assistant = intent.AssistantTurns(shown=("Your draft is ready.",) if shown else ())
        with _jev(_sequence_client(answer)):
            verdict, _in, _out = await ask_jev(
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                auto=AutoContext(user_id="u"),
                assistant=assistant,
            )
        return verdict

    @pytest.mark.parametrize(
        ("objection", "expected"),
        [
            (("permitted", 0.9), 0.9),
            (("forbidden", 0.8), 0.2),
            (("permitted", None), 0.0),
            (("forbidden", None), 0.0),
        ],
        ids=["permitted", "forbidden", "permitted-unsure-of-itself", "forbidden-unsure-of-itself"],
    )
    async def test_objection_is_the_probability_nothing_objects(
        self, objection: tuple[str, float | None], expected: float
    ) -> None:
        verdict = await self._verdict(_answer("authorized", 0.9, objection=objection))

        assert verdict.objection == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("go_ahead", "expected"),
        [
            (("authorized", 0.9), 0.9),
            (("unclear", 0.2), 0.8),
            (("authorized", None), 0.0),
            (("unclear", None), 0.0),
        ],
        ids=[
            "authorized",
            "unclear",
            "authorized-without-confidence",
            "unclear-without-confidence",
        ],
    )
    async def test_go_ahead_is_the_probability_the_reply_approves_this_call(
        self, go_ahead: tuple[str, float | None], expected: float
    ) -> None:
        """No probability to read never counts as a go-ahead: "0% unclear" must not read as a sure yes."""
        verdict = await self._verdict(_answer("unclear", 0.5, go_ahead=go_ahead), shown=True)

        assert verdict.go_ahead == pytest.approx(expected)

    async def test_go_ahead_is_absent_when_the_question_was_not_asked(self) -> None:
        verdict = await self._verdict(_answer("unclear", 0.5, go_ahead=("authorized", 0.9)))

        assert verdict.go_ahead is None

    async def test_an_objection_choice_the_question_never_offered_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match=r"^unknown JEV objection choice: 'authorized'$"):
            await self._verdict(_answer("unclear", 0.5, objection=("authorized", 0.9)))

    async def test_a_go_ahead_choice_the_question_never_offered_is_refused_by_name(self) -> None:
        with pytest.raises(ValueError, match=r"^unknown JEV go-ahead choice: 'forbidden'$"):
            await self._verdict(_answer("unclear", 0.5, go_ahead=("forbidden", 0.9)), shown=True)

    async def test_a_missing_objection_answer_is_refused(self) -> None:
        with pytest.raises(ValueError, match="objection answer missing"):
            await self._verdict(_answer("authorized", 0.9, objection=None))

    async def test_a_missing_go_ahead_answer_is_refused_when_it_was_asked(self) -> None:
        with pytest.raises(ValueError, match="go-ahead answer missing"):
            await self._verdict(_answer("unclear", 0.5), shown=True)


class TestTheJudgeAroundTheWire:
    async def test_a_failed_request_asks(self) -> None:
        client = _sequence_client(httpx.ConnectError("down"))
        with _jev(client):
            decision = await judge_intent(
                AutoContext(user_id="u"),
                user_messages=FORBID_TURNS,
                call=_call(),
                prior_calls=[],
                judge=JevIntentJudge(),
            )

        assert decision.outcome == "ask"
        assert client.post.await_count == 1

    async def test_an_answer_without_the_objection_asks(self) -> None:
        with _jev(_sequence_client(_answer("authorized", 0.9, objection=None))):
            decision = await judge_intent(
                AutoContext(user_id="u"),
                user_messages=["draft an email to bob@example.com about the deck"],
                call=_call(),
                prior_calls=[],
                judge=JevIntentJudge(),
            )

        assert decision.outcome == "ask"

    async def test_nothing_objecting_to_an_authorized_call_accepts(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9))
        with _jev(client):
            decision = await JevIntentJudge().decide(
                auto=AutoContext(user_id="u"),
                user_messages=["draft an email to bob@example.com about the deck"],
                call=_call(),
                prior_calls=[],
            )

        assert decision == IntentDecision(
            "accept", "Auto mode matched this to your request (authorized 0.90)."
        )
        assert client.post.await_count == 1


class TestNoWordListSecondGuessesTheUser:
    """JEV reads the user's words; code never matches them against a list of "forbid" or "hold" words."""

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "approval",
        [
            "yes send it, no need to wait for my ok",
            "don't wait, just send it",
            "send it, never ask me for this again",
        ],
    )
    async def test_an_approval_that_sounds_like_a_hold_runs_when_nothing_objects(
        self, approval: str
    ) -> None:
        """These carried words ("wait", "don't", "never") that a regex read as a forbid or a hold."""
        with _jev(_sequence_client(_answer("authorized", 0.9))):
            decision = await JevIntentJudge().decide(
                auto=AutoContext(user_id="u"),
                user_messages=["draft an email to bob@example.com about the deck", approval],
                call=_call(),
                prior_calls=[],
            )

        assert decision.outcome == "accept"

    @pytest.mark.regression
    @pytest.mark.parametrize(
        "hold",
        [
            "I'd rather approve anything that leaves my account myself",
            "run anything outbound past me",
            "let me look at it before it goes",
        ],
    )
    async def test_a_hold_no_word_list_knew_asks_when_jev_reports_the_objection(
        self, hold: str
    ) -> None:
        with _jev(_sequence_client(_answer("authorized", 0.9, objection=("forbidden", 0.9)))):
            decision = await JevIntentJudge().decide(
                auto=AutoContext(user_id="u"),
                user_messages=[hold, "email bob@example.com the deck"],
                call=_call(),
                prior_calls=[],
            )

        assert decision == IntentDecision(
            "ask", "something you said or saved argues against this send_email call."
        )


class TestSavedInstructionsOnlyEverAddAsks:
    """Instructions reach the one question; they can stop a call, and never let one run."""

    RULES = ("Always ask me before emailing my boss.",)

    async def _decide(self, answer: dict[str, Any], rules: tuple[str, ...]) -> IntentDecision:
        with _jev(_sequence_client(answer)):
            return await JevIntentJudge().decide(
                auto=AutoContext(user_id="u", standing_rules=rules),
                user_messages=["draft an email to bob@example.com about the deck"],
                call=_call(),
                prior_calls=[],
            )

    @pytest.mark.regression
    async def test_an_instruction_that_covers_the_call_makes_it_ask(self) -> None:
        answer = _answer("authorized", 0.95, objection=("forbidden", 0.9))

        decision = await self._decide(answer, self.RULES)

        assert decision == IntentDecision(
            "ask", "something you said or saved argues against this send_email call."
        )

    async def test_an_instruction_that_does_not_cover_it_changes_nothing(self) -> None:
        answer = _answer("authorized", 0.95)

        assert await self._decide(answer, self.RULES) == await self._decide(answer, ())

    async def test_an_instruction_never_lets_a_call_the_user_did_not_ask_for_run(self) -> None:
        answer = _answer("unclear", 0.4, contained=0.05)

        decision = await self._decide(answer, self.RULES)

        assert decision.outcome == "ask"
        assert decision == await self._decide(answer, ())


def _transport(*bodies: dict[str, Any]) -> AsyncMock:
    return AsyncMock(side_effect=[JevDecisionsResponse.model_validate(body) for body in bodies])


_FULL_PROBS = {"unclear": 0.6, "authorized": 0.4, "forbidden": 0.0}


class TestAContainedCallRunsOnTheOneRequest:
    async def test_the_judge_asks_the_transport_it_was_given_once(self) -> None:
        transport = _transport(_answer("unclear", 0.6, _FULL_PROBS, contained=0.95))

        decision = await JevIntentJudge(transport=transport).decide(
            auto=AutoContext(user_id="u"),
            user_messages=["don't worry about the formatting", "tidy my notes page"],
            call=_call(tool_name="NOTION_INSERT_MARKDOWN", args={"page_id": "p1"}),
            prior_calls=[],
        )

        assert transport.await_count == 1
        assert decision == IntentDecision(
            "accept",
            "Auto mode ran this: it stays in your account and can be undone (contained 0.95).",
        )


def _verdict(
    choice: str = "unclear",
    confidence: float = 0.6,
    contained: float | None = 0.95,
    objection: float | None = 0.95,
    go_ahead: float | None = None,
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
        objection=objection,
        go_ahead=go_ahead,
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
                objection=0.95,
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
            JevVerdict(
                choice="unclear", confidence=0.6, probabilities={}, contained=0.95, objection=0.95
            ),
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

    @pytest.mark.regression
    async def test_casual_words_that_look_like_a_forbid_do_not_hold_a_contained_call(self) -> None:
        """Prod 2026-11: "can't"/"never" in ordinary chat tripped 26 of 61 real asked calls."""
        turns = ["for MCP we can't generate a link?", "ok check the flags in posthog"]

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


#: A draft made earlier in the conversation, as the executor's thread still holds it.
_DRAFTED = PriorCall(
    name="GMAIL_CREATE_EMAIL_DRAFT",
    args={"recipient_email": "uzair@x.com", "subject": "Thursday confirmation"},
    output='{"id": "r-778"}',
)
_SEND_DRAFT = {"tool_name": "GMAIL_SEND_DRAFT", "args": {"draft_id": "r-778"}}
_SHOWN = ("The confirmation draft to Uzair is ready. Reply YES to send it.",)


def _go_ahead_case(
    verdict: JevVerdict,
    *,
    turns: list[str] | None = None,
    prior: list[PriorCall] | None = None,
    history: AutoHistory | None = None,
) -> IntentDecision:
    return decide_from_verdict(
        verdict,
        JevCase(
            call=_call(**_SEND_DRAFT),
            user_messages=turns or ["send"],
            prior_calls=[_DRAFTED] if prior is None else prior,
            history=history or AutoHistory(),
            shown_turns=_SHOWN,
        ),
    )


def _unsure(go_ahead: float | None, objection: float | None = 0.95) -> JevVerdict:
    """Build a verdict the decision question left under the line, so the go-ahead decides."""
    return _verdict(
        choice="authorized", confidence=0.7, contained=0.02, objection=objection, go_ahead=go_ahead
    )


class TestAnObjectionStopsEveryWayACallRuns:
    """A call runs unasked only when nothing objects, whichever path would have run it."""

    PATHS = ("authorized", "contained", "go-ahead")

    @staticmethod
    def _verdict(path: str, objection: float | None) -> JevVerdict:
        """Build the verdict that would run the call by this path, with this objection."""
        verdicts = {
            "authorized": _verdict(choice="authorized", confidence=0.95, contained=0.02),
            "contained": _verdict(choice="unclear", confidence=0.4, contained=0.95),
            "go-ahead": _unsure(0.95),
        }
        return replace(verdicts[path], objection=objection)

    @pytest.mark.parametrize("path", PATHS)
    async def test_each_path_runs_when_nothing_objects(self, path: str) -> None:
        verdict = self._verdict(path, 1.0)

        assert _go_ahead_case(verdict).outcome == "accept"

    @pytest.mark.regression
    @pytest.mark.parametrize("path", PATHS)
    async def test_a_confident_objection_blocks_it(self, path: str) -> None:
        verdict = self._verdict(path, 0.05)

        assert _go_ahead_case(verdict) == IntentDecision(
            "ask", "something you said or saved argues against this GMAIL_SEND_DRAFT call."
        )

    @pytest.mark.parametrize("path", PATHS)
    async def test_an_unsure_objection_under_the_floor_blocks_it(self, path: str) -> None:
        verdict = self._verdict(path, hil_constants.HIL_JEV_OBJECTION_FLOOR - 0.01)

        assert _go_ahead_case(verdict).outcome == "ask"

    @pytest.mark.parametrize("path", PATHS)
    async def test_an_objection_exactly_at_the_floor_clears_it(self, path: str) -> None:
        verdict = self._verdict(path, hil_constants.HIL_JEV_OBJECTION_FLOOR)

        assert _go_ahead_case(verdict).outcome == "accept"

    @pytest.mark.parametrize("path", PATHS)
    async def test_no_objection_answer_blocks_it(self, path: str) -> None:
        """A journal from before the question can't show nothing objects, so it never runs unasked."""
        assert _go_ahead_case(self._verdict(path, None)).outcome == "ask"

    async def test_a_forbidden_choice_blocks_it_whatever_the_probabilities_say(self) -> None:
        verdict = replace(
            self._verdict("contained", 0.95),
            choice="forbidden",
            confidence=0.9,
            probabilities={"forbidden": 0.0},
        )

        assert _go_ahead_case(verdict).outcome == "ask"

    async def test_a_confident_objection_with_a_confident_authorized_asks(self) -> None:
        verdict = _verdict(choice="authorized", confidence=0.99, contained=0.99, objection=0.01)

        assert _go_ahead_case(verdict).outcome == "ask"


class TestAConfirmationOfWhatTheUserWasShown:
    _LISTING = (
        "Visible drafts (id | to | subject | gist):\n"
        '1. r2569937965309608501 | boardy@x.com | "Intro" | intro\n'
        '2. r8807310570127663349 | simonne@intrinsicurlyme.co.za | "Re: October Invoice" | pdf'
    )

    @pytest.mark.regression
    async def test_send_after_the_drafted_reply_was_described_runs(self) -> None:
        """Prod 2026-11-15: JEV said authorized 0.92, the list-pick backstop still asked."""
        transport = _transport(_answer("authorized", 0.92, go_ahead=_NOT_A_GO_AHEAD))

        decision = await JevIntentJudge(transport=transport).decide(
            auto=AutoContext(user_id="u"),
            user_messages=["Send"],
            call=_call(tool_name="GMAIL_SEND_DRAFT", args={"draft_id": "r8807310570127663349"}),
            prior_calls=[PriorCall(name="GMAIL_LIST_DRAFTS", args={}, output=self._LISTING)],
            assistant=intent.AssistantTurns(
                shown=("I drafted the reply to Simonne with the October invoice attached.",)
            ),
        )

        assert decision.outcome == "accept"

    async def test_only_what_the_user_saw_grounds_the_pick(self) -> None:
        """The judge's context may hold a run's internal messages; they never ground a pick."""
        transport = _transport(_answer("authorized", 0.92))

        decision = await JevIntentJudge(transport=transport).decide(
            auto=AutoContext(user_id="u"),
            user_messages=["Send"],
            call=_call(tool_name="GMAIL_SEND_DRAFT", args={"draft_id": "r8807310570127663349"}),
            prior_calls=[PriorCall(name="GMAIL_LIST_DRAFTS", args={}, output=self._LISTING)],
            assistant=intent.AssistantTurns(run=("Picked the draft for simonne.",)),
        )

        assert decision.outcome == "ask"


class TestAGoAheadForWhatTheRunIsDoing:
    """'Send' after a shown draft runs when JEV, seeing the recent calls, says it is that draft."""

    def test_a_confident_go_ahead_on_a_grounded_call_runs(self) -> None:
        decision = _go_ahead_case(_unsure(0.95))
        assert decision.outcome == "accept"
        assert decision.reason.startswith(intent.GO_AHEAD_RUN_REASON)

    def test_an_unsure_go_ahead_asks(self) -> None:
        line = hil_constants.HIL_JEV_GO_AHEAD_LINE
        assert _go_ahead_case(_unsure(line - 0.01)).outcome == "ask"

    def test_no_go_ahead_answer_asks(self) -> None:
        assert _go_ahead_case(_unsure(None)).outcome == "ask"

    def test_nothing_shown_to_the_user_means_no_go_ahead(self) -> None:
        """'share that doc with dan' scored 0.98: with no proposal shown, it is not a reply."""
        case = JevCase(
            call=_call(**_SEND_DRAFT),
            user_messages=["send"],
            prior_calls=[_DRAFTED],
            history=AutoHistory(),
        )
        assert decide_from_verdict(_unsure(0.98), case).outcome == "ask"

    def test_a_draft_nothing_this_conversation_made_asks(self) -> None:
        assert _go_ahead_case(_unsure(0.95), prior=[]).outcome == "ask"

    def test_a_recent_denial_still_asks(self) -> None:
        history = AutoHistory(approved_recent=3, denied_recent=1)
        assert _go_ahead_case(_unsure(0.95), history=history).outcome == "ask"

    async def test_one_request_answers_the_go_ahead_and_the_call_runs(self) -> None:
        transport = _transport(
            _answer(
                "authorized",
                0.7,
                {"authorized": 0.7, "unclear": 0.3, "forbidden": 0.0},
                go_ahead=("authorized", 0.95),
            )
        )
        decision = await JevIntentJudge(transport=transport).decide(
            auto=AutoContext(user_id="u"),
            user_messages=["draft the confirmation to uzair", "send"],
            call=_call(**_SEND_DRAFT),
            prior_calls=[_DRAFTED],
            assistant=intent.AssistantTurns(shown=_SHOWN),
        )

        assert decision.outcome == "accept"
        assert decision.reason.startswith(intent.GO_AHEAD_RUN_REASON)
        assert transport.await_count == 1
        state, questions = transport.await_args.args
        assert questions[hil_constants.JEV_GO_AHEAD_QUESTION_KEY] == prompts.JEV_GO_AHEAD_QUESTION
        assert state["user_messages"] == ["draft the confirmation to uzair", "send"]
        assert state["assistant_turns"] == list(_SHOWN)
        assert state["prior_actions"] == [
            {"tool": "GMAIL_CREATE_EMAIL_DRAFT", "args": _DRAFTED.args, "output": _DRAFTED.output}
        ]

    async def test_a_failed_request_asks(self) -> None:
        transport = AsyncMock(side_effect=httpx.ConnectError("down"))
        decision = await judge_intent(
            AutoContext(user_id="u"),
            user_messages=["send"],
            call=_call(**_SEND_DRAFT),
            prior_calls=[_DRAFTED],
            judge=JevIntentJudge(transport=transport),
            assistant=intent.AssistantTurns(shown=_SHOWN),
        )
        assert decision.outcome == "ask"


def _verdict_case(
    args: dict[str, object], turns: list[str], history: AutoHistory | None = None
) -> IntentDecision:
    return decide_from_verdict(
        JevVerdict(
            choice="authorized",
            confidence=0.9,
            probabilities={"authorized": 0.9, "forbidden": 0.0},
            objection=0.95,
        ),
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


class TestARunOnAGoAheadStopsAtTheLine:
    def test_a_go_ahead_exactly_on_the_line_runs(self) -> None:
        assert _go_ahead_case(_unsure(hil_constants.HIL_JEV_GO_AHEAD_LINE)).outcome == "accept"

    def test_an_address_from_the_users_past_runs_is_not_an_untraced_target(self) -> None:
        case = JevCase(
            call=_call(),
            user_messages=["send"],
            prior_calls=[],
            history=AutoHistory(known_targets=("bob@example.com",)),
            shown_turns=_SHOWN,
        )

        assert decide_from_verdict(_unsure(0.95), case).outcome == "accept"

    def test_a_pick_from_a_list_is_grounded_by_what_the_user_was_shown(self) -> None:
        listing = (
            '1. r2569937965309608501 | boardy@x.com | "Intro"\n'
            '2. r8807310570127663349 | simonne@intrinsicurlyme.co.za | "Re: October Invoice"'
        )
        case = JevCase(
            call=_call(tool_name="GMAIL_SEND_DRAFT", args={"draft_id": "r8807310570127663349"}),
            user_messages=["Send"],
            prior_calls=[PriorCall(name="GMAIL_LIST_DRAFTS", args={}, output=listing)],
            history=AutoHistory(),
            shown_turns=("I drafted the reply to Simonne with the October invoice attached.",),
        )

        assert decide_from_verdict(_unsure(0.95), case).outcome == "accept"
