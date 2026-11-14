"""Quality suite — does GAIA sound human and behave well?

Drives the REAL comms -> executor path the way every client does: each turn is
POST /api/v1/conversations/{id}/messages, then the conversation's events stream
until the message's reply settles (core.live_chat), against the live dev API
(EVALS_DEV_API_BASE, default http://localhost:9460), authenticated through the
dev bypass (X-Dev-User header, user minted via POST /api/v1/dev/users).

What a turn records:
- text is the reply that answered the message (the comms reply); work it
  started is not waited for, so for a delegated turn the text is the ack and
  communicate strings are matched against it (documented per case);
- tool calls come from tool_calls_data cards (nested data.tool_name +
  data.inputs), deduped by tool_call_id;
- follow_up_actions come from the reply entry;
- no token usage is reported on the stream: tokens are estimated via
  core.cost.estimate_tokens (noted in raw).

Multi-turn cases split case.prompt on "\\n---\\n" and send each turn into the
same conversation, whose log carries the history.

Scoring is deterministic at runtime (no LLM): structural checks always
(BubbleBoundary, ToolCard), the prompt-derived absolutes always
(emoji_discipline plus core.prompt_gates — dashes, banned chatbot phrases,
internal machinery, routing markers — whose banned lists are read out of
COMMS_AGENT_PROMPT itself rather than copied here), plus gates that exist
in expected (communicate, tool_call_correctness, suggestion, openui), plus
a real suggestion check (3-4 non-empty items, each <=50 chars, from the
follow_up_actions frame).
overall is the mean of the applied scores; the RubricJudge LLM pass runs
at finalize time (1 call per case).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import os
from pathlib import Path
import re
import time
from typing import Any, ClassVar
import uuid

import httpx
import yaml

from scripts.evals.core.cost import EvalCostTracker, estimate_tokens
from scripts.evals.core.gates import ExtraGates, known_gates, score_gates, validate_gates
from scripts.evals.core.live_chat import (
    TOOL_CALLS_CARD,
    Turn,
    TurnOptions,
    called_tools,
    read_turn,
)
from scripts.evals.core.prompt_contracts import ClauseResolutionError, contract_criteria
from scripts.evals.core.prompt_gates import PROMPT_GATES
from scripts.evals.core.providers import EvalConfig, ProviderConfig, judge_model
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    NOTHING_TO_INSPECT,
    BubbleBoundary,
    CommunicateGate,
    DelegationGate,
    OpenUICheck,
    RubricJudge,
    ToolCard,
    produced_nothing,
)
from scripts.evals.core.types import Case, CaseRun, ProviderError
from shared.py.conversation_wire import ToolDataEntry

DEV_API_BASE = os.environ.get("EVALS_DEV_API_BASE", "http://localhost:9460")
DEV_USERS_URL = f"{DEV_API_BASE}/api/v1/dev/users"
DEV_USER_HEADER = "X-Dev-User"
TURN_SEPARATOR = "\n---\n"
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "quality"

# Type aliases: ANN401 bans `Any` in annotations but not in aliases; these
# name the wire shapes without polluting every signature.
TurnRecord = dict[str, Any]
TurnPayload = dict[str, Any]


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def turns_for(case: Case) -> list[str]:
    """Return the user turns this case sends, in order.

    Declared either as setup.turns (a YAML list) or by separating turns in
    prompt with a line of ---. Public so this mapping is testable without an
    API — a silent disagreement would grade a conversation never had.
    """
    setup_turns = case.setup.get("turns") if isinstance(case.setup, dict) else None
    if setup_turns:
        return [str(t).strip() for t in setup_turns if str(t).strip()]
    return [t.strip() for t in case.prompt.split(TURN_SEPARATOR) if t.strip()]


#: A transcript entry for a tap-back rather than a written reply. The judge reads
#: the reaction in its content; the emoji gate skips it, because a reaction is the
#: one emoji the comms prompt always allows.
REACTION_KIND = "reaction"


def turn_record(turn: Turn) -> TurnRecord:
    """Reduce a live turn into the record the suite gates on, with a compact journal for raw."""
    raw: list[dict[str, Any]] = [{"type": "frame_kinds", "kinds": turn.frame_kinds}]
    raw.extend(_tool_data_summary(entry) for entry in turn.tool_data)
    if turn.follow_up_actions is not None:
        raw.append({"type": "follow_up_actions", "actions": turn.follow_up_actions})
    if turn.reaction:
        raw.append({"type": "reaction", "emoji": turn.reaction})
    if turn.error:
        raw.append({"type": "error", "detail": _truncate(turn.error, 300)})
    return {
        "text": "" if turn.is_empty else turn.reply,
        "delivered": turn.delivered,
        "tool_calls": called_tools(turn.tool_data),
        "follow_up_actions": turn.follow_up_actions,
        "error": turn.error,
        "reaction": turn.reaction,
        "raw": raw,
    }


def _tool_data_summary(entry: ToolDataEntry) -> dict[str, Any]:
    """Summarize one card for the journal: the called tool and its inputs, or the card and its data."""
    data = entry["data"]
    if entry["tool_name"] != TOOL_CALLS_CARD or not isinstance(data, dict):
        return {
            "type": "tool_data",
            "tool_name": entry["tool_name"],
            "detail": _truncate(json.dumps(data, default=str), 200),
        }
    return {
        "type": "tool_data",
        "tool_name": data.get("tool_name", ""),
        "detail": _truncate(json.dumps(data.get("inputs", {}), default=str), 200),
    }


def _transcript_entries(turn_text: str, turn: TurnRecord) -> list[dict[str, str]]:
    """Return what one turn adds to the judged transcript: the ask, the reply, and a reaction when one was placed."""
    entries = [{"role": "user", "content": turn_text}]
    if turn["text"]:
        entries.append({"role": "assistant", "content": turn["text"]})
    if turn["reaction"]:
        entries.append(
            {
                "role": "assistant",
                "content": f"[reaction: {turn['reaction']}]",
                "kind": REACTION_KIND,
            }
        )
    return entries


class ChatTransport:
    """Multi-turn transport over send + events, the wire every client uses."""

    #: The quality suite grades the reply that answered each message, not the write-up of
    #: work it started; a transport that grades the delivered answer waits for it.
    turn_options: ClassVar[TurnOptions] = TurnOptions(wait_for_work=False)

    def __init__(self) -> None:
        self.user_prefix: str = "quality"
        self._timeout = httpx.Timeout(connect=15.0, read=900.0, write=30.0, pool=15.0)

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg
        deadline = float(os.environ.get("EVALS_CASE_TIMEOUT_S", "300"))
        turns = turns_for(case)
        if not turns:
            raise ProviderError(provider.name, "case prompt has no turns")
        transcript: list[dict[str, str]] = []
        tool_calls: list[dict[str, Any]] = []
        final_turn_tool_calls: list[dict[str, Any]] = []
        raw: list[dict[str, Any]] = []
        text_parts: list[str] = []
        follow_up_actions: list[str] | None = None
        conversation_id = str(uuid.uuid4())
        error: str | None = None
        start = time.monotonic()

        try:
            async with asyncio.timeout(deadline):
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    email = await self._mint_user(client, provider, self.case_email(case))
                    client.headers[DEV_USER_HEADER] = email
                    for turn_text in turns:
                        turn = await self._stream_turn(client, conversation_id, turn_text)
                        transcript.extend(_transcript_entries(turn_text, turn))
                        text_parts.append(turn["text"])
                        tool_calls.extend(turn["tool_calls"])
                        final_turn_tool_calls = turn["tool_calls"]
                        raw.extend(turn["raw"])
                        if turn["error"]:
                            error = error or turn["error"]
                        if turn["follow_up_actions"] is not None:
                            follow_up_actions = turn["follow_up_actions"]
        except TimeoutError:
            error = f"case timed out after {deadline:.0f}s"
        except httpx.HTTPError as e:
            raise ProviderError(provider.name, f"chat transport failed: {e}") from e

        text = " ".join(part for part in text_parts if part).strip()
        if error:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                messages=transcript,
                tool_calls=tool_calls,
                final_turn_tool_calls=final_turn_tool_calls,
                text=text,
                raw=raw,
                duration_s=time.monotonic() - start,
                error=f"turn error: {error[:200]}",
            )

        tokens_in = estimate_tokens(
            " ".join(m["content"] for m in transcript if m["role"] == "user")
        )
        tokens_out = estimate_tokens(
            " ".join(m["content"] for m in transcript if m["role"] == "assistant")
        )
        tracker.add_manual(provider.name, tokens_in, tokens_out)
        raw.append(
            {
                "type": "usage",
                "estimated": True,
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "note": "the events stream carries no token usage; estimated via core.cost.estimate_tokens",
            }
        )
        if follow_up_actions is not None:
            raw.append({"type": "follow_up_actions_final", "actions": follow_up_actions})
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=transcript,
            tool_calls=tool_calls,
            final_turn_tool_calls=final_turn_tool_calls,
            text=text,
            raw=raw,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_s=time.monotonic() - start,
        )

    def case_email(self, case: Case) -> str:
        """Return a fresh identity per case.

        A shared account once let cases inherit each other's todos, reminders
        and agent memory, making results order-dependent and concurrency
        unsafe. capability, gaia_bench and hil already mint per case.
        """
        return f"{self.user_prefix}-{case.id[:40]}-{uuid.uuid4().hex[:8]}@gaia.local"

    async def _mint_user(
        self, client: httpx.AsyncClient, provider: ProviderConfig, email: str
    ) -> str:
        """Create this case's user and return it, rather than storing on self.

        One transport instance serves every case in a run, so storing the
        identity on self let a concurrent case overwrite it mid-run, sending
        another case's turn to a conversation it did not own.
        """
        resp = await client.post(DEV_USERS_URL, json={"email": email})
        if resp.status_code not in (200, 201):
            raise ProviderError(
                provider.name,
                f"dev users endpoint failed: HTTP {resp.status_code}: {(resp.text or '')[:200]}",
            )
        return email

    async def _stream_turn(
        self,
        client: httpx.AsyncClient,
        conversation_id: str,
        turn_text: str,
    ) -> TurnRecord:
        """Send one message into the case's conversation and record what answered it."""
        turn = await read_turn(client, DEV_API_BASE, turn_text, conversation_id, self.turn_options)
        return turn_record(turn)


