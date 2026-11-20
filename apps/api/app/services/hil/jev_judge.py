"""JEV choice judge for auto mode (app/services/hil/intent.py's other half).

One Decisions call returns authorized / forbidden / unclear with a confidence,
plus P(contained); code maps them to accept / reject / ask and applies the checks
a classifier must never grade itself on (target grounding, history bias, holds).
Prod asks JEV (HIL_JEV_JUDGE_MODEL_NAME); the calibration suite may inject another
transport. Transport failure degrades to the injected LLM fallback — an outage
behaves like the LLM judge, never like an open gate.

Question text lives in prompts.py (JEV_QUESTION); thresholds in
constants/hil.py. Both are tuned through the hil-judge calibration suite,
never by hand here.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial

from app.constants.hil import (
    HIL_JEV_ACCEPT_LINE,
    HIL_JEV_CONTAINED_LINE,
    HIL_JEV_CONTAINED_MAX_FORBIDDEN,
    HIL_JEV_JUDGE_MODEL_NAME,
    HIL_JEV_REJECT_FLOOR,
    JEV_CONTAINED_QUESTION_KEY,
    JEV_FORBID_CHECK_FAILED,
    JevChoice,
)
from app.constants.log_tags import LogTag
from app.models.jev_models import JevDecisionsResponse
from app.services.hil.intent import (
    CONTAINED_RUN_REASON,
    AutoHistory,
    AutoOutcome,
    IntentDecision,
    IntentJudge,
    JudgedCall,
    _history_blocks,
    _LLMIntentJudge,
    forbid_tripwire,
    history_line,
    ungrounded_targets,
    user_held_or_denied,
)
from app.services.hil.jev_client import post_decisions
from app.services.hil.prompts import (
    JEV_CONTAINED_QUESTION,
    JEV_FORBID_QUESTION,
    JEV_QUESTION,
    JEV_QUESTIONS_VERSION,
)
from app.services.hil.utils import PriorCall
from shared.py.wide_events import log


def map_jev_choice(
    choice: str, confidence: float, *, accept_line: float, reject_floor: float
) -> AutoOutcome:
    """JEV verdict to gate outcome. Pure — the offline sweep reuses this."""
    if choice == JevChoice.AUTHORIZED and confidence >= accept_line:
        return "accept"
    if choice == JevChoice.FORBIDDEN and confidence >= reject_floor:
        return "reject"
    return "ask"


def decisive_forbidden(
    choice: str, probabilities: Mapping[str, float], *, margin: float = 0.40
) -> bool:
    """Whether forbidden is the runaway winner, whatever its absolute number.

    One-sided margin: a 0.40 lead over the runner-up rejects; accept keeps its line.
    """
    if choice != JevChoice.FORBIDDEN:
        return False
    runner_up = max(
        (prob for label, prob in probabilities.items() if label != JevChoice.FORBIDDEN),
        default=0.0,
    )
    return probabilities.get(JevChoice.FORBIDDEN, 0.0) - runner_up >= margin


#: Sends one Decisions request (state + named questions) and parses its answers.
DecisionsTransport = Callable[
    [Mapping[str, object], Mapping[str, Mapping[str, object]]], Awaitable[JevDecisionsResponse]
]

#: The judge's prod transport: JEV on the model its lines were tuned on.
JUDGE_TRANSPORT: DecisionsTransport = partial(post_decisions, model=HIL_JEV_JUDGE_MODEL_NAME)


async def ask_jev_forbid(
    *,
    user_messages: list[str],
    call: JudgedCall,
    transport: DecisionsTransport = JUDGE_TRANSPORT,
) -> tuple[str, float, int, int]:
    """Focused forbid check: does any earlier turn forbid THIS action?

    Second, decomposed opinion — runs only when the main verdict would accept
    but the tripwire found forbid language. Returns (choice, confidence, in,
    out) tokens; transport failure raises (caller degrades to ask, never to
    a run).
    """
    state = {
        "earlier_turns": user_messages[:-1],
        "latest_turns": user_messages[-1:],
        "pending_action": {"tool": call.tool_name, "args": call.args},
    }
    body = await transport(state, {"forbid": JEV_FORBID_QUESTION})
    answer = body.choice("forbid", (JevChoice.FORBIDDEN, JevChoice.PERMITTED), label="forbid ")
    return (answer.choice, float(answer.confidence or 0.0), *body.tokens())


def needs_forbid_check(
    mapped_outcome: AutoOutcome,
    user_messages: list[str],
    *,
    contained: float | None,
    contained_line: float = HIL_JEV_CONTAINED_LINE,
) -> bool:
    """Whether a call that may run needs the focused forbid double-check.

    Pure predicate shared by prod and the eval transport: the call would run
    (an accept, or contained at the line) but earlier turns carry forbid
    language with no later lift.
    """
    may_run = mapped_outcome == "accept" or (contained is not None and contained >= contained_line)
    return may_run and forbid_tripwire(user_messages)


def settle_forbid(
    choice: str, confidence: float, *, reject_floor: float = HIL_JEV_REJECT_FLOOR
) -> JevChoice:
    """Settle a forbid double-check answer: forbidden only at or past the floor, else permitted.

    Pure, shared by prod and the eval transport so the sweep regrades the rule prod runs.
    """
    if choice == JevChoice.FORBIDDEN and confidence >= reject_floor:
        return JevChoice.FORBIDDEN
    return JevChoice.PERMITTED


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

    Raises on transport failure or a malformed answer — the caller falls back
    to the LLM judge, never to an allow.
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
        state, {"decision": JEV_QUESTION, JEV_CONTAINED_QUESTION_KEY: JEV_CONTAINED_QUESTION}
    )
    answer = body.choice("decision", (JevChoice.AUTHORIZED, JevChoice.FORBIDDEN, JevChoice.UNCLEAR))
    verdict = JevVerdict(
        choice=answer.choice,
        confidence=float(answer.confidence or 0.0),
        probabilities=dict(answer.probabilities or {}),
        contained=body.noul(JEV_CONTAINED_QUESTION_KEY),
    )
    return (verdict, *body.tokens())


class JevIntentJudge:
    """Auto mode classifier: JEV decides, code applies the vetoes.

    Fallback runs when the Decisions call fails; unclear asks the user.
    """

    def __init__(
        self,
        fallback: IntentJudge | None = None,
        transport: DecisionsTransport = JUDGE_TRANSPORT,
    ) -> None:
        self._fallback = fallback or _LLMIntentJudge()
        self._transport = transport

    async def decide(
        self,
        *,
        user_id: str,
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        history: AutoHistory,
        assistant_turns: list[str] | None = None,
    ) -> IntentDecision:
        try:
            asked, _in, _out = await ask_jev(
                user_messages=user_messages,
                call=call,
                prior_calls=prior_calls,
                history=history,
                assistant_turns=assistant_turns,
                transport=self._transport,
            )
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} JEV judge failed; falling back to the LLM judge",
                tool_name=call.tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return await self._fallback.decide(
                user_id=user_id,
                user_messages=user_messages,
                call=call,
                prior_calls=prior_calls,
                history=history,
                assistant_turns=assistant_turns,
            )
        forbid = await self._forbid_verdict(asked, user_messages, call)
        return decide_from_verdict(
            replace(asked, forbid=forbid),
            JevCase(
                call=call,
                user_messages=user_messages,
                prior_calls=prior_calls,
                history=history,
                assistant_turns=tuple(assistant_turns or ()),
            ),
        )

    async def _forbid_verdict(
        self,
        asked: "JevVerdict",
        user_messages: list[str],
        call: JudgedCall,
    ) -> str | None:
        """Focused forbid verdict, or None when no double-check is warranted.

        Runs only for a call that may run with tripped forbid language. A failed
        focused check degrades to ask — never back to a run.
        """
        outcome = map_jev_choice(
            asked.choice,
            asked.confidence,
            accept_line=HIL_JEV_ACCEPT_LINE,
            reject_floor=HIL_JEV_REJECT_FLOOR,
        )
        if not needs_forbid_check(outcome, user_messages, contained=asked.contained):
            return None
        try:
            forbid_choice, forbid_conf, _in, _out = await ask_jev_forbid(
                user_messages=user_messages, call=call, transport=self._transport
            )
        except Exception as e:
            log.warning(
                f"{LogTag.HIL} forbid double-check failed; asking",
                tool_name=call.tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            return JEV_FORBID_CHECK_FAILED
        log.info(
            f"{LogTag.HIL} forbid double-check",
            tool_name=call.tool_name,
            hil={"choice": forbid_choice, "confidence": round(forbid_conf, 3)},
        )
        return settle_forbid(forbid_choice, forbid_conf)


@dataclass(frozen=True)
class JevVerdict:
    """What JEV said about one call, plus the focused forbid re-check when one ran.

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

    assistant_turns are what the user was shown: they ground a pick from a list
    the user was pointed at, never authorize anything.
    """

    call: JudgedCall
    user_messages: list[str]
    prior_calls: list[PriorCall]
    history: AutoHistory
    assistant_turns: tuple[str, ...] = ()


def decide_from_verdict(
    verdict: JevVerdict,
    case: JevCase,
    *,
    accept_line: float = HIL_JEV_ACCEPT_LINE,
    reject_floor: float = HIL_JEV_REJECT_FLOOR,
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
            "version": JEV_QUESTIONS_VERSION,
        },
    )
    decision = _authorization_decision(
        verdict, case, accept_line=accept_line, reject_floor=reject_floor
    )
    if (
        decision.outcome == "ask"
        and verdict.contained is not None
        and verdict.contained >= contained_line
        and verdict.choice != JevChoice.FORBIDDEN
        and (verdict.probabilities or {}).get(JevChoice.FORBIDDEN, 0.0)
        < HIL_JEV_CONTAINED_MAX_FORBIDDEN
        and (verdict.forbid == JevChoice.PERMITTED or not forbid_tripwire(case.user_messages))
        and not user_held_or_denied(case.user_messages, case.history)
    ):
        return IntentDecision(
            "accept", f"{CONTAINED_RUN_REASON} (contained {verdict.contained:.2f})."
        )
    return decision


def _authorization_decision(
    verdict: JevVerdict, case: JevCase, *, accept_line: float, reject_floor: float
) -> IntentDecision:
    """Whether the user's words authorize the call. The forbid double-check alone rejects."""
    choice, confidence, call = verdict.choice, verdict.confidence, case.call
    forbid = verdict.forbid
    outcome = map_jev_choice(
        choice,
        confidence,
        accept_line=accept_line,
        reject_floor=reject_floor,
    )
    if outcome == "ask" and decisive_forbidden(choice, verdict.probabilities or {}):
        outcome = "reject"
    if outcome == "accept" and forbid == JevChoice.FORBIDDEN:
        return IntentDecision(
            "reject",
            "Auto mode held this off: an earlier message forbids this "
            f"{call.tool_name} call and nothing since lifted it.",
        )
    if outcome == "accept" and forbid is not None:
        # The tripwire found forbid language but the double-check would not
        # refuse: contradictory turns still need the human, so the accept
        # floors to a card rather than running.
        return IntentDecision(
            "ask",
            "Auto mode wasn't sure: an earlier message argues against this "
            f"{call.tool_name} call — your call.",
        )
    if outcome == "reject":
        return IntentDecision(
            "reject",
            f"Auto mode held this off: your messages argue against this {call.tool_name} call.",
        )
    if outcome == "accept":
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
            shown_turns=list(case.assistant_turns),
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
    return IntentDecision(
        "ask",
        f"this {call.tool_name} call may not match your request ({choice} {confidence:.2f}).",
    )
