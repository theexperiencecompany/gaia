"""JEV choice judge for auto mode (app/services/hil/intent.py's other half).

One Decisions API call returns authorized / forbidden / unclear with a calibrated
confidence, plus how contained the call's effect is; code maps both to accept / ask
and applies the checks a classifier must never grade itself on (target grounding,
history, the user's holds and forbids). A failed Decisions call raises, and
judge_intent leaves the call to the user.

Question text lives in prompts.py; thresholds in constants/hil.py. Both are tuned
through the hil-judge calibration suite, never by hand here.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
import re

from app.constants.hil import (
    HIL_JEV_ACCEPT_LINE,
    HIL_JEV_CONTAINED_LINE,
    HIL_JEV_CONTAINED_MAX_FORBIDDEN,
    HIL_JEV_FORBID_FLOOR,
    HIL_JEV_GO_AHEAD_LINE,
    HIL_JEV_JUDGE_MODEL_NAME,
    JEV_CONTAINED_QUESTION_KEY,
    JEV_DECISION_QUESTION_KEY,
    JEV_FORBID_CHECK_FAILED,
    JEV_FORBID_QUESTION_KEY,
    JEV_GO_AHEAD_QUESTION_KEY,
    JEV_STANDING_QUESTION_KEY,
    JevChoice,
)
from app.constants.log_tags import LogTag
from app.models.jev_models import JevDecisionsResponse
from app.services.hil.intent import (
    CONTAINED_RUN_REASON,
    GO_AHEAD_RUN_REASON,
    AssistantTurns,
    AutoHistory,
    AutoOutcome,
    IntentDecision,
    JudgedCall,
    _history_blocks,
    history_line,
    ungrounded_targets,
)
from app.services.hil.jev_client import post_decisions
from app.services.hil.prompts import (
    JEV_CONTAINED_QUESTION,
    JEV_FORBID_QUESTION,
    JEV_GO_AHEAD_QUESTION,
    JEV_QUESTION,
    JEV_QUESTIONS_VERSION,
    JEV_STANDING_QUESTION,
)
from app.services.hil.utils import PriorCall
from shared.py.wide_events import log


def map_jev_choice(choice: str, confidence: float, *, accept_line: float) -> AutoOutcome:
    """JEV verdict to gate outcome: only a confident authorized runs, everything else asks."""
    if choice == JevChoice.AUTHORIZED and confidence >= accept_line:
        return "accept"
    return "ask"


#: Forbid tripwire on the accept path: crisp prohibitions, not moods.
#: Temporary boundaries ask on merits; these claim the act itself is off limits.
#: Bare "no" absent — "no, send it" lifts, not forbids; so is "never mind".
_FORBID_PATTERNS = (
    r"\bnever\b(?!\s+mind\b)",
    r"\bdon'?t\b",
    r"\bdo not\b",
    r"\bdoesn'?t\b",
    r"\bcan'?t\b",
    r"\bcannot\b",
    r"\bwon'?t\b",
    r"\bcancel that\b",
    r"\bforbid",
    r"\bprohibit",
    r"\bkeep\b.{0,24}\bprivate\b",
    r"\bkeep (everything|all)\b",
    r"\bhold (everything|all)\b",
    r"\bdon'?t touch\b",
)

#: A later turn lifts a forbid only when it opens with the lift ("actually, go ahead and
#: send"), so a lift word inside another request ("actually, can you also summarize it")
#: lifts nothing. Searched only AFTER the forbid turn.
_LIFT_OPENING = r"^\W*((actually|ok(ay)?|yes|yeah)\W+)*"
_LIFT_PATTERNS = tuple(
    f"{_LIFT_OPENING}{phrase}\\b"
    for phrase in (
        r"go ahead",
        r"never ?mind",
        r"do it( now)?",
        r"proceed",
        r"override",
        r"ignore (that|my last|the last)",
        r"change of plans",
        r"on second thought",
    )
)

#: A hold the user put on acting at all. Not a forbid (an authorized call is still
#: judged on its merits), but it stops a contained call running without their go-ahead.
_HOLD_PATTERNS = (
    r"\bnot yet\b",
    r"\bhold off\b",
    r"\bhold on\b",
    r"\bwait before\b",
    r"\bcheck with me\b",
    r"\bask me (first|before)\b",
    r"\buntil i (say|confirm)\b",
    r"\bwait (for|until|till) (my|i)\b",
    r"\b(need|needs|get) my (approval|ok|okay|go-?ahead|sign-?off)\b",
    r"\b(don'?t|do not)\b[^.!?]{0,60}\byet\b",
)

#: Only a turn that is nothing but a go-ahead lifts a hold: "go ahead and summarize the
#: page" approves the summary, not the action the user held.
_HOLD_LIFT_PATTERNS = (
    r"^\W*(ok(ay)?\W+)?(yes\W+)?(go ahead|do it( now)?|proceed|you can (go ahead|proceed|do it))\W*$",
)


def carries_forbid_language(user_messages: list[str]) -> bool:
    """Whether any turn carries forbid words, lifted or not.

    A lift is a regex guess at the user's meaning, so it never clears forbid words on its
    own where only the focused check can (a contained or go-ahead run).
    """
    return any(_matches_any(turn, _FORBID_PATTERNS) for turn in user_messages)


def forbid_tripwire(user_messages: list[str]) -> bool:
    """Whether an earlier turn forbids with no later lift; the call then cannot run unasked.

    A tripwire, not a verdict: whether the forbid covers this call is the focused
    JEV question's judgment (forbid_verdict).
    """
    return _unlifted(user_messages, _FORBID_PATTERNS, _LIFT_PATTERNS)


def user_held_or_denied(user_messages: list[str], history: AutoHistory) -> bool:
    """Whether an unlifted hold or any recent denial asks for the user's go-ahead first.

    Stricter than _history_blocks on purpose: a call the user's words don't authorize
    runs on containment alone, so even one recent "no" to this tool keeps it asking.
    """
    return (
        _unlifted(user_messages, _HOLD_PATTERNS, _HOLD_LIFT_PATTERNS) or history.denied_recent > 0
    )


def _unlifted(user_messages: list[str], patterns: tuple[str, ...], lifts: tuple[str, ...]) -> bool:
    """Whether some turn matches patterns and no later turn carries one of the lifts."""
    for index, turn in enumerate(user_messages):
        if _matches_any(turn, patterns) and not any(
            _matches_any(later, lifts) for later in user_messages[index + 1 :]
        ):
            return True
    return False


def _matches_any(turn: str, patterns: tuple[str, ...]) -> bool:
    lowered = turn.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


#: Sends one Decisions request (state + named questions) and parses its answers.
DecisionsTransport = Callable[
    [Mapping[str, object], Mapping[str, Mapping[str, object]]], Awaitable[JevDecisionsResponse]
]

#: The judge's prod transport: JEV on the model its lines were tuned on.
JUDGE_TRANSPORT: DecisionsTransport = partial(post_decisions, model=HIL_JEV_JUDGE_MODEL_NAME)


async def ask_jev(
    *,
    user_messages: list[str],
    call: JudgedCall,
    prior_calls: list[PriorCall],
    history: AutoHistory,
    assistant: AssistantTurns = AssistantTurns(),
    transport: DecisionsTransport = JUDGE_TRANSPORT,
) -> tuple["JevVerdict", int, int]:
    """One Decisions call: the verdict (authorization choice + containment) and (in, out) tokens.

    Raises on transport failure or a malformed answer; the caller asks the user.
    """
    pending_action: dict[str, object] = {
        "tool": call.tool_name,
        "description": call.description,
        "summary": call.summary,
        "args": call.args,
    }
    # Enrichment rides only when it exists: empty evidence reads as missing
    # evidence and costs confidence, so an old-shape call posts the old-shape
    # state byte for byte.
    if call.tool_schema:
        pending_action["tool_schema"] = call.tool_schema
    state = {
        "user_messages": user_messages,
        "pending_action": pending_action,
        "prior_actions": _prior_actions(prior_calls),
        "recent_history": history_line(history, call.tool_name),
        "now": datetime.now(UTC).isoformat(),
    }
    if assistant.shown:
        state["assistant_turns"] = assistant.recent_shown()
    if assistant.run:
        state["run_messages"] = assistant.recent_run()
    body = await transport(
        state,
        {
            JEV_DECISION_QUESTION_KEY: JEV_QUESTION,
            JEV_CONTAINED_QUESTION_KEY: JEV_CONTAINED_QUESTION,
        },
    )
    answer = body.choice(
        JEV_DECISION_QUESTION_KEY, (JevChoice.AUTHORIZED, JevChoice.FORBIDDEN, JevChoice.UNCLEAR)
    )
    verdict = JevVerdict(
        choice=answer.choice,
        confidence=float(answer.confidence or 0.0),
        probabilities=dict(answer.probabilities or {}),
        contained=body.noul(JEV_CONTAINED_QUESTION_KEY),
    )
    return (verdict, *body.tokens())


async def ask_jev_forbid(
    *,
    user_messages: list[str],
    call: JudgedCall,
    transport: DecisionsTransport = JUDGE_TRANSPORT,
) -> tuple[str, float, int, int]:
    """Focused forbid check: does an earlier turn forbid THIS action? (choice, confidence, in, out).

    A decomposed second opinion on forbid language, asked only when it is all that
    stands between a contained call and a run. Raises on transport failure.
    """
    state = {
        "earlier_turns": user_messages[:-1],
        "latest_turns": user_messages[-1:],
        "pending_action": {"tool": call.tool_name, "args": call.args},
    }
    body = await transport(state, {JEV_FORBID_QUESTION_KEY: JEV_FORBID_QUESTION})
    answer = body.choice(
        JEV_FORBID_QUESTION_KEY, (JevChoice.FORBIDDEN, JevChoice.PERMITTED), label="forbid "
    )
    return (answer.choice, float(answer.confidence or 0.0), *body.tokens())


def needs_forbid_check(user_messages: list[str], verdict: "JevVerdict") -> bool:
    """Whether forbid words need the focused check before the call may run.

    Pure, shared by prod and the eval. Any call JEV does not already forbid may still
    run (authorized, contained, or on a go-ahead), so forbid words with no later lift
    get a focused question instead of a blanket veto: a "don't" that forbids nothing
    ("don't we have the draft ready?") no longer stops the call.
    """
    return verdict.choice != JevChoice.FORBIDDEN and carries_forbid_language(user_messages)


async def ask_jev_go_ahead(
    *,
    user_messages: list[str],
    call: JudgedCall,
    prior_calls: list[PriorCall],
    assistant_turns: list[str],
    transport: DecisionsTransport = JUDGE_TRANSPORT,
) -> tuple[float, int, int]:
    """Focused check: is the user's reply the go-ahead for exactly this call? (P, in, out).

    Sees the run's recent calls with their outputs, so an opaque id is matched to the
    thing it names. Raises on transport failure or a malformed answer.
    """
    state: dict[str, object] = {}
    if assistant_turns:
        state["assistant_turns"] = list(assistant_turns)
    state |= {
        "latest_turns": user_messages[-2:],
        "recent_actions": _prior_actions(prior_calls),
        "pending_action": {"tool": call.tool_name, "args": call.args},
    }
    body = await transport(state, {JEV_GO_AHEAD_QUESTION_KEY: JEV_GO_AHEAD_QUESTION})
    answer = body.choice(
        JEV_GO_AHEAD_QUESTION_KEY, (JevChoice.AUTHORIZED, JevChoice.UNCLEAR), label="go-ahead "
    )
    if answer.confidence is None:
        # Nothing to read the go-ahead from: "0% unclear" would otherwise score as a sure yes.
        return (0.0, *body.tokens())
    authorized = answer.choice == JevChoice.AUTHORIZED
    go_ahead = answer.confidence if authorized else 1.0 - answer.confidence
    return (go_ahead, *body.tokens())


def _prior_actions(prior_calls: list[PriorCall]) -> list[dict[str, object]]:
    """Render the run's calls for JEV: tool, args, and the output when there is one."""
    actions: list[dict[str, object]] = []
    for prior in prior_calls:
        item: dict[str, object] = {"tool": prior.name, "args": prior.args}
        if prior.output.strip():
            item["output"] = prior.output
        actions.append(item)
    return actions