def _suggestion_check(run: CaseRun) -> tuple[float, str]:
    """Real suggestion gate: last follow_up_actions frame, 3-4 short items.

    Reads raw (the follow_up_actions frame summary), which the finalize
    replay does not carry yet (see report).
    """
    actions: list[str] | None = None
    for frame in reversed(run.raw):
        if frame.get("type") == "follow_up_actions":
            actions = frame.get("actions")
            break
    if actions is None:
        return 0.0, "no follow_up_actions frame in stream"
    if not actions:
        return 0.0, "follow_up_actions frame was empty"
    if not 3 <= len(actions) <= 4:
        return 0.0, f"{len(actions)} suggestions (expected 3-4)"
    bad = [a for a in actions if not a.strip() or len(a) > 50]
    if bad:
        return 0.0, f"bad suggestion item(s): {bad[:3]}"
    return 1.0, f"{len(actions)} suggestions, all non-empty and <=50 chars"


# Pictographic ranges only. Deliberately excludes U+2100-27BF (™, ←, ✓, ▶) and
# the U+FE0F variation selector: those appear in ordinary punctuation and would
# make the check fire on text carrying no emoji at all.
_EMOJI_PATTERN = re.compile(
    "[\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f900-\U0001f9ff"  # supplemental symbols & pictographs
    "\U0001fa70-\U0001faff"  # extended-A (🩵, 🫶)
    "☀-⛿]"  # miscellaneous symbols (☀, ⚡)
)


