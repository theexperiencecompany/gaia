"""JEV choice judge for auto mode (app/services/hil/intent.py's other half).

One Decisions API call per gated call carries every question: authorized / forbidden /
unclear with a calibrated confidence, how contained the call's effect is, whether
anything the user said or saved objects, and (when the user was shown a reply) whether
their message is the go-ahead. Code maps the answers to accept / ask and applies the
checks a classifier must never grade itself on (target grounding, history). A failed
Decisions call raises, and judge_intent leaves the call to the user.

Question text lives in prompts.py; thresholds in constants/hil.py. Both are tuned
through the hil-judge calibration suite, never by hand here.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

from app.constants.hil import (
    HIL_JEV_ACCEPT_LINE,
    HIL_JEV_CONTAINED_LINE,
    HIL_JEV_CONTAINED_MAX_FORBIDDEN,
    HIL_JEV_GO_AHEAD_LINE,
    HIL_JEV_JUDGE_MODEL_NAME,
    HIL_JEV_OBJECTION_FLOOR,
    JEV_CONTAINED_QUESTION_KEY,
    JEV_DECISION_QUESTION_KEY,
    JEV_GO_AHEAD_QUESTION_KEY,
    JEV_OBJECTION_QUESTION_KEY,
    JevChoice,
)
from app.constants.log_tags import LogTag
from app.models.jev_models import JevChoiceAnswer, JevDecisionsResponse
from app.services.hil.intent import (
    CONTAINED_RUN_REASON,
    GO_AHEAD_RUN_REASON,
    AssistantTurns,
    AutoContext,
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
    JEV_GO_AHEAD_QUESTION,
    JEV_OBJECTION_QUESTION,
    JEV_QUESTION,
    JEV_QUESTIONS_VERSION,
)
from app.services.hil.utils import PriorCall
from shared.py.wide_events import log


def map_jev_choice(choice: str, confidence: float, *, accept_line: float) -> AutoOutcome:
    """JEV verdict to gate outcome: only a confident authorized runs, everything else asks."""
    if choice == JevChoice.AUTHORIZED and confidence >= accept_line:
        return "accept"
    return "ask"


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
    auto: AutoContext,
    assistant: AssistantTurns = AssistantTurns(),
    transport: DecisionsTransport = JUDGE_TRANSPORT,
) -> tuple["JevVerdict", int, int]:
    """One Decisions call: the verdict (every question's answer) and (in, out) tokens.

    The go-ahead question rides only when the user was shown a reply to answer, and
    standing_instructions only when saved instructions reach the call. Raises on
    transport failure or a malformed answer; the caller asks the user.
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
        "recent_history": history_line(auto.history, call.tool_name),
        "now": datetime.now(UTC).isoformat(),
    }
    if assistant.shown:
        state["assistant_turns"] = assistant.recent_shown()
    if assistant.run:
        state["run_messages"] = assistant.recent_run()
    if auto.standing_rules:
        state["standing_instructions"] = list(auto.standing_rules)
    questions: dict[str, Mapping[str, object]] = {
        JEV_DECISION_QUESTION_KEY: JEV_QUESTION,
        JEV_CONTAINED_QUESTION_KEY: JEV_CONTAINED_QUESTION,
        JEV_OBJECTION_QUESTION_KEY: JEV_OBJECTION_QUESTION,
    }
    if assistant.shown:
        questions[JEV_GO_AHEAD_QUESTION_KEY] = JEV_GO_AHEAD_QUESTION
    body = await transport(state, questions)
    answer = body.choice(
        JEV_DECISION_QUESTION_KEY, (JevChoice.AUTHORIZED, JevChoice.FORBIDDEN, JevChoice.UNCLEAR)
    )
    objection = body.choice(
        JEV_OBJECTION_QUESTION_KEY,
        (JevChoice.FORBIDDEN, JevChoice.PERMITTED),
        label="objection ",
    )
    go_ahead = None
    if assistant.shown:
        go_ahead = _confidence_in(
            body.choice(
                JEV_GO_AHEAD_QUESTION_KEY,
                (JevChoice.AUTHORIZED, JevChoice.UNCLEAR),
                label="go-ahead ",
            ),
            JevChoice.AUTHORIZED,
        )
    verdict = JevVerdict(
        choice=answer.choice,
        confidence=float(answer.confidence or 0.0),
        probabilities=dict(answer.probabilities or {}),
        contained=body.noul(JEV_CONTAINED_QUESTION_KEY),
        objection=_confidence_in(objection, JevChoice.PERMITTED),
        go_ahead=go_ahead,
    )
    return (verdict, *body.tokens())


def _confidence_in(answer: JevChoiceAnswer, wanted: JevChoice) -> float:
    """P(the answer is wanted) from a two-way choice; no confidence reads as 0.0.

    Nothing to read the answer from must never score as a sure one: "0% unclear" would
    otherwise read as a sure yes, and "0% forbidden" as a sure "nothing objects".
    """
    if answer.confidence is None:
        return 0.0
    return answer.confidence if answer.choice == wanted else 1.0 - answer.confidence


def _prior_actions(prior_calls: list[PriorCall]) -> list[dict[str, object]]:
    """Render the run's calls for JEV: tool, args, and the output when there is one."""
    actions: list[dict[str, object]] = []
    for prior in prior_calls:
        item: dict[str, object] = {"tool": prior.name, "args": prior.args}
        if prior.output.strip():
            item["output"] = prior.output
        actions.append(item)
    return actions