def needs_go_ahead_check(
    verdict: "JevVerdict",
    case: "JevCase",
    *,
    accept_line: float = HIL_JEV_ACCEPT_LINE,
    contained_line: float = HIL_JEV_CONTAINED_LINE,
) -> bool:
    """Whether a call that would ask gets the go-ahead question: a reply to what the user was shown.

    Pure, shared by prod and the eval. With nothing shown there is no proposal to reply
    to, and the question turns into a looser second authorization check.
    """
    would_ask = _authorization_decision(
        verdict, case, accept_line=accept_line
    ).outcome == "ask" and not _runs_contained(verdict, case, contained_line=contained_line)
    return would_ask and bool(case.shown_turns) and _nothing_objects(verdict, case)


def settle_forbid(
    choice: str, confidence: float, *, floor: float = HIL_JEV_FORBID_FLOOR
) -> JevChoice:
    """Settle a focused forbid answer: permitted only when JEV says so at the floor.

    Anything less is doubt, and doubt asks the user. Pure, shared by prod and the eval
    so the sweep regrades the rule prod runs.
    """
    if choice == JevChoice.PERMITTED and confidence >= floor:
        return JevChoice.PERMITTED
    return JevChoice.FORBIDDEN


class JevIntentJudge:
    """Auto mode classifier: JEV decides, code applies the vetoes; unclear asks the user.

    The one classifier: a failed Decisions call raises, and judge_intent leaves the call to the user.
    """

    def __init__(self, transport: DecisionsTransport = JUDGE_TRANSPORT) -> None:
        self._transport = transport

    async def decide(
        self,
        *,
        user_id: str,  # noqa: ARG002 -- IntentJudge protocol
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        history: AutoHistory,
        assistant: AssistantTurns = AssistantTurns(),
    ) -> IntentDecision:
        asked, _in, _out = await ask_jev(
            user_messages=user_messages,
            call=call,
            prior_calls=prior_calls,
            history=history,
            assistant=assistant,
            transport=self._transport,
        )
        case = JevCase(
            call=call,
            user_messages=user_messages,
            prior_calls=prior_calls,
            history=history,
            shown_turns=assistant.shown,
        )
        verdict = replace(asked, forbid=await self._forbid_verdict(asked, user_messages, call))
        if needs_go_ahead_check(verdict, case):
            verdict = replace(
                verdict, go_ahead=await self._go_ahead(case, assistant.recent_shown())
            )
        return decide_from_verdict(verdict, case)

    async def standing_rules_hold(
        self, *, standing_rules: tuple[str, ...], call: JudgedCall
    ) -> bool:
        """Whether a saved instruction forbids this call or asks to be asked first; raises on failure."""
        state = {
            "standing_instructions": list(standing_rules),
            "pending_action": {"tool": call.tool_name, "args": call.args},
        }
        body = await self._transport(state, {JEV_STANDING_QUESTION_KEY: JEV_STANDING_QUESTION})
        answer = body.choice(
            JEV_STANDING_QUESTION_KEY,
            (JevChoice.FORBIDDEN, JevChoice.PERMITTED),
            label="standing ",
        )
        verdict = settle_forbid(answer.choice, float(answer.confidence or 0.0))
        log.info(
            f"{LogTag.HIL} standing instructions check",
            tool_name=call.tool_name,
            hil={"choice": answer.choice, "holds": verdict is JevChoice.FORBIDDEN},
        )
        return verdict is JevChoice.FORBIDDEN

    async def _go_ahead(self, case: "JevCase", assistant_turns: list[str]) -> float | None:
        """Return P(the reply is the go-ahead for this call), or None when the check failed.

        A failed check leaves the call to the user, never runs it.
        """
        try:
            go_ahead, _in, _out = await ask_jev_go_ahead(
                user_messages=case.user_messages,
                call=case.call,
                prior_calls=case.prior_calls,
                assistant_turns=assistant_turns,
                transport=self._transport,
            )
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} go-ahead check failed; asking",
                tool_name=case.call.tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return None
        return go_ahead

    async def _forbid_verdict(
        self, asked: "JevVerdict", user_messages: list[str], call: JudgedCall
    ) -> str | None:
        """Return the focused forbid verdict, or None when no check is warranted.

        A failed check degrades to asking, never to a run.
        """
        if not needs_forbid_check(user_messages, asked):
            return None
        try:
            choice, confidence, _in, _out = await ask_jev_forbid(
                user_messages=user_messages, call=call, transport=self._transport
            )
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} forbid check failed; asking",
                tool_name=call.tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return JEV_FORBID_CHECK_FAILED
        log.info(
            f"{LogTag.HIL} forbid check",
            tool_name=call.tool_name,
            hil={"choice": choice, "confidence": round(confidence, 3)},
        )
        return settle_forbid(choice, confidence)


