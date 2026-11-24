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
    HIL_JEV_JUDGE_MODEL_NAME,
    JEV_CONTAINED_QUESTION_KEY,
    JEV_DECISION_QUESTION_KEY,
    JEV_FORBID_CHECK_FAILED,
    JEV_FORBID_QUESTION_KEY,
    JEV_STANDING_QUESTION_KEY,
    JevChoice,
)
from app.constants.log_tags import LogTag
from app.models.jev_models import JevDecisionsResponse
from app.services.hil.intent import (
    CONTAINED_RUN_REASON,
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
#: Bare "no" absent — "no, send it" lifts, not forbids.
_FORBID_PATTERNS = (
    r"\bnever\b",
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

#: Later-turn language that lifts a forbid. Searched only AFTER the forbid turn.
_LIFT_PATTERNS = (
    r"\bactually\b",
    r"\bgo ahead\b",
    r"\bnever mind\b",
    r"\bnevermind\b",
    r"\byes do it\b",
    r"\bdo it now\b",
    r"\boverride\b",
    r"\bignore (that|my last|the last)\b",
    r"\bchange of plans\b",
    r"\bon second thought\b",
)

#: A hold the user put on acting at all. Not a forbid (an authorized call is still
#: judged on its merits), but it stops a contained call running without their go-ahead.
_HOLD_PATTERNS = (
    r"\bnot yet\b",
    r"\bhold off\b",
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
    assistant_turns: list[str] | None = None,
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
    prior_actions = []
    for prior in prior_calls:
        item: dict[str, object] = {"tool": prior.name, "args": prior.args}
        if prior.output.strip():
            item["output"] = prior.output
        prior_actions.append(item)
    state = {
        "user_messages": user_messages,
        "pending_action": pending_action,
        "prior_actions": prior_actions,
        "recent_history": history_line(history, call.tool_name),
        "now": datetime.now(UTC).isoformat(),
    }
    if assistant_turns:
        state["assistant_turns"] = list(assistant_turns)
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


def needs_forbid_check(
    user_messages: list[str],
    *,
    contained: float | None,
    contained_line: float = HIL_JEV_CONTAINED_LINE,
) -> bool:
    """Whether a call that may run on containment needs the focused forbid check.

    Pure, shared by prod and the eval: the call clears the containment line but an
    earlier turn carries forbid language with no later lift. An authorized call with
    forbid language asks whatever the check would say, so it never needs one.
    """
    return contained is not None and contained >= contained_line and forbid_tripwire(user_messages)


def settle_forbid(
    choice: str, confidence: float, *, floor: float = HIL_JEV_FORBID_FLOOR
) -> JevChoice:
    """Settle a focused forbid answer: forbidden only at or past the floor, else permitted.

    Pure, shared by prod and the eval so the sweep regrades the rule prod runs.
    """
    if choice == JevChoice.FORBIDDEN and confidence >= floor:
        return JevChoice.FORBIDDEN
    return JevChoice.PERMITTED


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
            assistant_turns=assistant.context(),
            transport=self._transport,
        )
        forbid = await self._forbid_verdict(asked, user_messages, call)
        return decide_from_verdict(
            replace(asked, forbid=forbid),
            JevCase(
                call=call,
                user_messages=user_messages,
                prior_calls=prior_calls,
                history=history,
                shown_turns=assistant.shown,
            ),
        )

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

    async def _forbid_verdict(
        self, asked: "JevVerdict", user_messages: list[str], call: JudgedCall
    ) -> str | None:
        """Return the focused forbid verdict, or None when no check is warranted.

        A failed check degrades to asking, never to a run.
        """
        if not needs_forbid_check(user_messages, contained=asked.contained):
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
) -> IntentDecision:
    """Map one JEV verdict through the code vetoes. Pure, shared by prod and eval.

    A call the user's words don't clearly authorize still runs when its effect is
    contained and nothing they said or did objects; only risky calls need the words.
    """
    log.info(
        f"{LogTag.HIL} JEV judge",
        tool_name=case.call.tool_name,
        hil={
            "choice": verdict.choice,
            "confidence": round(verdict.confidence, 3),
            "contained": None if verdict.contained is None else round(verdict.contained, 3),
            "forbid": verdict.forbid,
            "version": JEV_QUESTIONS_VERSION,
        },
    )
    decision = _authorization_decision(verdict, case, accept_line=accept_line)
    if decision.outcome == "ask" and _runs_contained(verdict, case, contained_line=contained_line):
        return IntentDecision(
            "accept", f"{CONTAINED_RUN_REASON} (contained {verdict.contained:.2f})."
        )
    return decision


def _runs_contained(verdict: JevVerdict, case: JevCase, *, contained_line: float) -> bool:
    """Whether the call's effect is contained enough to run with nothing the user said against it."""
    return (
        verdict.contained is not None
        and verdict.contained >= contained_line
        and verdict.choice != JevChoice.FORBIDDEN
        # An answer without P(forbidden) can't show the call is safe to run unasked.
        and (verdict.probabilities or {}).get(JevChoice.FORBIDDEN, 1.0)
        < HIL_JEV_CONTAINED_MAX_FORBIDDEN
        and (verdict.forbid == JevChoice.PERMITTED or not forbid_tripwire(case.user_messages))
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
    if forbid_tripwire(case.user_messages):
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
