"""JEV choice judge (app/services/hil/jev_judge.py).

The Decisions API is mocked — the network boundary. map_jev_choice,
ungrounded_targets, and the vetoes around the verdict are the production
code under test and run for real. Every test assumes the classifier at its
most confident and asks whether the code around it still refuses.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.hil import (
    HIL_JEV_MODEL_NAME,
    HIL_JEV_REJECT_FLOOR,
    HIL_JEV_TIMEOUT_SECONDS,
    HIL_JEV_URL,
    JevChoice,
)
from app.services.hil.intent import AutoHistory, IntentDecision, JudgedCall
from app.services.hil.jev_judge import (
    JevCase,
    JevIntentJudge,
    JevVerdict,
    ask_jev,
    ask_jev_forbid,
    decide_from_verdict,
    decisive_forbidden,
    forbid_tripwire,
    map_jev_choice,
    needs_forbid_check,
    settle_forbid,
    ungrounded_targets,
)
from app.services.hil.prompts import JEV_FORBID_QUESTION
from app.services.hil.utils import PriorCall

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
    choice: str, confidence: float, probs: dict[str, float] | None = None
) -> dict[str, Any]:
    return {
        "answers": {
            "decision": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": probs if probs is not None else {choice: confidence},
            }
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


def _client(answer: dict[str, Any] | Exception) -> AsyncMock:
    """Fake httpx.AsyncClient serving one Decisions answer (or raising)."""
    response = MagicMock()
    response.json.return_value = answer
    client = AsyncMock()
    client.__aenter__.return_value = client
    if isinstance(answer, Exception):
        client.post.side_effect = answer
    else:
        client.post.return_value = response
    return client


async def _decide(
    answer: dict[str, Any] | Exception,
    call: JudgedCall | None = None,
    history: AutoHistory | None = None,
    fallback: Any = None,
) -> IntentDecision:
    judge = JevIntentJudge(
        fallback=fallback
        if fallback is not None
        else AsyncMock(
            **{"decide.return_value": None},
        ),
    )
    with patch(f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=_client(answer)):
        with patch(f"{CLIENT_MODULE}.settings") as settings:
            settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
            return await judge.decide(
                user_id="u",
                user_messages=["draft an email to bob@example.com about the deck"],
                call=call or _call(),
                prior_calls=[],
                history=history or AutoHistory(),
            )


class TestMapping:
    async def test_confident_authorized_is_accept(self) -> None:
        assert map_jev_choice("authorized", 0.9, accept_line=0.5, reject_floor=0.5) == "accept"

    async def test_below_line_authorized_is_ask_not_accept(self) -> None:
        # Confidence lines are load-bearing: a 0.49 authorized must not run.
        assert map_jev_choice("authorized", 0.49, accept_line=0.5, reject_floor=0.5) == "ask"

    async def test_forbidden_needs_its_own_floor(self) -> None:
        assert map_jev_choice("forbidden", 0.4, accept_line=0.5, reject_floor=0.5) == "ask"
        assert map_jev_choice("forbidden", 0.6, accept_line=0.5, reject_floor=0.5) == "reject"

    async def test_unclear_is_always_ask(self) -> None:
        assert map_jev_choice("unclear", 1.0, accept_line=0.5, reject_floor=0.5) == "ask"

    async def test_unknown_choice_is_ask(self) -> None:
        assert map_jev_choice("maybe", 1.0, accept_line=0.5, reject_floor=0.5) == "ask"


class TestDecisiveForbidden:
    """A runaway forbidden wins whatever its absolute number.

    One-sided by design: over-rejecting is silent (no card), over-accepting
    runs the action — so only refusal gets the margin rule.
    """

    async def test_runaway_forbidden_rejects_below_the_floor(self) -> None:
        assert (
            decisive_forbidden("forbidden", {"forbidden": 0.48, "unclear": 0.06, "authorized": 0.0})
            is True
        )

    async def test_close_race_does_not_reject(self) -> None:
        assert (
            decisive_forbidden(
                "forbidden", {"forbidden": 0.48, "unclear": 0.40, "authorized": 0.12}
            )
            is False
        )

    async def test_just_under_the_margin_does_not_reject(self) -> None:
        # 0.37 margin: the journal band where temporary-boundary asks
        # (bg-boundary, r-hold) sit — the margin must clear them.
        assert (
            decisive_forbidden("forbidden", {"forbidden": 0.43, "unclear": 0.06, "authorized": 0.0})
            is False
        )

    async def test_margin_never_accepts(self) -> None:
        # The accept side keeps its absolute line plus grounding, always.
        assert (
            decisive_forbidden("authorized", {"authorized": 0.9, "unclear": 0.05, "forbidden": 0.0})
            is False
        )

    async def test_empty_probabilities_do_not_reject(self) -> None:
        assert decisive_forbidden("forbidden", {}) is False

    async def test_decisive_forbidden_rejects_through_decide(self) -> None:
        d = await _decide(
            _answer(
                "forbidden",
                0.22,
                {"forbidden": 0.50, "unclear": 0.06, "authorized": 0.0},
            )
        )
        assert d.outcome == "reject"


class TestForbidTripwire:
    """The tripwire only ever downgrades an accept into a double-check."""

    async def test_forbid_without_lift_trips(self) -> None:
        assert forbid_tripwire(["keep everything for now", "delete thread t5"]) is True
        assert forbid_tripwire(["never pay anyone", "pay $10 now"]) is True

    async def test_lift_language_clears_the_tripwire(self) -> None:
        assert forbid_tripwire(["don't send anything yet", "actually, go ahead and send"]) is False

    async def test_clean_history_never_trips(self) -> None:
        assert forbid_tripwire(["draft an email to bob", "looks good, send it"]) is False

    async def test_check_runs_only_on_would_accept(self) -> None:
        assert needs_forbid_check("accept", ["never email alice", "email alice"]) is True
        assert needs_forbid_check("ask", ["never email alice", "email alice"]) is False
        assert needs_forbid_check("accept", ["send the deck"]) is False
        assert needs_forbid_check("reject", ["never email alice"]) is False

    async def test_forbidden_double_check_rejects(self) -> None:
        d = decide_from_verdict(
            JevVerdict(
                choice="authorized",
                confidence=0.9,
                probabilities={"authorized": 0.9},
                forbid="forbidden",
            ),
            JevCase(
                call=_call(),
                user_messages=["send it"],
                prior_calls=[],
                history=AutoHistory(),
            ),
        )
        assert d.outcome == "reject"

    async def test_permitted_double_check_floors_accept_to_ask(self) -> None:
        # The tripwire fired (forbid words present) but the check cleared it:
        # contradictory turns still need the human — a card, never a run.
        d = decide_from_verdict(
            JevVerdict(
                choice="authorized",
                confidence=0.9,
                probabilities={"authorized": 0.9},
                forbid="permitted",
            ),
            JevCase(
                call=_call(),
                user_messages=["don't send anything yet", "send it"],
                prior_calls=[],
                history=AutoHistory(),
            ),
        )
        assert d.outcome == "ask"
        assert "earlier message" in d.reason

    async def test_failed_double_check_floors_accept_to_ask(self) -> None:
        d = decide_from_verdict(
            JevVerdict(
                choice="authorized",
                confidence=0.9,
                probabilities={"authorized": 0.9},
                forbid="unclear-forbid",
            ),
            JevCase(
                call=_call(),
                user_messages=["don't send anything yet", "send it"],
                prior_calls=[],
                history=AutoHistory(),
            ),
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
    async def test_forbidden_is_reject_with_a_reason(self) -> None:
        d = await _decide(_answer("forbidden", 0.9))
        assert d.outcome == "reject"
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


class TestFallback:
    async def test_transport_failure_runs_the_fallback_not_an_allow(self) -> None:
        fallback = AsyncMock(**{"decide.return_value": IntentDecision("ask", "llm says ask")})
        d = await _decide(ConnectionError("down"), fallback=fallback)
        assert d.outcome == "ask"
        assert d.reason == "llm says ask"
        fallback.decide.assert_awaited_once()

    async def test_malformed_answer_runs_the_fallback(self) -> None:
        fallback = AsyncMock()
        await _decide({"answers": {}}, fallback=fallback)
        fallback.decide.assert_awaited_once()

    async def test_unknown_choice_runs_the_fallback(self) -> None:
        fallback = AsyncMock()
        await _decide(_answer("maybe", 1.0), fallback=fallback)
        fallback.decide.assert_awaited_once()

    async def test_missing_api_key_runs_the_fallback(self) -> None:
        fallback = AsyncMock()
        judge = JevIntentJudge(fallback=fallback)
        with patch(f"{CLIENT_MODULE}.settings") as settings:
            settings.OPENROUTER_API_KEY = None
            await judge.decide(
                user_id="u",
                user_messages=["send it"],
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )
        fallback.decide.assert_awaited_once()


class TestWire:
    async def test_state_names_its_evidence_fields(self) -> None:
        """The criteria reference these names; a renamed field blinds the judge."""
        client = _client(_answer("unclear", 0.5))
        with patch(f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=client):
            with patch(f"{CLIENT_MODULE}.settings") as settings:
                settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[],
                    history=AutoHistory(),
                )
        posted = client.__aenter__.return_value.post.await_args.kwargs["json"]
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
        with patch(f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=client):
            with patch(f"{CLIENT_MODULE}.settings") as settings:
                settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
                await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[PriorCall(name="FIND", args={})],
                    history=AutoHistory(),
                )
        posted = client.__aenter__.return_value.post.await_args.kwargs["json"]
        assert set(posted["state"]["pending_action"]) == {
            "tool",
            "description",
            "summary",
            "args",
        }
        assert posted["state"]["prior_actions"] == [{"tool": "FIND", "args": {}}]
        assert "assistant_turns" not in posted["state"]

        client = _client(_answer("unclear", 0.5))
        with patch(f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=client):
            with patch(f"{CLIENT_MODULE}.settings") as settings:
                settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
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
        posted = client.__aenter__.return_value.post.await_args.kwargs["json"]
        assert posted["state"]["pending_action"]["tool_schema"] == {
            "properties": {"draft_id": {"type": "string"}}
        }
        assert posted["state"]["prior_actions"] == [
            {"tool": "CREATE", "args": {}, "output": '{"draft_id": "r1"}'}
        ]
        assert posted["state"]["assistant_turns"] == ["your draft is ready"]

    async def test_usage_is_reported(self) -> None:
        with patch(
            f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=_client(_answer("unclear", 0.5))
        ):
            with patch(f"{CLIENT_MODULE}.settings") as settings:
                settings.OPENROUTER_API_KEY = "or-key"  # pragma: allowlist secret
                choice, conf, probs, tokens_in, tokens_out = await ask_jev(
                    user_messages=["send it"],
                    call=_call(),
                    prior_calls=[],
                    history=AutoHistory(),
                )
        assert (choice, conf) == ("unclear", 0.5)
        assert (tokens_in, tokens_out) == (300, 20)
        assert probs == {"unclear": 0.5}


class TestSettleForbid:
    def test_forbidden_at_the_floor_forbids(self) -> None:
        assert settle_forbid("forbidden", HIL_JEV_REJECT_FLOOR) is JevChoice.FORBIDDEN

    def test_forbidden_below_the_floor_permits(self) -> None:
        assert settle_forbid("forbidden", HIL_JEV_REJECT_FLOOR - 0.01) is JevChoice.PERMITTED

    def test_any_other_answer_permits_however_confident(self) -> None:
        """The eval once passed "unclear" through untouched; prod has always settled it to permitted."""
        assert settle_forbid("unclear", 0.99) is JevChoice.PERMITTED

    def test_the_sweep_can_move_the_floor(self) -> None:
        assert settle_forbid("forbidden", 0.6, reject_floor=0.7) is JevChoice.PERMITTED
        assert settle_forbid("forbidden", 0.6, reject_floor=0.5) is JevChoice.FORBIDDEN


def _forbid_answer(
    choice: str, confidence: float | None, usage: dict[str, int] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "answers": {"forbid": {"type": "choice", "choice": choice, "confidence": confidence}}
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _sequence_client(*answers: dict[str, Any] | Exception) -> AsyncMock:
    """Fake httpx.AsyncClient serving one answer per post, in order."""
    effects: list[Any] = []
    for answer in answers:
        if isinstance(answer, Exception):
            effects.append(answer)
        else:
            response = MagicMock()
            response.json.return_value = answer
            effects.append(response)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.side_effect = effects
    return client


@contextmanager
def _jev(client: AsyncMock, key: str | None = "or-key") -> Iterator[MagicMock]:
    """Serve client as the Decisions API with key configured; yields the AsyncClient factory."""
    with (
        patch(f"{CLIENT_MODULE}.httpx.AsyncClient", return_value=client) as factory,
        patch(f"{CLIENT_MODULE}.settings") as settings,
    ):
        settings.OPENROUTER_API_KEY = key
        yield factory


FORBID_TURNS = ["never email bob@example.com", "email bob@example.com the deck"]


class TestTheLinesAreInclusive:
    async def test_confidence_exactly_on_the_accept_line_accepts(self) -> None:
        assert map_jev_choice("authorized", 0.5, accept_line=0.5, reject_floor=0.5) == "accept"

    async def test_confidence_exactly_on_the_reject_floor_rejects(self) -> None:
        assert map_jev_choice("forbidden", 0.5, accept_line=0.5, reject_floor=0.5) == "reject"

    async def test_a_lone_forbidden_is_measured_against_nothing(self) -> None:
        assert decisive_forbidden("forbidden", {"forbidden": 0.45}) is True

    async def test_a_lead_exactly_at_the_margin_is_decisive(self) -> None:
        assert decisive_forbidden("forbidden", {"forbidden": 0.5, "unclear": 0.1}) is True


class TestTheTripwireReadsEachLaterTurn:
    async def test_a_lift_in_any_later_turn_clears_it(self) -> None:
        assert forbid_tripwire(["don't send it", "actually", "ok"]) is False

    async def test_a_lift_is_never_assembled_from_two_turns(self) -> None:
        assert forbid_tripwire(["don't send it", "go", "ahead"]) is True


class TestTheDecisionsWire:
    async def test_the_request_is_bounded_authenticated_and_names_its_model(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with _jev(client) as factory:
            await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        factory.assert_called_once_with(timeout=HIL_JEV_TIMEOUT_SECONDS)
        post = client.post.await_args
        assert post.args == (HIL_JEV_URL,)
        assert post.kwargs["headers"] == {"Authorization": "Bearer or-key"}
        posted = post.kwargs["json"]
        assert posted["model"] == HIL_JEV_MODEL_NAME
        assert posted["state"]["recent_history"] == "No recent decisions on send_email."
        assert datetime.fromisoformat(posted["state"]["now"]).tzinfo == UTC

    async def test_no_key_means_no_request(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with (
            _jev(client, key=None),
            pytest.raises(
                RuntimeError, match="^OPENROUTER_API_KEY unset; cannot reach the JEV judge$"
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
        answer = {"answers": {"decision": {"type": "choice", "choice": "authorized"}}}
        with _jev(_sequence_client(answer)):
            result = await ask_jev(
                user_messages=["send it"], call=_call(), prior_calls=[], history=AutoHistory()
            )

        assert result == ("authorized", 0.0, {}, 0, 0)


class TestTheForbidWire:
    async def test_the_focused_question_sees_earlier_and_latest_turns_apart(self) -> None:
        turns = ["never email bob", "hold on", "email bob the deck"]
        client = _sequence_client(_forbid_answer("forbidden", 0.8, {"input_tokens": 9}))
        with _jev(client) as factory:
            result = await ask_jev_forbid(user_messages=turns, call=_call())

        assert result == ("forbidden", 0.8, 9, 0)
        factory.assert_called_once_with(timeout=HIL_JEV_TIMEOUT_SECONDS)
        post = client.post.await_args
        assert post.args == (HIL_JEV_URL,)
        assert post.kwargs["headers"] == {"Authorization": "Bearer or-key"}
        assert post.kwargs["json"] == {
            "model": HIL_JEV_MODEL_NAME,
            "state": {
                "earlier_turns": ["never email bob", "hold on"],
                "latest_turns": ["email bob the deck"],
                "pending_action": {"tool": "send_email", "args": _call().args},
            },
            "questions": {"forbid": JEV_FORBID_QUESTION},
        }

    async def test_missing_confidence_and_usage_read_as_zero(self) -> None:
        with _jev(_sequence_client(_forbid_answer("permitted", None))):
            result = await ask_jev_forbid(user_messages=FORBID_TURNS, call=_call())

        assert result == ("permitted", 0.0, 0, 0)

    async def test_no_key_means_no_request(self) -> None:
        client = _sequence_client(_forbid_answer("permitted", 0.9))
        with (
            _jev(client, key=None),
            pytest.raises(
                RuntimeError, match="^OPENROUTER_API_KEY unset; cannot reach the JEV judge$"
            ),
        ):
            await ask_jev_forbid(user_messages=FORBID_TURNS, call=_call())
        client.post.assert_not_awaited()

    async def test_a_non_choice_answer_is_refused_with_a_bounded_message(self) -> None:
        answer = {"answers": {"forbid": {"type": "text", "choice": "x" * 400}}}
        with _jev(_sequence_client(answer)), pytest.raises(ValueError) as caught:
            await ask_jev_forbid(user_messages=FORBID_TURNS, call=_call())

        assert str(caught.value).startswith("non-choice JEV forbid answer: ")
        assert len(str(caught.value)) == 300

    async def test_an_unknown_choice_is_refused_by_name(self) -> None:
        with (
            _jev(_sequence_client(_forbid_answer("authorized", 0.9))),
            pytest.raises(ValueError) as caught,
        ):
            await ask_jev_forbid(user_messages=FORBID_TURNS, call=_call())

        assert str(caught.value) == "unknown JEV forbid choice: 'authorized'"


class TestTheJudgeAroundTheWire:
    async def test_the_users_and_assistants_turns_reach_jev(self) -> None:
        client = _sequence_client(_answer("unclear", 0.5))
        with _jev(client):
            await JevIntentJudge(fallback=AsyncMock()).decide(
                user_id="u",
                user_messages=["draft it", "send it"],
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
                assistant_turns=["Your draft is ready."],
            )

        state = client.post.await_args.kwargs["json"]["state"]
        assert state["user_messages"] == ["draft it", "send it"]
        assert state["assistant_turns"] == ["Your draft is ready."]

    async def test_a_failure_is_reported_and_the_fallback_gets_the_whole_call(self) -> None:
        fallback = AsyncMock(**{"decide.return_value": IntentDecision("ask", "llm")})
        prior = [PriorCall(name="FIND", args={})]
        history = AutoHistory(approved_recent=1)
        with (
            _jev(_sequence_client(ConnectionError("down"))),
            patch(f"{MODULE}.log") as log,
        ):
            decision = await JevIntentJudge(fallback=fallback).decide(
                user_id="u",
                user_messages=["send it"],
                call=_call(),
                prior_calls=prior,
                history=history,
                assistant_turns=["ready"],
            )

        assert decision == IntentDecision("ask", "llm")
        fallback.decide.assert_awaited_once_with(
            user_id="u",
            user_messages=["send it"],
            call=_call(),
            prior_calls=prior,
            history=history,
            assistant_turns=["ready"],
        )
        log.warning.assert_called_once()
        assert "JEV judge failed; falling back" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {
            "tool_name": "send_email",
            "error": "down",
            "error_type": "ConnectionError",
        }

    async def _decide_with_forbid(
        self, forbid: dict[str, Any] | Exception
    ) -> tuple[IntentDecision, AsyncMock]:
        client = _sequence_client(_answer("authorized", 0.9), forbid)
        with _jev(client):
            decision = await JevIntentJudge(fallback=AsyncMock()).decide(
                user_id="u",
                user_messages=FORBID_TURNS,
                call=_call(),
                prior_calls=[],
                history=AutoHistory(),
            )
        return decision, client

    async def test_a_confirmed_forbid_rejects_the_would_be_accept(self) -> None:
        decision, client = await self._decide_with_forbid(_forbid_answer("forbidden", 0.9))

        assert decision == IntentDecision(
            "reject",
            "Auto mode held this off: an earlier message forbids this send_email call "
            "and nothing since lifted it.",
        )
        forbid_post = client.post.await_args_list[1].kwargs["json"]
        assert forbid_post["state"]["earlier_turns"] == [FORBID_TURNS[0]]

    async def test_a_weak_forbid_floors_the_accept_to_a_card(self) -> None:
        decision, _ = await self._decide_with_forbid(_forbid_answer("forbidden", 0.3))

        assert decision == IntentDecision(
            "ask",
            "Auto mode wasn't sure: an earlier message argues against this send_email call "
            "— your call.",
        )

    async def test_a_failed_forbid_check_is_reported_and_asks(self) -> None:
        with patch(f"{MODULE}.log") as log:
            decision, _ = await self._decide_with_forbid(ConnectionError("down"))

        assert decision.outcome == "ask"
        log.warning.assert_called_once()
        assert "forbid double-check failed; asking" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs == {
            "tool_name": "send_email",
            "error": "down",
            "error_type": "ConnectionError",
        }

    async def test_no_forbid_language_skips_the_second_question(self) -> None:
        client = _sequence_client(_answer("authorized", 0.9))
        with _jev(client):
            decision = await JevIntentJudge(fallback=AsyncMock()).decide(
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
