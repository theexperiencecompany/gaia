"""Prove a case's gates can actually fail, without running the agent.

A gate written from the pass side encodes *a good answer contains X*. A gate
written from the fail side encodes *a bad answer cannot fake X*. Only the second
is a test, and the difference is invisible in a run: a gate that cannot go red
and a gate the agent happened to satisfy produce the same green.

So each case is scored against deliberately worthless runs. Every declared gate
must reject them. Two levels, in increasing strength:

* **empty** — a run that produced nothing at all: no text, no tool calls, no
  world change. Needs no authoring, applies to every case ever written, and
  catches the gate that is structurally incapable of failing.
* **echo** — a run that says the prompt back and does nothing. Catches the gate
  satisfied by words the user already supplied.
* **counterfeit** — an optional per-case ``counterfeit:`` block: a hand-written
  wrong answer built to be as sneaky as the author can make it. This is the one
  that catches gates faked by a plausible-looking wrong answer.

Nothing here calls a model or a database, so it belongs in CI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import GATE_PASS_THRESHOLD, Case, CaseRun


class Scorable(Protocol):
    """The part of a suite this check needs: its real scoring path."""

    name: str

    def score(self, case: Case, run: CaseRun) -> dict[str, float]: ...


@dataclass(frozen=True)
class Forgery:
    """One worthless run, and what it is meant to prove a gate rejects."""

    label: str
    run: CaseRun
    proves: str


@dataclass
class CaseVerdict:
    """Which of a case's gates failed to reject a worthless run.

    Two severities, and the difference matters: the run loop passes a case only
    when EVERY gate passes, so one weak gate beside a strong one still yields a
    case that fails correctly. Only a case where a single forgery satisfies ALL
    its gates is actually incapable of failing.
    """

    case_id: str
    suite: str
    fooled: dict[str, list[str]]  # gate name -> forgery labels that fooled it
    gates: list[str]
    inert: list[str] = field(default_factory=list)  # declared, but the suite scores nothing
    passed_wholesale: list[str] = field(default_factory=list)  # forgeries that passed every gate
    parroted: list[str] = field(
        default_factory=list
    )  # communicate terms the prompt already supplies
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.fooled and not self.error and not self.inert

    @property
    def unfalsifiable(self) -> bool:
        """A run that produced NOTHING would have been recorded as a pass.

        This is always a defect: no transcript, no tool call, no world change,
        and the case still scored green.
        """
        return "empty" in self.passed_wholesale or "counterfeit" in self.passed_wholesale

    @property
    def content_blind(self) -> bool:
        """Passes a reply that only parrots the prompt back.

        NOT automatically a bug. A case whose gates are purely structural or
        absence-based ("did not delegate a greeting", "produced one clean
        bubble") is doing its stated job, and an echo satisfying it is a
        property of what it set out to test rather than a hole in it. It does
        mean the case asserts nothing about *what the agent actually said*, so
        it is worth seeing — and worth fixing wherever content is the point.
        """
        return "echo" in self.passed_wholesale and not self.unfalsifiable

    judge_criteria: int = 0

    @property
    def judge_only(self) -> bool:
        """No runtime gate, but the judge grades it at finalize.

        Weaker than a real gate and worth seeing separately: the judge runs only
        when a run finalizes, so at runtime such a case cannot fail at all.
        """
        return not self.gates and self.judge_criteria > 0

    @property
    def ungated(self) -> bool:
        """Nothing can ever fail this case — no gate, and nothing to judge."""
        return not self.gates and self.judge_criteria == 0


def _empty_run(case: Case) -> CaseRun:
    return CaseRun(case_id=case.id, messages=[], tool_calls=[], end_state={}, text="")


def _echo_run(case: Case) -> CaseRun:
    """Says the user's own words back and does nothing else."""
    return CaseRun(
        case_id=case.id,
        messages=[
            {"role": "user", "content": case.prompt},
            {"role": "assistant", "content": case.prompt},
        ],
        tool_calls=[],
        end_state={},
        text=case.prompt,
    )


def _self_scored(suite: Scorable) -> frozenset[str]:
    """Gates the suite computes from its transport's own end state.

    A benchmark verdict — ``gaia_exact``, ``probes`` — is derived from a payload
    only a real run of that suite produces, so a synthetic run legitimately
    yields nothing for it and its absence here is not evidence of a defect.
    Those names are covered instead by ``gates.validate_gates`` at load time.
    """
    extra = getattr(suite, "EXTRA_GATES", None)
    if not isinstance(extra, Mapping):
        return frozenset()
    return frozenset(name for name, scorer in extra.items() if scorer is None)


def _plausible_run(case: Case) -> CaseRun:
    """A run that did plenty of everything, used only to ask whether each
    declared gate produces a value. Its scores are never judged — only the
    presence of the keys is."""
    return CaseRun(
        case_id=case.id,
        messages=[
            {"role": "user", "content": case.prompt},
            {"role": "assistant", "content": "an answer with real content in it"},
        ],
        tool_calls=[{"name": "create_todo", "args": {"title": "something"}}],
        end_state={"verdict": "refuse"},
        text="an answer with real content in it",
    )


def _authored_run(case: Case) -> CaseRun | None:
    """The case's own ``counterfeit:`` block, if its author wrote one."""
    block = case.setup.get("counterfeit") if isinstance(case.setup, dict) else None
    if not isinstance(block, dict):
        return None
    messages = block.get("messages")
    text = str(block.get("text", ""))
    return CaseRun(
        case_id=case.id,
        messages=messages
        if isinstance(messages, list)
        else ([{"role": "assistant", "content": text}] if text else []),
        tool_calls=block.get("tool_calls") if isinstance(block.get("tool_calls"), list) else [],
        end_state=block.get("end_state") if isinstance(block.get("end_state"), dict) else {},
        text=text,
    )


def parroted_assertions(case: Case) -> list[str]:
    """``communicate`` strings the user's own prompt already contains.

    A presence assertion the prompt supplies can be satisfied by repeating the
    question back, so it credits the agent for nothing. This is reported rather
    than rejected: for a recall case ("remember my order is a large oat latte")
    the word genuinely does belong in both, and the case is honest as long as a
    stronger gate stands beside it. Assert the value where it is authoritative —
    the database — and keep prose assertions for tokens that cannot arrive by
    accident.

    Absence assertions are deliberately excluded: an injection canary belongs in
    the prompt, because the prompt IS the attack.
    """
    prompt = case.prompt.lower()
    required = case.expected.get("communicate") or []
    return [str(term) for term in required if str(term).strip().lower() in prompt]


def forgeries(case: Case) -> list[Forgery]:
    out = [
        Forgery("empty", _empty_run(case), "gate can reach 0.0 at all"),
        Forgery("echo", _echo_run(case), "gate is not satisfied by the user's own words"),
    ]
    authored = _authored_run(case)
    if authored is not None:
        out.append(Forgery("counterfeit", authored, "gate rejects a plausible wrong answer"))
    return out


def check_case(suite: Scorable, case: Case) -> CaseVerdict:
    """Score every forgery through the suite's real scorer."""
    verdict = CaseVerdict(
        case_id=case.id,
        suite=suite.name,
        fooled={},
        gates=case.gates,
        parroted=parroted_assertions(case),
        judge_criteria=len((case.expected.get("judge") or {}).get("criteria") or []),
    )
    if not verdict.gates:
        return verdict
    # The blind spot this check closes: a gate the suite never scores rejects
    # every forgery, so it looks PROVEN while being incapable of passing —
    # `_status_from_scores` reads a missing gate back as 0.0. Ask the opposite
    # question first: on a run that did plenty of everything, does each declared
    # gate produce a value at all?
    try:
        scored = suite.score(case, _plausible_run(case))
        verdict.inert = [
            gate for gate in case.gates if gate not in scored and gate not in _self_scored(suite)
        ]
    except Exception as e:
        verdict.error = f"plausible: {type(e).__name__}: {e}"
        return verdict
    for forgery in forgeries(case):
        try:
            scores = suite.score(case, forgery.run)
        except Exception as e:
            # A scorer that raises on an empty run is its own defect: the run
            # loop would journal it as a failed case rather than a broken gate.
            verdict.error = f"{forgery.label}: {type(e).__name__}: {e}"
            return verdict
        satisfied = [g for g in case.gates if scores.get(g, 0.0) >= GATE_PASS_THRESHOLD]
        for gate in satisfied:
            verdict.fooled.setdefault(gate, []).append(forgery.label)
        if len(satisfied) == len(case.gates):
            verdict.passed_wholesale.append(forgery.label)
    return verdict


def check_suite(suite: Scorable, cases: list[Case]) -> list[CaseVerdict]:
    return [check_case(suite, case) for case in cases]


def format_report(verdicts: list[CaseVerdict]) -> str:
    """A report that leads with the number, because that is the decision."""
    total = len(verdicts)
    ungated = [v for v in verdicts if v.ungated]
    judge_only = [v for v in verdicts if v.judge_only]
    errored = [v for v in verdicts if v.error]
    inert = [v for v in verdicts if v.inert]
    broken = [v for v in verdicts if v.unfalsifiable and not v.ungated]
    blind = [v for v in verdicts if v.content_blind and not v.ungated and not v.inert]
    weak = [
        v
        for v in verdicts
        if v.fooled and not v.unfalsifiable and not v.content_blind and not v.inert
    ]
    solid = (
        total
        - len(ungated)
        - len(judge_only)
        - len(errored)
        - len(inert)
        - len(broken)
        - len(blind)
        - len(weak)
    )
    cannot_fail = len(broken) + len(ungated)

    lines = [
        "",
        "=" * 74,
        f"FALSIFIABILITY  {cannot_fail}/{total} cases CANNOT FAIL — a worthless run would pass them",
        "=" * 74,
        f"  {len(broken):>4}  BROKEN   — a run that produced NOTHING scored a pass",
        f"  {len(inert):>4}  INERT    — declares a gate its suite never scores, so the runner",
        "        reads it back as 0.0: the case can never PASS, whatever the agent did",
        f"  {len(ungated):>4}  ungated  — no gate and no judge criteria: nothing can fail it",
        f"  {len(judge_only):>4}  judge-only — no runtime gate; graded only when a run finalizes",
        f"  {len(blind):>4}  content-blind — passes a reply that only parrots the prompt;",
        "        structural/absence gates only, so it asserts nothing about what was said",
        f"  {len(weak):>4}  weak     — one gate is fakeable, but another still rejects the run",
        f"  {solid:>4}  proven   — every gate rejected every forgery",
        f"  {len(errored):>4}  errored  — the scorer raised on a worthless run",
    ]
    if inert:
        lines.append("\nINERT gates (the case cannot pass — fix the suite or the gate name):")
        for verdict in inert[:20]:
            lines.append(
                f"  {verdict.suite:<12} {verdict.case_id:<46} never scored: {','.join(verdict.inert)}"
            )
    if broken:
        lines.append("\nBROKEN cases (these are the ones that matter):")
        for verdict in broken[:40]:
            lines.append(
                f"  {verdict.suite:<12} {verdict.case_id:<46} "
                f"gates={','.join(verdict.gates)} via {'/'.join(verdict.passed_wholesale)}"
            )
    by_gate: dict[str, int] = {}
    for verdict in broken + blind + weak:
        for gate in verdict.fooled:
            by_gate[gate] = by_gate.get(gate, 0) + 1
    if by_gate:
        lines.append("\nfooled gates, by how many cases they affect:")
        for gate, n in sorted(by_gate.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {n:>4}  {gate}")
    if weak:
        lines.append("\nweak gates (case still fails, but the gate is fakeable) — first 15:")
        for verdict in weak[:15]:
            detail = ", ".join(f"{g} ({'/'.join(labels)})" for g, labels in verdict.fooled.items())
            lines.append(f"  {verdict.suite:<12} {verdict.case_id:<44} {detail}")
    if errored:
        lines.append("\nscorers that raised:")
        for verdict in errored[:15]:
            lines.append(f"  {verdict.suite:<12} {verdict.case_id:<44} {verdict.error}")
    if ungated:
        lines.append(
            f"\nungated cases ({len(ungated)}): " + ", ".join(v.case_id for v in ungated[:20])
        )
    lines.append("")
    return "\n".join(lines)


def summary_counts(verdicts: list[CaseVerdict]) -> dict[str, Any]:
    return {
        "total": len(verdicts),
        "inert": len([v for v in verdicts if v.inert]),
        "broken": len([v for v in verdicts if v.unfalsifiable and not v.ungated]),
        "content_blind": len([v for v in verdicts if v.content_blind and not v.ungated]),
        "weak": len(
            [
                v
                for v in verdicts
                if v.fooled and not v.unfalsifiable and not v.content_blind and not v.inert
            ]
        ),
        "ungated": len([v for v in verdicts if v.ungated]),
        "errored": len([v for v in verdicts if v.error]),
    }