@dataclass(frozen=True)
class JevVerdict:
    """What JEV said about one call, plus the focused forbid verdict when one ran.

    contained is P(the call's effect stays with the user and can be undone); None
    when the question was not asked (a journal from before it existed).
    """

    choice: str
    confidence: float
    probabilities: Mapping[str, float] | None = None
    forbid: str | None = None
    contained: float | None = None
    # P(the user's reply is the go-ahead for exactly this call); None when not asked.
    go_ahead: float | None = None


@dataclass(frozen=True)
class JevCase:
    """What a verdict is weighed against: the call, the user's words, the run's history.

    shown_turns are the replies the user saw: they ground a pick from a list the user
    was pointed at, never authorize anything.
    """

    call: JudgedCall
    user_messages: list[str]
    prior_calls: list[PriorCall]
    history: AutoHistory
    shown_turns: tuple[str, ...] = ()


def decide_from_verdict(
    verdict: JevVerdict,
    case: JevCase,
    *,
    accept_line: float = HIL_JEV_ACCEPT_LINE,
    contained_line: float = HIL_JEV_CONTAINED_LINE,
    go_ahead_line: float = HIL_JEV_GO_AHEAD_LINE,
) -> IntentDecision:
    """Map one JEV verdict through the code vetoes. Pure, shared by prod and eval.

    A call the user's words don't clearly authorize still runs when its effect is
    contained, or when their reply is the go-ahead for exactly it, and nothing they
    said or did objects.
    """
    log.info(
        f"{LogTag.HIL} JEV judge",
        tool_name=case.call.tool_name,
        hil={
            "choice": verdict.choice,
            "confidence": round(verdict.confidence, 3),
            "contained": None if verdict.contained is None else round(verdict.contained, 3),
            "forbid": verdict.forbid,
            "go_ahead": None if verdict.go_ahead is None else round(verdict.go_ahead, 3),
            "version": JEV_QUESTIONS_VERSION,
        },
    )
    decision = _authorization_decision(verdict, case, accept_line=accept_line)
    if decision.outcome != "ask":
        return decision
    if _runs_contained(verdict, case, contained_line=contained_line):
        return IntentDecision(
            "accept", f"{CONTAINED_RUN_REASON} (contained {verdict.contained:.2f})."
        )
    if _runs_on_go_ahead(verdict, case, go_ahead_line=go_ahead_line):
        return IntentDecision("accept", f"{GO_AHEAD_RUN_REASON} (go-ahead {verdict.go_ahead:.2f}).")
    return decision


