"""JEV choice judge for auto mode (app/services/hil/intent.py's other half).

One Decisions API call returns authorized / forbidden / unclear with a
calibrated confidence; code maps it to accept / ask and applies the
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

from app.constants.hil import HIL_JEV_ACCEPT_LINE, JevChoice
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
from app.services.hil.prompts import JEV_QUESTION, JEV_QUESTIONS_VERSION
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


def forbid_tripwire(user_messages: list[str]) -> bool:
    """Whether an earlier turn forbids with no later lift; an accept then asks instead."""
    for index, turn in enumerate(user_messages):
        if _matches_any(turn, _FORBID_PATTERNS) and not any(
            _matches_any(later, _LIFT_PATTERNS) for later in user_messages[index + 1 :]
        ):
            return True
    return False


def _matches_any(turn: str, patterns: tuple[str, ...]) -> bool:
    lowered = turn.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


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
            ),
            JevCase(
                call=call,
                user_messages=user_messages,
                prior_calls=prior_calls,
                history=history,
            ),
        )


@dataclass(frozen=True)
class JevVerdict:
    """What JEV said about one call."""

    choice: str
    confidence: float
    probabilities: Mapping[str, float] | None = None


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
) -> IntentDecision:
    """Map one JEV verdict through the code vetoes. Pure, shared by prod and eval."""
    choice, confidence, call = verdict.choice, verdict.confidence, case.call
    log.info(
        f"{LogTag.HIL} JEV judge",
        tool_name=call.tool_name,
        hil={
            "choice": choice,
            "confidence": round(confidence, 3),
            "version": JEV_QUESTIONS_VERSION,
        },
    )
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
