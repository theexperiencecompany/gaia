"""Auto mode's intent judge: do the user's own words authorize this call?

Called by the gate when the user's mode is auto; unsupported, broader, or
unclear cases fall back to the normal approval pause. Only the user's words
carry authority, not the executor/subagent's agent-authored paraphrase; all
recent turns are carried since the authorizing quote may be an earlier one.

The judge never sees the agent's prose, since fabricated reasoning raises a
judge's false-approval rate by 20-30 points with actions held fixed (arXiv
2601.14691), and LLM judges are also measurably lenient (>96% TPR, <25% TNR,
arXiv 2510.11822, 2605.06161). So the model must quote its authorizing words,
and _is_grounded checks the quote really occurs in something the user wrote.

Fails toward asking on: no user turns, judge error, malformed output, an
ungrounded quote, instruction-like arguments, or shipping secrets outward.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
from typing import Literal, Protocol

from app.constants.hil import HIL_JUDGE_MAX_ASSISTANT_TURNS
from app.constants.log_tags import LogTag
from app.models.hil_models import ApprovalLedgerDocument
from app.services.hil.utils import (
    PriorCall,
    args_preview,
)
from shared.py.approvals import ActionResult, ApprovalOutcome
from shared.py.wide_events import log

_NO_REQUEST_REASON = "Could not check this against anything you asked for."
_JUDGE_FAILED_REASON = "The approval check could not run."
#: Shown when a call ran on containment rather than on the user's explicit words.
CONTAINED_RUN_REASON = "Auto mode ran this: it stays in your account and can be undone"
GO_AHEAD_RUN_REASON = "Auto mode ran this: your reply was the go-ahead for it"
STANDING_RULE_REASON = (
    "One of your saved instructions asks for your go-ahead before this {tool} call."
)


@dataclass(frozen=True)
class JudgedCall:
    """The tool call put to the judge, as the judge sees it.

    Name, description, arguments and summary always travel together — the gate reads
    them off one pending call, and the prompt renders all four — so they are passed as
    one value rather than four parallel arguments. tool_schema is the tool's own
    argument contract: an opaque id stops being opaque once the judge sees what it
    is for.
    """

    tool_name: str
    description: str
    args: dict[str, object]
    summary: str
    tool_schema: dict[str, object] | None = None


# What auto mode decided about one call: accept runs it, ask registers the normal
# approval card. Auto never refuses on its own: a call it doubts goes to the user.
AutoOutcome = Literal["accept", "ask"]


@dataclass(frozen=True)
class AutoHistory:
    """What this user recently decided about this tool — the judge's memory.

    Built from the ledger (Task 4 wires the counts); defaults to blank, which
    the judge reads as "no signal", never as authorization. A store failure
    degrades to this blank, not to an exception out of the judge path.
    """

    approved_recent: int = 0
    denied_recent: int = 0
    last_deny_feedback: str | None = None
    last_deny_at: datetime | None = None
    # Recipients/targets from the user's own approved runs (bounded) — a
    # repeat send to a known address is not "an address from nowhere". Mined
    # from the same rows as the counts: no extra query, no extra latency.
    known_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntentDecision:
    """The judge's call, plus the model-facing why: accept runs the call, ask raises a card."""

    outcome: AutoOutcome
    reason: str


# An approved action that then failed or vanished is not counted as a vote to let it run.
_UNCOUNTED_ACTIONS = frozenset({ActionResult.FAILED, ActionResult.UNKNOWN})


def summarize_history(rows: list[ApprovalLedgerDocument]) -> AutoHistory:
    """Count recent ledger outcomes into the judge's memory.

    Pure: the repository fetches rows, this decides what they mean. Only
    decided rows count — pendings were never answered, revokes and failures
    were never approved-or-denied.
    """
    let_run = [
        row
        for row in rows
        if row.outcome is ApprovalOutcome.APPROVED and row.action not in _UNCOUNTED_ACTIONS
    ]
    approved = len(let_run)
    denies = [row for row in rows if row.outcome is ApprovalOutcome.DENIED]
    # Timestamps, not datetimes: round-tripped rows may be naive while
    # hand-built ones are aware, and mixed comparison raises.
    latest = max(
        denies,
        key=lambda row: row.decided_at.timestamp() if row.decided_at is not None else -math.inf,
        default=None,
    )
    return AutoHistory(
        approved_recent=approved,
        denied_recent=len(denies),
        last_deny_feedback=latest.feedback if latest else None,
        last_deny_at=latest.decided_at if latest else None,
        known_targets=tuple(
            dict.fromkeys(target for row in let_run for target in _target_values(row.args))
        )[:20],
    )