class JevIntentJudge:
    """Auto mode classifier: JEV decides, code applies the vetoes; unclear asks the user.

    The one classifier: a failed Decisions call raises, and judge_intent leaves the call to the user.
    """

    def __init__(self, transport: DecisionsTransport = JUDGE_TRANSPORT) -> None:
        self._transport = transport

    async def decide(
        self,
        *,
        auto: AutoContext,
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        assistant: AssistantTurns = AssistantTurns(),
    ) -> IntentDecision:
        verdict, _in, _out = await ask_jev(
            user_messages=user_messages,
            call=call,
            prior_calls=prior_calls,
            auto=auto,
            assistant=assistant,
            transport=self._transport,
        )
        case = JevCase(
            call=call,
            user_messages=user_messages,
            prior_calls=prior_calls,
            history=auto.history,
            shown_turns=assistant.shown,
        )
        return decide_from_verdict(verdict, case)


@dataclass(frozen=True)
class JevVerdict:
    """What JEV said about one call.

    contained is P(the call's effect stays with the user and can be undone), objection
    is P(nothing the user said or saved objects), go_ahead is P(the user's reply is the
    go-ahead for exactly this call). Each is None when its question was not asked: a
    journal from before it existed, or no reply shown for go_ahead.
    """

    choice: str
    confidence: float
    probabilities: Mapping[str, float] | None = None
    contained: float | None = None
    objection: float | None = None
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
    objection_floor: float = HIL_JEV_OBJECTION_FLOOR,
) -> IntentDecision:
    """Map one JEV verdict through the code vetoes. Pure, shared by prod and eval.

    A call runs unasked only when nothing objects, and then only when the user's words
    authorize it, its effect is contained, or their reply is the go-ahead for exactly it.
    """
    log.info(
        f"{LogTag.HIL} JEV judge",
        tool_name=case.call.tool_name,
        hil={
            "choice": verdict.choice,
            "confidence": round(verdict.confidence, 3),
            "contained": None if verdict.contained is None else round(verdict.contained, 3),
            "objection": None if verdict.objection is None else round(verdict.objection, 3),
            "go_ahead": None if verdict.go_ahead is None else round(verdict.go_ahead, 3),
            "version": JEV_QUESTIONS_VERSION,
        },
    )
    call = case.call
    if not _nothing_objects(verdict, objection_floor=objection_floor):
        return IntentDecision(
            "ask", f"something you said or saved argues against this {call.tool_name} call."
        )
    decision = _authorization_decision(verdict, case, accept_line=accept_line)
    if decision.outcome == "accept":
        return decision
    if _runs_contained(verdict, case, contained_line=contained_line):
        return IntentDecision(
            "accept", f"{CONTAINED_RUN_REASON} (contained {verdict.contained:.2f})."
        )
    if _runs_on_go_ahead(verdict, case, go_ahead_line=go_ahead_line):
        return IntentDecision("accept", f"{GO_AHEAD_RUN_REASON} (go-ahead {verdict.go_ahead:.2f}).")
    return decision


def _runs_contained(verdict: JevVerdict, case: JevCase, *, contained_line: float) -> bool:
    """Whether the call's effect is contained enough to run, with no recent denial of this tool."""
    return (
        verdict.contained is not None
        and verdict.contained >= contained_line
        and case.history.denied_recent == 0
    )


def _runs_on_go_ahead(verdict: JevVerdict, case: JevCase, *, go_ahead_line: float) -> bool:
    """Whether the user's reply is surely the go-ahead for this call, and it acts on a known thing."""
    return (
        verdict.go_ahead is not None
        and verdict.go_ahead >= go_ahead_line
        and bool(case.shown_turns)
        and case.history.denied_recent == 0
        and not _ungrounded(case)
    )


def _nothing_objects(verdict: JevVerdict, *, objection_floor: float) -> bool:
    """Whether nothing the user said or saved, nor JEV's choice, argues against running the call."""
    return (
        verdict.choice != JevChoice.FORBIDDEN
        # An answer without P(forbidden) can't show the call is safe to run unasked. Equivalent
        # under mutation: any default at or above the line says so, 1.0 as much as 2.0.
        and (verdict.probabilities or {}).get(JevChoice.FORBIDDEN, 1.0)  # pragma: no mutate
        < HIL_JEV_CONTAINED_MAX_FORBIDDEN
        and verdict.objection is not None
        and verdict.objection >= objection_floor
    )


def _ungrounded(case: JevCase) -> list[str]:
    """Return the call's target-like args that trace to nothing the user wrote, was shown, or approved."""
    return ungrounded_targets(
        case.call.args,
        case.user_messages,
        case.prior_calls,
        frozenset(case.history.known_targets),
        shown_turns=list(case.shown_turns),
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
    if _history_blocks(case.history):
        return IntentDecision(
            "ask",
            f"You denied {case.history.denied_recent} recent "
            f"{call.tool_name} call(s), so this one needs your "
            "go-ahead even though it looks authorized.",
        )
    if missing := _ungrounded(case):
        return IntentDecision(
            "ask",
            f"the target ({', '.join(missing[:3])}) doesn't trace to your words.",
        )
    return IntentDecision(
        "accept",
        f"Auto mode matched this to your request ({choice} {confidence:.2f}).",
    )
