"""User-visible invariants that must hold on every scenario's transcript, whatever the model says.

Each invariant reads only what the Telegram client showed: my messages, the bot's bubbles and
every text they showed, quotes and reactions. None asserts wording. The approval prompt is
recognised by the bot's fixed prompt copy (libs/shared/ts/src/bots/conversation/approval-prompt.ts),
which is product text, not model output.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import re

from edge_transcript import BotMessage, SentMessage, Transcript

# The fixed lines every bot approval prompt carries (APPROVAL_PROMPT_COPY).
APPROVAL_PROMPT_MARKERS = ("Reply yes or no", "need your OK", "needs your OK")
NUMBERED_ITEM = re.compile(r"^(\d+)\. (.+)$", re.MULTILINE)
STOP_COMMAND = "/stop"

# Internals the user must never see, in any text a bubble ever showed.
LEAKS: dict[str, re.Pattern[str]] = {
    "openui block": re.compile(r":::\s*openui|:::\s*$|root = Stack\(", re.MULTILINE),
    "sandbox path": re.compile(r"/workspace/|/sessions/[0-9a-f-]{8,}"),
    "item handle": re.compile(r"\[#\d+\]"),
    "tool call id": re.compile(r"\bcall_[A-Za-z0-9]{12,}"),
    "raw tool markup": re.compile(r"</?(tool|function|invoke|thinking)[ >]|\[\[(tool|say):"),
    "traceback": re.compile(r"Traceback \(most recent call last\)"),
}
# Markdown the bot must have converted to Telegram entities: checked on the final text only,
# since a bubble mid-stream may hold half of a pair it has not closed yet.
RAW_MARKDOWN: dict[str, re.Pattern[str]] = {
    "bold markers": re.compile(r"\*\*\S[^*\n]*\*\*"),
    "markdown link": re.compile(r"\[[^\]\n]+\]\((https?://|/)[^)\s]+\)"),
    "heading": re.compile(r"^#{1,6} \S", re.MULTILINE),
    "html tag": re.compile(r"</?(b|i|u|s|a|code|pre|br|p|div|span)( [^>]*)?>"),
}
REPEATED_LINE_MIN_CHARS = 40
DUPLICATE_BUBBLE_MIN_CHARS = 20
STOP_EDIT_GRACE_S = 3.0


@dataclass
class Budgets:
    """Latency budgets for one scenario, in seconds."""

    first_response_s: float = 20.0


@dataclass
class Violation:
    """One broken invariant, with the evidence a reader needs to find it."""

    invariant: str
    message: str
    evidence: dict[str, object] = field(default_factory=dict)
    severity: str = "fail"


def first_response_at(t: Transcript, sent: SentMessage) -> float | None:
    """When the user first saw anything answer this message: a reaction on it or a new bubble."""
    candidates = [m.created_at for m in t.bot_after(sent.sent_at)]
    if sent.first_reaction_at is not None:
        candidates.append(sent.first_reaction_at)
    return min(candidates, default=None)


def is_approval_prompt(m: BotMessage) -> bool:
    """Whether a bubble is a bot approval prompt (by its fixed copy)."""
    return any(marker in m.text for marker in APPROVAL_PROMPT_MARKERS)


def prompt_items(m: BotMessage) -> list[tuple[int, str]]:
    """Return the (number, line) of each approval a prompt asks about; a single prompt is number 1."""
    numbered = [(int(n), line) for n, line in NUMBERED_ITEM.findall(m.text)]
    if numbered:
        return numbered
    return [(1, m.text.splitlines()[0])]


def every_message_answered(t: Transcript, _: Budgets) -> list[Violation]:
    """Every message I sent got a reaction, an answer or an "On it" before the run ended."""
    return [
        Violation(
            "answered", f"no reaction and no bubble after my message {s.id}", {"sent": s.text}
        )
        for s in t.sent
        if first_response_at(t, s) is None
    ]


def first_response_in_budget(t: Transcript, budgets: Budgets) -> list[Violation]:
    """Check that the first visible response to each message came within the latency budget."""
    out = []
    for s in t.sent:
        at = first_response_at(t, s)
        if at is not None and at - s.sent_at > budgets.first_response_s:
            out.append(
                Violation(
                    "latency",
                    f"first response to {s.id} took {at - s.sent_at:.1f}s (budget {budgets.first_response_s:g}s)",
                    {"sent": s.text, "latency_s": round(at - s.sent_at, 2)},
                )
            )
    return out


def nothing_taken_back(t: Transcript, _: Budgets) -> list[Violation]:
    """No bubble I saw was deleted, and no edit ever removed text I had already seen."""
    out = []
    for m in t.bot:
        if m.deleted_at is not None:
            out.append(
                Violation(
                    "taken_back", f"bubble {m.id} was deleted", {"text": m.text, "at": m.deleted_at}
                )
            )
        for before, after in zip(m.states, m.states[1:], strict=False):
            if not after.text.startswith(before.text.rstrip()):
                out.append(
                    Violation(
                        "taken_back",
                        f"bubble {m.id} lost text it had shown",
                        {"before": before.text[-200:], "after": after.text[:200], "at": after.at},
                    )
                )
    return out


def no_duplicate_bubbles(t: Transcript, _: Budgets) -> list[Violation]:
    """No bubble repeats another, no long line appears twice, and no bubble is a stranded copy of a later one."""
    out = []
    seen_lines: dict[str, int] = {}
    for i, m in enumerate(t.bot):
        for later in t.bot[i + 1 :]:
            if m.text and m.text == later.text and len(m.text) >= DUPLICATE_BUBBLE_MIN_CHARS:
                out.append(
                    Violation(
                        "duplicate",
                        f"bubbles {m.id} and {later.id} show the same text",
                        {"text": m.text[:200]},
                    )
                )
            elif m.text and later.text.startswith(m.text) and len(later.text) > len(m.text):
                out.append(
                    Violation(
                        "duplicate",
                        f"bubble {m.id} is a stranded start of bubble {later.id}",
                        {"stranded": m.text[:200], "full": later.text[:200]},
                    )
                )
        for line in {ln.strip() for ln in m.text.splitlines()}:
            if len(line) < REPEATED_LINE_MIN_CHARS:
                continue
            if line in seen_lines and seen_lines[line] != m.id:
                out.append(
                    Violation(
                        "duplicate",
                        f"a line of bubble {m.id} repeats bubble {seen_lines[line]}",
                        {"line": line},
                    )
                )
            seen_lines.setdefault(line, m.id)
    return out


def no_leaked_internals(t: Transcript, _: Budgets) -> list[Violation]:
    """No text a bubble ever showed carries internals, and no final text carries unconverted markdown."""
    out = []
    for m in t.bot:
        for name, pattern in LEAKS.items():
            hit = next((s for s in m.states if pattern.search(s.text)), None)
            if hit is not None:
                match = pattern.search(hit.text)
                out.append(
                    Violation(
                        "leak",
                        f"bubble {m.id} showed {name}",
                        {"match": match.group(0) if match else "", "at": hit.at},
                    )
                )
        for name, pattern in RAW_MARKDOWN.items():
            match = pattern.search(m.text)
            if match:
                out.append(
                    Violation("leak", f"bubble {m.id} shows raw {name}", {"match": match.group(0)})
                )
    return out


def stop_is_final(t: Transcript, _: Budgets) -> list[Violation]:
    """After /stop, the stop notice is the last new bubble, and nothing grows after it, until I send again."""
    out = []
    for s in t.sent:
        if s.text.strip() != STOP_COMMAND:
            continue
        window_end = t.next_send_after(s.sent_at)
        after = [m for m in t.bot_after(s.sent_at) if m.created_at < window_end]
        if not after:
            continue
        ack = after[0]
        out.extend(
            Violation(
                "stop",
                f"bubble {m.id} arrived after the stop notice",
                {"text": m.text[:200], "at": m.created_at},
            )
            for m in after[1:]
        )
        for m in t.bot:
            if m is ack:
                continue
            late = [
                st for st in m.states[1:] if ack.created_at + STOP_EDIT_GRACE_S < st.at < window_end
            ]
            if late:
                out.append(
                    Violation(
                        "stop",
                        f"bubble {m.id} kept growing after the stop notice",
                        {"at": late[0].at, "text": late[-1].text[-200:]},
                    )
                )
    return out


def approvals_asked_once(t: Transcript, _: Budgets) -> list[Violation]:
    """No approval is asked about twice: each prompt line appears in one prompt only."""
    out = []
    asked: dict[str, int] = {}
    for m in t.bot:
        if not is_approval_prompt(m):
            continue
        for _, line in prompt_items(m):
            if line in asked:
                out.append(
                    Violation(
                        "asked_twice",
                        f"prompt {m.id} asks again what prompt {asked[line]} asked",
                        {"line": line},
                    )
                )
            asked.setdefault(line, m.id)
    return out


Invariant = Callable[[Transcript, Budgets], list[Violation]]
INVARIANTS: tuple[Invariant, ...] = (
    every_message_answered,
    first_response_in_budget,
    nothing_taken_back,
    no_duplicate_bubbles,
    no_leaked_internals,
    stop_is_final,
    approvals_asked_once,
)


def check_invariants(t: Transcript, budgets: Budgets) -> list[Violation]:
    """Apply every invariant to a transcript."""
    return [v for invariant in INVARIANTS for v in invariant(t, budgets)]