def history_line(history: AutoHistory, tool_name: str) -> str:
    """One line of memory for the judge prompt: counts plus known targets.

    Known targets are recipient/id values from the user's own approved runs —
    the same args the judge already sees in full, so no new exposure, just
    the repeat pattern made explicit.
    """
    if history.approved_recent == 0 and history.denied_recent == 0:
        return f"No recent decisions on {tool_name}."
    line = (
        f"Recent decisions on {tool_name}: {history.approved_recent} approved, "
        f"{history.denied_recent} denied."
    )
    if history.last_deny_feedback:
        line += f" Latest deny reason: {history.last_deny_feedback!r}."
    if history.known_targets:
        line += f" Known from past runs: {', '.join(history.known_targets[:8])}."
    return line


@dataclass(frozen=True)
class AssistantTurns:
    """The assistant's recent words: context for a shorthand, never authorization.

    shown are the replies the user saw before their turn, the only ones a confirmation or
    a pick from a listed result may rest on. run are this run's own messages, unseen.
    """

    shown: tuple[str, ...] = ()
    run: tuple[str, ...] = ()

    def recent_shown(self) -> list[str]:
        """Return the latest replies the user saw, oldest first."""
        return list(self.shown[-HIL_JUDGE_MAX_ASSISTANT_TURNS:])

    def recent_run(self) -> list[str]:
        """Return the run's latest own messages, oldest first."""
        return list(self.run[-HIL_JUDGE_MAX_ASSISTANT_TURNS:])


class IntentJudge(Protocol):
    """Decide one auto-mode call.

    LLM-backed today; a JEV-backed judge implements this Protocol later (JEV
    answers risk booleans, code keeps the grounding-quote and veto checks) — the
    gate never changes.
    """

    async def decide(
        self,
        *,
        user_id: str,
        user_messages: list[str],
        call: JudgedCall,
        prior_calls: list[PriorCall],
        history: AutoHistory,
        assistant: AssistantTurns = AssistantTurns(),
    ) -> IntentDecision: ...

    async def standing_rules_hold(
        self, *, standing_rules: tuple[str, ...], call: JudgedCall
    ) -> bool:
        """Whether a saved instruction forbids this call or asks to be asked first."""
        ...


@dataclass(frozen=True)
class AutoContext:
    """The user's auto-mode standing for one decision: who, their record, their opt-outs."""

    user_id: str
    history: AutoHistory = AutoHistory()
    # The user put this call's tool on their never-auto list (matched by HIL tool key).
    never_auto: bool = False
    # Saved instructions that reach this call (global and its integration's): they can
    # only make it ask, never authorize it.
    standing_rules: tuple[str, ...] = ()