def _runs_contained(verdict: JevVerdict, case: JevCase, *, contained_line: float) -> bool:
    """Whether the call's effect is contained enough to run with nothing the user said against it."""
    return (
        verdict.contained is not None
        and verdict.contained >= contained_line
        and _nothing_objects(verdict, case)
    )


def _runs_on_go_ahead(verdict: JevVerdict, case: JevCase, *, go_ahead_line: float) -> bool:
    """Whether the user's reply is surely the go-ahead for this call, and it acts on a known thing."""
    return (
        verdict.go_ahead is not None
        and verdict.go_ahead >= go_ahead_line
        and bool(case.shown_turns)
        and _nothing_objects(verdict, case)
        and not ungrounded_targets(
            case.call.args,
            case.user_messages,
            case.prior_calls,
            frozenset(case.history.known_targets),
            shown_turns=list(case.shown_turns),
        )
    )


def _nothing_objects(verdict: JevVerdict, case: JevCase) -> bool:
    """Whether nothing JEV or the user said or did argues against running the call unasked."""
    return (
        verdict.choice != JevChoice.FORBIDDEN
        # An answer without P(forbidden) can't show the call is safe to run unasked. Equivalent
        # under mutation: any default at or above the line says so, 1.0 as much as 2.0.
        and (verdict.probabilities or {}).get(JevChoice.FORBIDDEN, 1.0)  # pragma: no mutate
        < HIL_JEV_CONTAINED_MAX_FORBIDDEN
        and (
            verdict.forbid == JevChoice.PERMITTED or not carries_forbid_language(case.user_messages)
        )
        and not user_held_or_denied(case.user_messages, case.history)
    )


