"""Scenarios as data: load the YAML files and check each scenario's own expectations.

A step is one of:
  send: <text>                     burst: [<text>, ...] (gap: s)      sleep: <s>
  wait_reply: {quiet, timeout}     wait_for: approval_prompt | bot_message (timeout: s)
  wait_bubbles: {count, timeout}   until the run has shown at least count bot bubbles
  set_tool_ask: {tool, ask}        restart_bot: {down}
Texts and patterns may use {nonce}, a token unique to the run.

An expectation is one key plus optional `loose:` (why it reads model text) and `severity: warn`.
Message indexes count my sent messages from 0.
  contains: {after, pattern, within_s?}          a bubble after message N matches (needs loose)
  distinct_answers: [pattern per question]       separate answers are told apart (needs loose)
  arrives: {after, pattern, min_delay_s, count}  a proactive message arrives count times (needs loose)
  prompts: <n>                                   exactly n approval prompts were shown
  reaction: <message index>                      a reaction landed on that message
  todos: [{tag, exists, priority?}]              the todo titled with {nonce} and tag exists or not
  approval_numbers: {tags, decisions}            "yes N"/"no N" decided the approvals shown as N
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from edge_invariants import Budgets, Violation, is_approval_prompt, prompt_items
from edge_transcript import Transcript
import yaml

SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
STEP_KINDS = frozenset(
    {
        "send",
        "burst",
        "sleep",
        "wait_reply",
        "wait_for",
        "wait_bubbles",
        "set_tool_ask",
        "restart_bot",
    }
)
WAIT_TARGETS = frozenset({"approval_prompt", "bot_message"})
EXPECTATION_KINDS = frozenset(
    {"contains", "distinct_answers", "arrives", "prompts", "reaction", "todos", "approval_numbers"}
)
TEXT_EXPECTATIONS = frozenset({"contains", "distinct_answers", "arrives"})
# Work can run for a while with nothing on screen; a scenario ends only after this long with no change.
DEFAULT_SETTLE_S = 20.0
SEVERITIES = frozenset({"fail", "warn"})

Todo = dict[str, object]


@dataclass
class TodoWant:
    """A todo the run must (or must not) have created."""

    tag: str
    exists: bool
    priority: str | None = None


@dataclass
class Expectation:
    """One scenario-specific check, parsed from YAML."""

    kind: str
    after: int = 0
    pattern: str = ""
    within_s: float | None = None
    min_delay_s: float = 0.0
    count: int = 1
    patterns: list[str] = field(default_factory=list)
    todos: list[TodoWant] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    decisions: dict[int, bool] = field(default_factory=dict)
    loose: str = ""
    severity: str = "fail"


@dataclass
class Scenario:
    """One scenario file, with the run's nonce already filled in."""

    name: str
    description: str
    steps: list[dict[str, object]]
    expect: list[Expectation] = field(default_factory=list)
    budgets: Budgets = field(default_factory=Budgets)
    settle_s: float = DEFAULT_SETTLE_S
    fresh: bool = True

    @property
    def needs_restart(self) -> bool:
        """Whether a step restarts the bot."""
        return any("restart_bot" in step for step in self.steps)


def _fill(value: object, nonce: str) -> object:
    if isinstance(value, str):
        return value.replace("{nonce}", nonce)
    if isinstance(value, list):
        return [_fill(v, nonce) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, nonce) for k, v in value.items()}
    return value


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{where}: expected a mapping, got {value!r}")
    return {str(k): v for k, v in value.items()}