def _emoji_discipline_check(run: CaseRun) -> tuple[float, str]:
    """Fail if the assistant used an emoji before the user has used one.

    A verbatim, deterministically gradeable prompt rule; walks the transcript
    in order so a user who opens with an emoji permits an emoji reply.
    Caught live: "add a todo to water the plants" came back as "aight, add
    kar raha hoon Inbox me 🌱", passing every other structural gate.
    """
    if produced_nothing(run.messages, run.tool_calls, run.text):
        return 0.0, NOTHING_TO_INSPECT
    user_has_emojied = False
    for message in run.messages:
        content = str(message.get("content") or "")
        if message.get("role") == "user":
            user_has_emojied = user_has_emojied or bool(_EMOJI_PATTERN.search(content))
            continue
        if message.get("role") != "assistant" or user_has_emojied:
            continue
        if message.get("kind") == REACTION_KIND:
            continue
        found = _EMOJI_PATTERN.findall(content)
        if found:
            return 0.0, f"assistant used {''.join(found[:4])} before the user used any emoji"
    return 1.0, "no emoji before the user's first"


class OpenUIPolicyError(ValueError):
    """A case's openui_policy cannot be resolved against the shipped prompt.

    Its own error type so the case-id prefix is only ever attached to failures
    that really are the case's fault. Catching bare ValueError here meant a
    pydantic ValidationError — which IS a ValueError — got relabelled as a
    broken case, so a missing env var read as "quality-openui-…: 1 validation
    error for DevelopmentSettings".
    """


