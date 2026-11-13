"""JEV choice judge for auto mode (app/services/hil/intent.py's other half).

One Decisions API call returns authorized / forbidden / unclear with a
calibrated confidence; code maps it to accept / reject / ask and applies the
checks a classifier must never grade itself on (target grounding, history
bias). Transport failure degrades to the injected LLM fallback — the gate's
behavior on a JEV outage is today's behavior, not an open gate.

Question text lives in prompts.py (JEV_QUESTION); thresholds in
constants/hil.py. Both are tuned through the hil-judge calibration suite,
never by hand here.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import re

from app.constants.hil import (
    HIL_JEV_ACCEPT_LINE,
    HIL_JEV_REJECT_FLOOR,
    JEV_FORBID_CHECK_FAILED,
    JevChoice,
)
from app.constants.log_tags import LogTag
from app.services.hil.intent import (
    AutoHistory,
    AutoOutcome,
    IntentDecision,
    IntentJudge,
    JudgedCall,
    _history_blocks,
    _LLMIntentJudge,
    history_line,
    ungrounded_targets,
)
from app.services.hil.jev_client import post_decisions
from app.services.hil.prompts import (
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


#: Forbid double-check on the accept path: crisp prohibitions, not moods.
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


def forbid_tripwire(user_messages: list[str]) -> bool:
    """Whether an earlier turn forbids with no later lift — check needed.

    A tripwire, not a verdict: it only ever downgrades an accept into a
    focused forbid-check (or an ask), never into a run. Matching is
    deterministic keyword/regex on the user's own words; the JUDGMENT of
    whether the forbid covers this call belongs to the focused JEV question.
    """
    for index, turn in enumerate(user_messages):
        if _matches_any(turn, _FORBID_PATTERNS) and not any(
            _matches_any(later, _LIFT_PATTERNS) for later in user_messages[index + 1 :]
        ):
            return True
    return False


def _matches_any(turn: str, patterns: tuple[str, ...]) -> bool:
    lowered = turn.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


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


async def ask_jev_forbid(
    *,
    user_messages: list[str],
    call: JudgedCall,
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
    body = await post_decisions(state, {"forbid": JEV_FORBID_QUESTION})
    answer = body.choice("forbid", (JevChoice.FORBIDDEN, JevChoice.PERMITTED), label="forbid ")
    return (answer.choice, float(answer.confidence or 0.0), *body.tokens())


def needs_forbid_check(mapped_outcome: AutoOutcome, user_messages: list[str]) -> bool:
    """Whether an accept needs the focused forbid double-check.

    Pure predicate shared by prod and the eval transport: the main verdict
    says accept, but earlier turns carry forbid language with no later lift.
    """
    return mapped_outcome == "accept" and forbid_tripwire(user_messages)


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
) -> tuple[str, float, dict[str, float], int, int]:
    """One Decisions call: (choice, confidence, probabilities, in, out) tokens.

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
    body = await post_decisions(state, {"decision": JEV_QUESTION})
    answer = body.choice("decision", (JevChoice.AUTHORIZED, JevChoice.FORBIDDEN, JevChoice.UNCLEAR))
    return (
        answer.choice,
        float(answer.confidence or 0.0),
        dict(answer.probabilities or {}),
        *body.tokens(),
    )


class JevIntentJudge:
    """Auto mode classifier: JEV decides, code applies the vetoes.

    Fallback runs when the Decisions call fails; unclear asks the user.
    """

    def __init__(self, fallback: IntentJudge | None = None) -> None:
        self._fallback = fallback or _LLMIntentJudge()

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
            choice, confidence, probs, _in, _out = await ask_jev(
                user_messages=user_messages,
                call=call,
                prior_calls=prior_calls,
                history=history,
                assistant_turns=assistant_turns,
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
        return decide_from_verdict(
            JevVerdict(
                choice=choice,
                confidence=confidence,
                probabilities=probs,
                forbid=await self._forbid_verdict(choice, confidence, user_messages, call),
            ),
            JevCase(
                call=call,
                user_messages=user_messages,
                prior_calls=prior_calls,
                history=history,
            ),
        )

    async def _forbid_verdict(
        self,
        choice: str,
        confidence: float,
        user_messages: list[str],
        call: JudgedCall,
    ) -> str | None:
        """Focused forbid verdict, or None when no double-check is warranted.

        Runs only on the accept path with tripped forbid language. A failed
        focused check degrades to ask (the tripwire already downgraded the
        accept) — never back to a run.
        """
        outcome = map_jev_choice(
            choice,
            confidence,
            accept_line=HIL_JEV_ACCEPT_LINE,
            reject_floor=HIL_JEV_REJECT_FLOOR,
        )
        if not needs_forbid_check(outcome, user_messages):
            return None
        try:
            forbid_choice, forbid_conf, _in, _out = await ask_jev_forbid(
                user_messages=user_messages, call=call
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
    """What JEV said about one call, plus the focused forbid re-check when one ran."""

    choice: str
    confidence: float
    probabilities: Mapping[str, float] | None = None
    forbid: str | None = None


@dataclass(frozen=True)
class JevCase:
    """What a verdict is weighed against: the call, the user's words, the run's history."""

    call: JudgedCall
    user_messages: list[str]
    prior_calls: list[PriorCall]
    history: AutoHistory


def decide_from_verdict(
    verdict: JevVerdict,
    case: JevCase,
    *,
    accept_line: float = HIL_JEV_ACCEPT_LINE,
    reject_floor: float = HIL_JEV_REJECT_FLOOR,
) -> IntentDecision:
    """Map one JEV verdict through the code vetoes. Pure, shared by prod and eval.

    The verdict's forbid carries the focused double-check; only forbidden rejects.
    """
    choice, confidence, call = verdict.choice, verdict.confidence, case.call
    forbid = verdict.forbid
    log.info(
        f"{LogTag.HIL} JEV judge",
        tool_name=call.tool_name,
        hil={
            "choice": choice,
            "confidence": round(confidence, 3),
            "version": JEV_QUESTIONS_VERSION,
        },
    )
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