async def judge_intent(
    auto: AutoContext,
    *,
    user_messages: list[str],
    call: JudgedCall,
    prior_calls: list[PriorCall],
    judge: IntentJudge,
    assistant: AssistantTurns = AssistantTurns(),
) -> IntentDecision:
    """Decide whether the user's own words authorize this call; fails toward asking.

    No user turns and a tool on the never-auto list both ask without spending a
    call. assistant is recent assistant prose: context for what a shorthand refers
    to ("send it" after "your draft to X is ready"), never authorization.
    """
    turns = [text for text in user_messages if text.strip()]
    if not turns:
        log.info(
            f"{LogTag.HIL} intent judge : nothing to verify against; asking",
            tool_name=call.tool_name,
        )
        return IntentDecision("ask", _NO_REQUEST_REASON)

    if auto.never_auto:
        return IntentDecision(
            "ask",
            f"{call.tool_name} is on your never-auto list, so it always asks.",
        )

    try:
        decision = await judge.decide(
            user_id=auto.user_id,
            user_messages=turns,
            call=call,
            prior_calls=prior_calls,
            history=auto.history,
            assistant=assistant,
        )
        if (
            decision.outcome == "accept"
            and auto.standing_rules
            and await judge.standing_rules_hold(standing_rules=auto.standing_rules, call=call)
        ):
            return IntentDecision("ask", STANDING_RULE_REASON.format(tool=call.tool_name))
    except Exception as e:  # the one classifier failed: the call waits on the user instead
        log.error(
            f"{LogTag.HIL} intent judge failed; asking",
            tool_name=call.tool_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return IntentDecision("ask", _JUDGE_FAILED_REASON)
    return decision


def _history_blocks(history: AutoHistory) -> bool:
    """Whether past denies outweigh approvals enough to hold off auto-accept.

    Blank history is no signal (a new tool must still be able to auto-approve);
    otherwise accept needs strictly more approvals than denies. The user can
    always approve the resulting card by hand.
    """
    if history.approved_recent == 0 and history.denied_recent == 0:
        return False
    return history.approved_recent <= history.denied_recent


def _output_identifies(output: str) -> bool:
    """Whether a prior result identifies (rather than lists).

    One id-like value means the lookup returned the thing: acting on it
    involves no agent choice. Several means the agent picked from a list —
    and that pick is exactly what needs the user's confirmation. Unparseable
    results identify nothing.
    """
    try:
        parsed: object = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return False
    return len([t for t in _target_values(parsed) if _is_id_like(t)]) == 1


def _is_id_like(target: str) -> bool:
    """Whether a target value is a reference id, not an address or an amount."""
    if "@" in target:
        return False
    return not target.replace(",", "").replace(".", "").replace("$", "").strip().isdigit()


def ungrounded_targets(
    args: dict[str, object],
    user_turns: list[str],
    prior_calls: list[PriorCall],
    known: frozenset[str] | None = None,
    *,
    shown_turns: list[str] | None = None,
) -> list[str]:
    """Return target-like arg values with no provenance in user words or priors.

    Backstop for JEV: an email, id or amount from nowhere blocks auto-accept. A prior
    output grounds when it identifies (one result), or when the listed entry holding
    the target names an address the user wrote or was shown: not a blind pick.
    """
    provenance = [f"{call.name} {args_preview(call.args)}" for call in prior_calls]
    provenance += [
        call.output
        for call in prior_calls
        if call.output.strip() and _output_identifies(call.output)
    ]
    # Matched per source: a target straddling two turns or two priors came from neither.
    sources = [_normalize(text) for text in [*user_turns, *provenance]]
    normalized_known = {_normalize(target) for target in known or frozenset()}
    user_tokens = {token for turn in user_turns for token in _normalize(turn).split()}
    pointed_at = [*user_turns, *(shown_turns or [])]
    return [
        target
        for target in _target_values(args)
        if not any(_mentions(source, _normalize(target)) for source in sources)
        and _normalize(target) not in normalized_known
        and _local_part(target) not in user_tokens
        and not _listed_entry_pointed_at(target, prior_calls, pointed_at)
    ]


_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: What may sit between the addresses of a recipients column.
_RECIPIENT_SEPARATORS = re.compile(r"[\s,;]+")
#: Quoted text in a plain-text list line: content, never the entry's own fields.
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”")


def _listed_entry_pointed_at(target: str, prior_calls: list[PriorCall], context: list[str]) -> bool:
    """Whether a listed result carries target on an entry naming an address in context."""
    text = _normalize(" ".join(context))
    tokens = set(text.split())
    return any(
        _mentions(text, _normalize(address)) or _local_part(address) in tokens
        for call in prior_calls
        for addresses in _entry_addresses(call.output, target)
        for address in addresses
    )


def _entry_addresses(output: str, target: str) -> list[list[str]]:
    """Return the own addresses of each listed entry that carries target: JSON objects, else lines.

    A plain-text line's quoted text is content (a forwarded mail, a subject), never the
    entry's own fields, so it is dropped before its recipients are read (_line_recipients).
    """
    try:
        parsed: object = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        holds = re.compile(rf"(?<![\w-]){re.escape(target)}(?![\w-])")
        return [
            _line_recipients(_QUOTED.sub(" ", line))
            for line in output.splitlines()
            if holds.search(line)
        ]
    return [
        _ADDRESS.findall(_own_fields(node)) for node in _objects(parsed) if target in node.values()
    ]


def _line_recipients(line: str) -> list[str]:
    """Return the addresses a plain-text list line names as its own recipients.

    Only a column holding nothing but addresses is a recipients column ("id | to |
    subject | gist"); the first column with an address must be one, or the line is
    ambiguous ("d-1 | Bob | Forwarded from simonne@x.com") and names none. A line
    without columns can't part recipients from prose, so it names none either.
    """
    for cell in line.split("|")[1:]:
        if found := _ADDRESS.findall(cell):
            return found if not _RECIPIENT_SEPARATORS.sub("", _ADDRESS.sub("", cell)) else []
    return []


def _own_fields(record: dict[str, object]) -> str:
    """Render a record's own scalar fields, free text apart; a nested record is a different entry.

    A draft to bob@x.com quoting a mail from simonne@x.com, as a nested record or in its
    body, is Bob's draft, not Simonne's.
    """
    values: list[object] = []
    for key, value in record.items():
        if str(key).lower() in _PROSE_FIELDS:
            continue
        if isinstance(value, list):
            values += [item for item in value if not isinstance(item, (dict, list))]
        elif not isinstance(value, dict):
            values.append(value)
    return " ".join(str(value) for value in values)


def _objects(value: object) -> list[dict[str, object]]:
    """Every JSON object nested anywhere in value."""
    if isinstance(value, dict):
        return [value, *(found for child in value.values() for found in _objects(child))]
    if isinstance(value, list):
        return [found for child in value for found in _objects(child)]
    return []


def _local_part(target: str) -> str:
    """Return the email local part ("sarah" of "sarah@x.com"), else "".

    "Reply yes to Sarah's thread" grounds sarah@x.com: the name matches, only
    the domain was resolved. Equality on the local part — a "bob" in the text
    never grounds "bobby@evil.com". A string with a second "@" is no address,
    so it has no local part to ground.
    """
    if target.count("@") != 1:
        return ""  # pragma: no mutate — user_tokens are non-empty lowercase words, so no literal here can ever be one
    return target.partition("@")[
        0
    ]  # pragma: no mutate — exactly one "@", so rpartition splits identically


def _target_values(args: object) -> list[str]:
    """Collect the arg values that name a target: emails, ids, amounts.

    Datetimes are NOT targets: an ISO rendering never matches "tomorrow at 2pm"
    textually, so grounding it would ask on every derived time. Free-text fields
    (body, subject, text) are not targets either: a code like "q3" in a body is
    content the choice criteria judge, not a who/which/how-much.
    """
    found: list[str] = []
    if isinstance(args, dict):
        for key, value in args.items():
            if str(key).lower() in _PROSE_FIELDS:
                continue
            found += _target_values(value)
    elif isinstance(args, list):
        for value in args:
            found += _target_values(value)
    elif isinstance(args, str):
        candidate = _target_string(args.strip())
        if candidate is not None:
            found.append(candidate)
    elif isinstance(args, bool):
        pass
    elif isinstance(args, (int, float)):
        found.append(str(args))
    return [target for target in found if len(target) >= 2]


#: Arg fields that carry prose, never references. The choice criteria judge
#: their content; grounding only covers who/which/how-much.
_PROSE_FIELDS = frozenset(
    {"body", "subject", "text", "content", "message", "description", "title", "summary"}
)


def _target_string(value: str) -> str | None:
    """Return value when it looks like a copied target, else None."""
    if "@" in value:
        return value
    if re.search(r"\d{4}-\d{2}-\d{2}", value):
        return None
    if len(value.split()) > 2:
        return None
    if value.replace(",", "").replace(".", "").replace("$", "").strip().isdigit():
        return value
    if len(value) < 24 and (
        any(char.isdigit() for char in value) or value.startswith(("evt-", "#"))
    ):
        return value
    return None


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _mentions(source: str, phrase: str) -> bool:
    """Whether normalized source holds the normalized phrase as whole words.

    "ann x com" is not in "joann x com": an address the user named never grounds one it ends.
    """
    return f" {phrase} " in f" {source} "