#: Directions a case can take on the OpenUI surface policy, via
#: expected.openui_policy, mapped to the shipped prompt clauses that decide
#: it. Replaces a prose rubric that froze its own copy and drifted from the prompt.
OPENUI_POLICY_CONTRACTS: dict[str, tuple[str, ...]] = {
    "required": (
        "openui.rule_structured_data",
        "openui.prose_and_component_are_layers",
        "openui.how_to_emit",
    ),
    "forbidden": (
        "openui.rule_plain_text",
        "openui.never_openui_in_conversation",
    ),
    "suppressed": ("openui.rule_native_card",),
}

OPENUI_POLICY_DIRECTIONS = tuple(OPENUI_POLICY_CONTRACTS)


def openui_policy_criteria(direction: str) -> list[str]:
    """Return judge criteria composed from the real OpenUI prompt, not paraphrased.

    Quotes OPENUI_SURFACE_POLICY verbatim, so a prompt edit changes what
    these cases grade with no YAML to update; rule_native_card's suppressed
    tool list comes from the same interpolated prompt text.
    """
    refs = OPENUI_POLICY_CONTRACTS.get(direction)
    if refs is None:
        raise OpenUIPolicyError(
            f"unknown openui_policy {direction!r}; expected one of {OPENUI_POLICY_DIRECTIONS}"
        )
    return contract_criteria(list(refs))


def _apply_openui_policy_criteria(case_id: str, expected: TurnPayload) -> None:
    """Append policy-derived criteria to a case that opts in.

    Cases declare openui_policy: required|forbidden|suppressed and get the
    shipped policy's own words appended to their rubric. Case-specific criteria
    written in YAML are kept — they say what THIS request is, the imported ones
    say what the product promises.
    """
    direction = expected.get("openui_policy")
    if not direction:
        return
    try:
        derived = openui_policy_criteria(str(direction))
    except ClauseResolutionError as e:
        raise ClauseResolutionError(f"{case_id}: {e}") from e
    except OpenUIPolicyError as e:
        # Deliberately narrow: catching bare ValueError once let pydantic's
        # ValidationError (e.g. an empty E2B_DOMAIN) surface as a broken
        # case instead of the config failure it actually was.
        raise OpenUIPolicyError(f"{case_id}: {e}") from e
    judge = expected.setdefault("judge", {})
    judge["criteria"] = list(judge.get("criteria") or []) + derived


def _reject_unfalsifiable_openui_gate(case: Case) -> None:
    """Openui as a gate on a case declaring openui: false cannot go red.

    OpenUICheck returns 1.0 without reading anything in that branch, so the
    gate carries the authority of a hard check while being incapable of failing
    — worse than no gate at all. Neither the forgery sweep nor the inert check
    can see it: the gate does produce a value, it just always produces 1.0.
    """
    expected = case.expected
    if "openui" in case.gates and not expected.get("openui"):
        raise ValueError(
            f"quality case {case.id}: gates 'openui' while declaring openui="
            f"{expected.get('openui')!r}. OpenUICheck scores 1.0 unconditionally there, so the "
            f"gate can never fail. Record it as a metric (drop it from score.gates), or set "
            f"openui: true if a fence really is required."
        )


def _tool_card_gate(case: Case, run: CaseRun) -> float:
    del case
    result = ToolCard().score(tool_calls=run.tool_calls, messages=run.messages, output=run.text)
    return float(result.value)


def _final_turn_delegation_gate(case: Case, run: CaseRun) -> float:
    """expected.delegation, judged on the last turn alone: an earlier hand-off cannot satisfy it."""
    result = DelegationGate().score(
        output=run.text,
        tool_calls=run.final_turn_tool_calls,
        expected=case.expected,
        messages=run.messages,
    )
    return float(result.value)


def _openui_gate(case: Case, run: CaseRun) -> float:
    return float(OpenUICheck().score(output=run.text, expected=case.expected).value)