def _items(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{where}: expected a list, got {value!r}")
    return value


def _kind(spec: dict[str, object], allowed: frozenset[str], where: str) -> str:
    kinds = [k for k in spec if k in allowed]
    if len(kinds) != 1:
        raise ValueError(f"{where}: needs exactly one of {sorted(allowed)}, got {sorted(spec)}")
    return kinds[0]


def _parse_step(raw: object, where: str) -> dict[str, object]:
    step = _mapping(raw, where)
    if _kind(step, STEP_KINDS, where) == "wait_for" and step["wait_for"] not in WAIT_TARGETS:
        raise ValueError(f"{where}: wait_for must be one of {sorted(WAIT_TARGETS)}")
    return step


def _parse_expectation(raw: object, where: str) -> Expectation:
    spec = _mapping(raw, where)
    kind = _kind(spec, EXPECTATION_KINDS, where)
    loose = str(spec.get("loose", ""))
    severity = str(spec.get("severity", "fail"))
    if kind in TEXT_EXPECTATIONS and not loose:
        raise ValueError(f"{where}: {kind} reads model text, so it must say why in `loose:`")
    if severity not in SEVERITIES:
        raise ValueError(f"{where}: severity must be one of {sorted(SEVERITIES)}")
    value = spec[kind]
    exp = Expectation(kind=kind, loose=loose, severity=severity)
    if kind in {"contains", "arrives"}:
        body = _mapping(value, where)
        exp.after = int(str(body["after"]))
        exp.pattern = str(body["pattern"])
        exp.within_s = float(str(body["within_s"])) if "within_s" in body else None
        exp.min_delay_s = float(str(body.get("min_delay_s", 0)))
        exp.count = int(str(body.get("count", 1)))
    elif kind == "distinct_answers":
        exp.patterns = [str(p) for p in _items(value, where)]
    elif kind == "prompts":
        exp.count = int(str(value))
    elif kind == "reaction":
        exp.after = int(str(value))
    elif kind == "todos":
        for item in _items(value, where):
            want = _mapping(item, where)
            priority = want.get("priority")
            exp.todos.append(
                TodoWant(
                    str(want["tag"]), bool(want["exists"]), str(priority) if priority else None
                )
            )
    elif kind == "approval_numbers":
        body = _mapping(value, where)
        exp.tags = [str(t) for t in _items(body["tags"], where)]
        exp.decisions = {
            int(str(n)): str(d) == "yes" for n, d in _mapping(body["decisions"], where).items()
        }
    else:
        raise ValueError(f"{where}: unknown expectation {kind}")
    return exp


def parse_scenario(raw: object, nonce: str) -> Scenario:
    """Validate one scenario's YAML and fill in the nonce; raise on anything malformed."""
    doc = _mapping(_fill(raw, nonce), "scenario")
    name = str(doc["name"])
    steps = [_parse_step(s, f"{name} step {i}") for i, s in enumerate(_items(doc["steps"], name))]
    if not steps:
        raise ValueError(f"{name}: steps must not be empty")
    expect = [
        _parse_expectation(e, f"{name} expectation {i}")
        for i, e in enumerate(_items(doc.get("expect", []), name))
    ]
    budgets = _mapping(doc.get("budgets", {}), f"{name} budgets")
    return Scenario(
        name=name,
        description=str(doc.get("description", "")),
        steps=steps,
        expect=expect,
        budgets=Budgets(
            first_response_s=float(str(budgets.get("first_response_s", Budgets.first_response_s)))
        ),
        settle_s=float(str(doc.get("settle_s", DEFAULT_SETTLE_S))),
        fresh=bool(doc.get("fresh", True)),
    )


def load_scenarios(nonce: str, directory: Path = SCENARIO_DIR) -> list[Scenario]:
    """Every scenario file in the directory, sorted by file name."""
    return [
        parse_scenario(yaml.safe_load(p.read_text()), nonce)
        for p in sorted(directory.glob("*.yaml"))
    ]


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _contains(t: Transcript, exp: Expectation) -> list[Violation]:
    sent = t.sent[exp.after]
    deadline = sent.sent_at + exp.within_s if exp.within_s is not None else t.ended_at
    shown = [
        s.at for m in t.bot_after(sent.sent_at) for s in m.states if _matches(exp.pattern, s.text)
    ]
    if any(at <= deadline for at in shown):
        return []
    where = f"within {exp.within_s:g}s" if exp.within_s is not None else "before the end"
    first = f", first at +{min(shown) - sent.sent_at:.1f}s" if shown else ""
    return [
        Violation(
            "contains",
            f"no bubble after {sent.id} matched /{exp.pattern}/ {where}{first}",
            {"loose": exp.loose},
        )
    ]


def _distinct_answers(t: Transcript, exp: Expectation) -> list[Violation]:
    """One bubble answers every question, or each question's answer quotes it."""
    bubbles = t.bot_after(t.sent[0].sent_at)
    if any(all(_matches(p, m.text) for p in exp.patterns) for m in bubbles):
        return []
    out = []
    for sent, pattern in zip(t.sent, exp.patterns, strict=False):
        answers = [m for m in bubbles if _matches(pattern, m.text)]
        if not answers:
            out.append(
                Violation(
                    "distinct_answers",
                    f"no answer to message {sent.id} matched /{pattern}/",
                    {"loose": exp.loose},
                )
            )
        elif not any(m.reply_to == sent.id for m in answers):
            out.append(
                Violation(
                    "distinct_answers",
                    f"message {sent.id} was answered in its own bubble that does not quote it",
                    {"bubbles": [m.id for m in answers], "loose": exp.loose},
                )
            )
    return out


def _prompts(t: Transcript, exp: Expectation) -> list[Violation]:
    prompts = [m.id for m in t.bot if is_approval_prompt(m)]
    if len(prompts) == exp.count:
        return []
    return [
        Violation(
            "prompts",
            f"{len(prompts)} approval prompts shown, expected {exp.count}",
            {"prompts": prompts},
        )
    ]


def _reaction(t: Transcript, exp: Expectation) -> list[Violation]:
    sent = t.sent[exp.after]
    if sent.first_reaction_at is not None:
        return []
    return [Violation("reaction", f"no reaction on message {sent.id}", {"sent": sent.text})]


def _arrives(t: Transcript, exp: Expectation) -> list[Violation]:
    sent = t.sent[exp.after]
    got = [
        m.id for m in t.bot_after(sent.sent_at + exp.min_delay_s) if _matches(exp.pattern, m.text)
    ]
    if len(got) == exp.count:
        return []
    return [
        Violation(
            "arrives",
            f"{len(got)} bubbles matching /{exp.pattern}/ arrived {exp.min_delay_s:g}s+ after {sent.id}, expected {exp.count}",
            {"bubbles": got, "loose": exp.loose},
        )
    ]


def _check_todos(wants: list[TodoWant], todos: list[Todo], nonce: str) -> list[Violation]:
    out = []
    for want in wants:
        found = [
            t
            for t in todos
            if nonce.lower() in str(t["title"]).lower()
            and want.tag.lower() in str(t["title"]).lower()
        ]
        titles = [t["title"] for t in found]
        if want.exists and len(found) != 1:
            out.append(
                Violation(
                    "todos",
                    f"expected one todo tagged {want.tag}, found {len(found)}",
                    {"titles": titles},
                )
            )
        elif not want.exists and found:
            out.append(
                Violation(
                    "todos",
                    f"todo tagged {want.tag} exists though it was denied",
                    {"titles": titles},
                )
            )
        elif found and want.priority and found[0].get("priority") != want.priority:
            out.append(
                Violation(
                    "todos",
                    f"todo tagged {want.tag} has priority {found[0].get('priority')}, expected {want.priority}",
                    {},
                )
            )
    return out


def _approval_numbers(
    t: Transcript, exp: Expectation, todos: list[Todo], nonce: str
) -> list[Violation]:
    """Map each number to the tag its prompt line named, then check the decision on that tag."""
    numbers: dict[int, str] = {}
    for m in t.bot:
        if is_approval_prompt(m):
            for n, line in prompt_items(m):
                tag = next((tg for tg in exp.tags if tg.lower() in line.lower()), None)
                if tag is not None:
                    numbers.setdefault(n, tag)
    out = [
        Violation("approval_numbers", f"no prompt showed approval number {n}", {"numbers": numbers})
        for n in exp.decisions
        if n not in numbers
    ]
    wants = [TodoWant(numbers[n], approve) for n, approve in exp.decisions.items() if n in numbers]
    return out + _check_todos(wants, todos, nonce)


def check_expectations(
    scenario: Scenario, t: Transcript, todos: list[Todo], nonce: str
) -> list[Violation]:
    """Check a scenario's own expectations against its transcript and the user's todos."""
    out: list[Violation] = []
    for exp in scenario.expect:
        if exp.kind == "contains":
            found = _contains(t, exp)
        elif exp.kind == "distinct_answers":
            found = _distinct_answers(t, exp)
        elif exp.kind == "arrives":
            found = _arrives(t, exp)
        elif exp.kind == "prompts":
            found = _prompts(t, exp)
        elif exp.kind == "reaction":
            found = _reaction(t, exp)
        elif exp.kind == "todos":
            found = _check_todos(exp.todos, todos, nonce)
        else:
            found = _approval_numbers(t, exp, todos, nonce)
        for v in found:
            v.severity = exp.severity
        out += found
    return out