def _authorization_decision(
    verdict: JevVerdict, case: JevCase, *, accept_line: float
) -> IntentDecision:
    """Whether the user's own words authorize the call, through the code vetoes."""
    choice, confidence, call = verdict.choice, verdict.confidence, case.call
    if map_jev_choice(choice, confidence, accept_line=accept_line) != "accept":
        return IntentDecision(
            "ask",
            f"this {call.tool_name} call may not match your request ({choice} {confidence:.2f}).",
        )
    if forbid_tripwire(case.user_messages) and verdict.forbid != JevChoice.PERMITTED:
        return IntentDecision(
            "ask",
            f"an earlier message argues against this {call.tool_name} call "
            "and nothing since lifted it.",
        )
    if _history_blocks(case.history):
        return IntentDecision(
            "ask",
            f"You denied {case.history.denied_recent} recent "
            f"{call.tool_name} call(s), so this one needs your "
            "go-ahead even though it looks authorized.",
        )
    missing = ungrounded_targets(
        call.args,
        case.user_messages,
        case.prior_calls,
        frozenset(case.history.known_targets),
        shown_turns=list(case.shown_turns),
    )
    if missing:
        return IntentDecision(
            "ask",
            f"the target ({', '.join(missing[:3])}) doesn't trace to your words.",
        )
    return IntentDecision(
        "accept",
        f"Auto mode matched this to your request ({choice} {confidence:.2f}).",
    )