def _recorded(
    name: str, check: Callable[[CaseRun], tuple[float, str]]
) -> Callable[[Case, CaseRun], float]:
    """Adapt a (run) -> (value, reason) check to the gate signature.

    The reason is journaled on the run so the report can explain a red gate;
    that side effect is why these are not plain lambdas.
    """

    def gate(case: Case, run: CaseRun) -> float:
        del case
        value, reason = check(run)
        run.raw.append({"type": f"{name}_check", "value": value, "reason": reason})
        return value

    return gate


#: Gates this suite adds to the shared set in ``core/gates.py``. Everything else
#: a case may declare comes from there, so a name means the same thing in every
#: suite instead of being re-implemented here.
QUALITY_GATES: ExtraGates = {
    "tool_card": _tool_card_gate,
    "openui": _openui_gate,
    "final_turn_delegation": _final_turn_delegation_gate,
    "emoji_discipline": _recorded("emoji", _emoji_discipline_check),
    "suggestion": _recorded("suggestion", _suggestion_check),
    **{name: _recorded(name, check) for name, check in PROMPT_GATES.items()},
}

#: Recorded on every case, gated or not: the prompt-derived ones state an
#: absolute with no exceptions (dashes, banned phrases, ONE ENTITY, routing
#: markers), so a case does not opt in to a rule that applies to every reply.
ALWAYS_SCORED: tuple[str, ...] = (
    "bubble_boundary",
    "tool_card",
    "emoji_discipline",
    *PROMPT_GATES,
)

#: A gate also recorded as a metric when the ``expected`` field that gives it
#: meaning is present, even on a case that does not gate it.
METRIC_WHEN_PRESENT: dict[str, str] = {
    "communicate": "communicate",
    "tool_call_correctness": "tool_calls",
    "no_forbidden_tools": "must_not_call_tools",
    "must_not_communicate": "must_not_communicate",
    "delegation": "delegation",
    "suggestion": "suggestions",
    "openui": "openui",
}

#: openui: false used to be recorded too, but OpenUICheck's false branch
#: returns 1.0 without reading the output, so recording it fed a constant
#: 1.0 into overall and inflated the mean the more cases declared it.


@register_suite("quality")
class QualitySuite(Suite):
    name = "quality"
    project = "gaia-quality"
    label = "Quality"

    EXTRA_GATES: ClassVar[ExtraGates] = QUALITY_GATES

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._transport = ChatTransport()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is not None:
            return self._cases
        cases: list[Case] = []
        seen_ids: set[str] = set()
        for path in sorted(DATA_DIR.glob("*.yaml")):
            rows = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError(f"{path}: expected a YAML list of cases")
            for row in rows:
                row = dict(row)
                case_id = row.pop("id")
                if case_id in seen_ids:
                    raise ValueError(f"duplicate case id {case_id!r} in {path}")
                seen_ids.add(case_id)
                expected = row.pop("expected")
                _apply_openui_policy_criteria(case_id, expected)
                case = Case(
                    id=case_id,
                    ticket=row.pop("ticket", ""),
                    prompt=row.pop("prompt", ""),
                    expected=expected,
                    tags=row.pop("tags", []),
                    setup=row.pop("setup", {}),
                )
                validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
                _reject_unfalsifiable_openui_gate(case)
                cases.append(case)
        if not cases:
            raise ValueError(f"no quality cases found in {DATA_DIR}")
        self._cases = cases
        return cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        """Score suite metrics, then the declared gates through the shared dispatcher.

        Separate on purpose: a METRIC is recorded because the case carries
        the field that gives it meaning and shows in the report; a GATE
        decides pass/fail. score_gates guarantees every declared gate has an
        entry, since a missing key reads back as 0.0 and can never pass.
        """
        available = known_gates(self.EXTRA_GATES)
        scores = {name: available[name](case, run) for name in ALWAYS_SCORED}
        for gate, field in METRIC_WHEN_PRESENT.items():
            if case.expected.get(field):
                scores[gate] = available[gate](case, run)
        gate_scores = score_gates(case, run, self.EXTRA_GATES)
        gate_scores.pop("overall", None)
        scores.update(gate_scores)
        scores["overall"] = round(sum(scores.values()) / len(scores), 3) if scores else 0.0
        return scores

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        return [
            CommunicateGate(),
            BubbleBoundary(),
            ToolCard(),
            RubricJudge(
                base_url=os.environ.get("DEV_LLM_BASE_URL", ""),
                api_key=os.environ.get("DEV_LLM_API_KEY", ""),
                model=judge_model(cfg),
            ),
        ]
