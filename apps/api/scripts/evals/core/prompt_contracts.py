"""Eval contracts anchored to the prompt text GAIA actually ships.

The problem this exists to kill: every judge rubric in this harness used to be
hand-written YAML prose. A rubric like "the reply mirrors the user's tone" is a
*paraphrase* of `COMMS_AGENT_PROMPT`, frozen at the moment someone typed it. Edit
the prompt — soften the rule, rename the section, delete it outright — and not a
single eval notices. The suite keeps grading a spec the product stopped shipping,
and reports green while the thing it claims to measure has moved.

A **clause** is a named, verbatim span of a live prompt constant. Rubrics quote
the clause instead of restating it, so a prompt edit changes what the evals grade
with no YAML to update. `suites/quality.py::openui_policy_criteria` proved the
shape on the OpenUI surface policy; this module is that idea generalised, and it
is where the OpenUI extraction converges once the harness freeze lifts.

**Resolution fails loud, always.** A clause whose anchor no longer appears —
section renamed, rule deleted, prompt restructured — raises
:class:`ClauseResolutionError`. There is no cached copy, no default, no empty
string, and no "best effort" match. A silent fallback would recreate precisely
the bug this module exists to fix: an eval that keeps passing because it quietly
stopped reading the prompt. :func:`contract_failures` turns that property into a
CI gate (`tests/unit/evals/test_prompt_contracts.py`).

Anchors are matched as **exact substrings, and must occur exactly once**.
Ambiguity is treated as a failure rather than resolved by "first match": once an
anchor matches two places, it no longer identifies the rule, and the extract
would drift the next time either copy is edited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
import importlib
import textwrap

#: Prompt constants a clause may be anchored in, as ``(module, attribute)``.
#:
#: Loaded lazily by :func:`prompt_text` rather than at module import: importing
#: ``openui_prompts`` pulls in app settings (Infisical, validators), and
#: ``__main__`` imports every suite module eagerly, so an import-time failure
#: here would take down every suite's run rather than just the cases that
#: actually depend on a prompt.
PROMPT_SOURCES: dict[str, tuple[str, str]] = {
    "comms": ("app.agents.prompts.comms_prompts", "COMMS_AGENT_PROMPT"),
    "executor": ("app.agents.prompts.comms_prompts", "EXECUTOR_AGENT_PROMPT"),
    "openui": ("app.agents.prompts.openui_prompts", "OPENUI_SURFACE_POLICY"),
    "subagent_base": ("app.agents.prompts.subagent_prompts", "BASE_SUBAGENT_PROMPT"),
    "subagent_gmail": ("app.agents.prompts.subagent_prompts", "GMAIL_AGENT_SYSTEM_PROMPT"),
    "subagent_reminders": ("app.agents.prompts.subagent_prompts", "REMINDER_AGENT_SYSTEM_PROMPT"),
    "memory_extraction": ("app.agents.prompts.memory_prompts", "BASE_MEMORY_EXTRACTION_PROMPT"),
}


class ClauseResolutionError(Exception):
    """A named clause no longer resolves against the shipped prompt.

    Raised, never swallowed. The message names the clause, the prompt constant,
    the anchor that went missing, and every eval that depends on it, because the
    fix is always one of two things: re-anchor the clause on the prompt's new
    wording, or delete the clause *and* the evals it feeds.
    """


@dataclass(frozen=True)
class Clause:
    """One named span of a live prompt.

    ``starts_at`` and ``ends_before`` are verbatim substrings of the shipped
    prompt. The span runs from the start of ``starts_at``'s line to the start of
    ``ends_before``'s line; with no ``ends_before`` the clause is ``starts_at``'s
    own line, which is the right extent for a single-line absolute.

    Requiring an explicit end anchor (rather than inferring one from a header
    regex) is deliberate. Header shapes differ per prompt file — ``—SECTION—``,
    ``— SECTION``, ``## SECTION``, numbered rules — so one inferred rule would
    silently mis-slice four of them, and a *changed* header shape would silently
    change what the rubric quotes. An explicit end anchor cannot fail quietly:
    the extent is contract-checked at both ends.
    """

    name: str
    source: str
    starts_at: str
    ends_before: str | None = None
    #: What behaviour this clause governs, in one line — the reason a reader
    #: should care that it broke.
    governs: str = ""
    #: Evals that grade this rule. Named in the failure message so a prompt edit
    #: tells you which suite went stale, not just that a string disappeared.
    depends_on: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ref(self) -> str:
        return f"{self.source}.{self.name}"


CLAUSES: tuple[Clause, ...] = (
    # -- comms: the NON-NEGOTIABLES block ---------------------------------
    Clause(
        name="delegate_every_real_ask",
        source="comms",
        starts_at="1. DELEGATE EVERY REAL ASK:",
        ends_before="2. YOU ARE THE USER'S ONLY WINDOW:",
        governs="when a turn must go through call_executor instead of being answered directly",
        depends_on=(
            "gate:delegation",
            "data/comms/delegation.yaml",
            "data/quality/delegation.yaml",
        ),
    ),
    Clause(
        name="only_window",
        source="comms",
        starts_at="2. YOU ARE THE USER'S ONLY WINDOW:",
        ends_before="3. RELAY EVERY RESULT IN FULL:",
        governs="the executor's output reaches the user only through the comms reply",
        depends_on=("gate:communicate", "data/quality/hard.yaml"),
    ),
    Clause(
        name="relay_every_result_in_full",
        source="comms",
        starts_at="3. RELAY EVERY RESULT IN FULL:",
        ends_before="4. NEVER FABRICATE:",
        governs="reacting to data without delivering it is a critical failure",
        depends_on=("gate:communicate", "data/quality/hard.yaml"),
    ),
    Clause(
        name="never_fabricate",
        source="comms",
        starts_at="4. NEVER FABRICATE:",
        ends_before="7. RISKY WRITES NEED A DRAFT:",
        governs="no claim of completed work before call_executor returns it",
        depends_on=("gate:must_not_communicate", "data/comms/honesty.yaml"),
    ),
    Clause(
        name="confirm_risky_writes",
        source="comms",
        starts_at="7. RISKY WRITES NEED A DRAFT:",
        ends_before="8. HONOR STATED CHANNELS:",
        governs="sends and deletes are drafted and confirmed before they happen",
        depends_on=("data/quality/hard.yaml", "data/capability/gmail.yaml"),
    ),
    Clause(
        name="honor_stated_channels",
        source="comms",
        starts_at="8. HONOR STATED CHANNELS:",
        ends_before="9. ONE ENTITY:",
        governs="a named notification channel is used, not silently widened to all",
        depends_on=("gate:tool_call_correctness", "data/capability/notifications.yaml"),
    ),
    Clause(
        name="one_entity",
        source="comms",
        starts_at="9. ONE ENTITY:",
        ends_before="10. GROUND TRUTH:",
        governs="internal machinery (executor, subagent, tool) is never named to the user",
        depends_on=("gate:internal_machinery", "data/quality/voice.yaml"),
    ),
    Clause(
        name="ground_truth",
        source="comms",
        starts_at="10. GROUND TRUTH:",
        ends_before="11. NO INVENTED CAPABILITIES:",
        governs="facts, names, numbers, IDs and links are copied exactly, never invented",
        depends_on=("gate:communicate", "data/comms/honesty.yaml"),
    ),
    Clause(
        name="no_invented_capabilities",
        source="comms",
        starts_at="11. NO INVENTED CAPABILITIES:",
        ends_before="—Voice (Human WhatsApp Mode)—",
        governs="how a request outside GAIA's real abilities is declined",
        depends_on=("data/quality/refusals.yaml", "data/comms/honesty.yaml"),
    ),
    # -- comms: response style --------------------------------------------
    Clause(
        name="tone_mirroring",
        source="comms",
        starts_at="TONE MIRRORING (PRIMARY DIRECTIVE):",
        ends_before="Mechanics:",
        governs="matching the user's formality, vocabulary, length, pacing and energy",
        depends_on=("data/quality/tone.yaml", "data/comms/smalltalk.yaml"),
    ),
    Clause(
        name="voice_mechanics",
        source="comms",
        starts_at="Mechanics:",
        ends_before="Never sound like a bot:",
        governs="the WhatsApp register: short, lowercase, fragments, brevity under 10 words",
        depends_on=("data/quality/voice.yaml",),
    ),
    Clause(
        name="emoji_discipline",
        source="comms",
        starts_at="- Emojis EXTREMELY RARE,",
        governs="no emoji before the user has used one",
        depends_on=("gate:emoji_discipline", "suites/quality.py::_emoji_discipline_check"),
    ),
    Clause(
        name="no_dashes",
        source="comms",
        starts_at="- NEVER use em dashes",
        ends_before="Never sound like a bot:",
        governs="em dashes and en dashes are banned from every output",
        depends_on=("gate:dash_discipline",),
    ),
    Clause(
        name="banned_bot_phrases",
        source="comms",
        starts_at="- Banned phrases (they scream chatbot):",
        ends_before="- When the user is just chatting,",
        governs="the literal chatbot phrases that must never be said",
        depends_on=("gate:banned_bot_phrases", "data/quality/voice.yaml"),
    ),
    Clause(
        name="content_vs_conversation_length",
        source="comms",
        starts_at="—Length Modes (CRITICAL: two different modes, never confuse them)—",
        ends_before="—Chat Bubbles—",
        governs="chat replies stay short; requested deliverables are written in full",
        depends_on=("data/quality/hard.yaml", "data/quality/everyday.yaml"),
    ),
    Clause(
        name="write_like_a_human",
        source="comms",
        starts_at="WRITE LIKE A HUMAN (all content you produce):",
        ends_before="—Chat Bubbles—",
        governs="the AI-tell patterns banned from produced content (LLM vocabulary, scaffolding)",
        depends_on=("data/quality/hard.yaml",),
    ),
    Clause(
        name="bubble_splitting",
        source="comms",
        starts_at="—Chat Bubbles—",
        ends_before="—Rich UI Components (OpenUI) — CRITICAL—",
        governs="conversational messages split into bubbles; structured data stays in one",
        depends_on=("gate:bubble_boundary", "data/quality/bubbles.yaml"),
    ),
    # -- comms: the call_executor protocol ---------------------------------
    Clause(
        name="tone_is_not_intent",
        source="comms",
        starts_at="TONE IS NOT INTENT:",
        ends_before="THE THREE MOMENTS:",
        governs="casual phrasing of an action does not make it small talk",
        depends_on=("gate:delegation", "data/comms/delegation.yaml"),
    ),
    Clause(
        name="acknowledge_exactly_once",
        source="comms",
        starts_at="THE THREE MOMENTS:",
        ends_before="Writing the task (complete context, CRITICAL):",
        governs="the three moments: silent call, one ack, then the outcome",
        depends_on=("data/quality/bubbles.yaml", "data/quality/multiturn_extra.yaml"),
    ),
    Clause(
        name="never_echo_task_id",
        source="comms",
        starts_at='- MOMENT 2 (right after the tool returns "Task accepted"):',
        governs="the internal task_id is never shown to the user",
        depends_on=("gate:internal_machinery",),
    ),
    Clause(
        name="never_reproduce_internal_tags",
        source="comms",
        starts_at="Never reproduce the literal tags:",
        governs="the internal channel tags never appear in a user-facing reply",
        depends_on=("gate:internal_machinery",),
    ),
    Clause(
        name="long_form_deliverables",
        source="comms",
        starts_at="1. LONG-FORM DELIVERABLES:",
        ends_before="2. DATA RESULTS (calendar, emails, search, lists):",
        governs="a finished written deliverable is passed through whole, never summarised",
        depends_on=("gate:communicate", "data/quality/hard.yaml"),
    ),
    Clause(
        name="executor_ground_truth_contract",
        source="comms",
        starts_at="—Delivering Results (<executor_result> / <executor_error>)—",
        ends_before="—Rate Limits & Subscription—",
        governs="how executor output is re-voiced: relay everything, change only tone",
        depends_on=("gate:communicate", "data/quality/hard.yaml"),
    ),
    Clause(
        name="upgrade_link",
        source="comms",
        starts_at="[Upgrade to GAIA Pro](https://heygaia.io/pricing)",
        governs="the exact markdown link offered when usage limits are hit",
        depends_on=("data/quality/domains.yaml",),
    ),
    Clause(
        name="never_narrate_memory",
        source="comms",
        starts_at="- NEVER NARRATE MEMORY:",
        ends_before="- A PREFERENCE IS NOT A TASK:",
        governs="remembering is never announced as a mechanism",
        depends_on=("data/quality/voice.yaml", "suites/memory.py"),
    ),
    Clause(
        name="preference_is_not_a_task",
        source="comms",
        starts_at="- A PREFERENCE IS NOT A TASK:",
        ends_before="—Active Todo Binding—",
        governs="a standing preference is remembered, never turned into a destructive action",
        depends_on=("gate:no_forbidden_tools", "data/quality/hard.yaml"),
    ),
    # -- executor ----------------------------------------------------------
    Clause(
        name="risky_writes_draft_first",
        source="executor",
        starts_at="RISKY WRITES — DRAFT AND CONFIRM FIRST",
        ends_before="TWO TASK SYSTEMS (do not confuse)",
        governs="emails always go through the draft flow; nothing auto-sends or auto-deletes",
        depends_on=("data/capability/gmail.yaml", "suites/hil.py"),
    ),
    Clause(
        name="verbatim_only_fields",
        source="executor",
        starts_at="VERBATIM-ONLY FIELDS (never rewrite, never infer, never guess):",
        ends_before="WHAT YOU MAY DO:",
        governs="titles, sources, authors, dates, URLs and quotes are copied, never inferred",
        depends_on=("gate:communicate", "data/capability/web.yaml"),
    ),
    Clause(
        name="research_effort_ladder",
        source="executor",
        starts_at="RESEARCH EFFORT LADDER",
        ends_before="GAIA SELF-KNOWLEDGE (MANDATORY)",
        governs="effort matches the question; deep_research is not the default",
        depends_on=("data/capability/web.yaml", "data/capability/web_extra.yaml"),
    ),
    # -- openui surface policy --------------------------------------------
    Clause(
        name="rule_native_card",
        source="openui",
        starts_at="1. Tool already renders a native card",
        ends_before="2. Composing/sending an email",
        governs="tools with their own card are never wrapped in :::openui",
        depends_on=("openui_policy:suppressed", "data/quality/openui.yaml"),
    ),
    Clause(
        name="rule_email_draft",
        source="openui",
        starts_at="2. Composing/sending an email",
        ends_before="3. Casual chat,",
        governs="composing mail uses the draft tool, never :::openui or a TextDocument",
        depends_on=("data/quality/openui.yaml", "data/capability/gmail.yaml"),
    ),
    Clause(
        name="rule_plain_text",
        source="openui",
        starts_at="3. Casual chat, a single-sentence answer",
        ends_before="4. A casual reply,",
        governs="casual chat and single-sentence answers get no component",
        depends_on=("openui_policy:forbidden", "data/quality/openui.yaml"),
    ),
    Clause(
        name="rule_structured_data",
        source="openui",
        starts_at="5. Structured data shown inline:",
        ends_before="6. Reusable text",
        governs="stats, timelines, steps, charts and maps MUST use an :::openui component",
        depends_on=("openui_policy:required", "data/quality/openui.yaml"),
    ),
    Clause(
        name="prose_and_component_are_layers",
        source="openui",
        starts_at="OPENUI AND PROSE WORK TOGETHER",
        ends_before="Never put :::openui inside greetings, opinions, or plain conversational replies.",
        governs="the component and the words are one reply, never a choice between two",
        depends_on=("openui_policy:required", "data/quality/openui.yaml"),
    ),
    Clause(
        name="never_openui_in_conversation",
        source="openui",
        starts_at="Never put :::openui inside greetings, opinions, or plain conversational replies.",
        governs="the absolute against components in conversational replies",
        depends_on=("openui_policy:forbidden", "data/quality/openui.yaml"),
    ),
    Clause(
        name="how_to_emit",
        source="openui",
        starts_at="How to emit openui — fence the openui-lang code",
        governs="a component is openui-lang inside a :::openui fence, mixed with ordinary prose",
        depends_on=("openui_policy:required", "data/quality/openui.yaml"),
    ),
    # -- subagents ---------------------------------------------------------
    Clause(
        name="finish_task_carries_the_data",
        source="subagent_base",
        starts_at="- finish_task(result=...) MUST contain the ACTUAL data",
        governs="a subagent returns every item, not a count or a couple of highlights",
        depends_on=("gate:communicate", "data/capability/multitool.yaml"),
    ),
    Clause(
        name="draft_first_workflow",
        source="subagent_gmail",
        starts_at="— DRAFT-FIRST WORKFLOW (NON-NEGOTIABLE)",
        ends_before="— WHAT MAKES A GOOD EMAIL",
        governs="every email goes through the real compose card, never plain text or OpenUI",
        depends_on=("data/capability/gmail.yaml", "suites/hil.py"),
    ),
    Clause(
        name="delete_requires_consent",
        source="subagent_reminders",
        starts_at="- NEVER use delete_reminder_tool without explicit user consent",
        governs="destructive reminder tools need explicit consent",
        depends_on=("gate:no_forbidden_tools", "data/capability/reminders.yaml"),
    ),
    # -- memory extraction --------------------------------------------------
    Clause(
        name="no_secrets",
        source="memory_extraction",
        starts_at="6. NO SECRETS:",
        governs="passwords, tokens, API keys and credentials are never extracted into memory",
        depends_on=("suites/memory.py", "suites/safety.py"),
    ),
    Clause(
        name="be_specific",
        source="memory_extraction",
        starts_at="1. BE SPECIFIC:",
        governs="memories carry real IDs and emails, not 'the user's email'",
        depends_on=("suites/memory.py",),
    ),
    Clause(
        name="extraction_rules",
        source="memory_extraction",
        starts_at="## EXTRACTION RULES:",
        ends_before="## MEMORY FORMAT:",
        governs="the full rule set every extracted memory must satisfy",
        depends_on=("suites/memory.py",),
    ),
)

_BY_REF: dict[str, Clause] = {c.ref: c for c in CLAUSES}

if len(_BY_REF) != len(CLAUSES):
    raise ValueError("duplicate clause ref in CLAUSES — every (source, name) must be unique")


@cache
def prompt_text(source: str) -> str:
    """The live text of a registered prompt constant.

    Cached because a run resolves dozens of clauses against the same handful of
    prompts, and importing ``openui_prompts`` costs an app-settings boot.
    """
    entry = PROMPT_SOURCES.get(source)
    if entry is None:
        raise ClauseResolutionError(
            f"unknown prompt source {source!r}; registered: {', '.join(sorted(PROMPT_SOURCES))}"
        )
    module_path, attribute = entry
    module = importlib.import_module(module_path)
    if not hasattr(module, attribute):
        raise ClauseResolutionError(
            f"prompt source {source!r} points at {module_path}.{attribute}, which no longer "
            f"exists. The constant was renamed or deleted — re-point PROMPT_SOURCES at the "
            f"prompt that ships today."
        )
    value = getattr(module, attribute)
    if not isinstance(value, str):
        raise ClauseResolutionError(
            f"prompt source {source!r} ({module_path}.{attribute}) is "
            f"{type(value).__name__}, not str"
        )
    return value


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _locate(clause_obj: Clause, text: str, anchor: str, role: str) -> int:
    """Index of ``anchor`` in ``text``, or a loud failure.

    Zero matches means the prompt no longer says this. Two or more means the
    anchor stopped identifying one rule, so the extracted span is arbitrary —
    both are contract breaks, and neither may be papered over by picking a match.
    """
    count = text.count(anchor)
    if count == 1:
        return text.index(anchor)
    depends = ", ".join(clause_obj.depends_on) or "nothing yet"
    problem = "no longer appears in" if count == 0 else f"appears {count} times in"
    module_path, attribute = PROMPT_SOURCES[clause_obj.source]
    raise ClauseResolutionError(
        f"clause {clause_obj.ref!r} is broken: its {role} anchor {anchor!r} {problem} "
        f"{module_path}.{attribute}.\n"
        f"  This clause governs: {clause_obj.governs or 'unstated'}\n"
        f"  Evals that depend on it: {depends}\n"
        f"  Fix by re-anchoring the clause on the prompt's new wording, or by deleting the "
        f"clause AND the evals above. Do not restore a stale copy of the text — a rubric that "
        f"outlives the rule it quotes is exactly the drift this module exists to prevent."
    )


def resolve(ref: str) -> str:
    """The live prompt text of one clause, dedented and stripped.

    ``ref`` is ``"<source>.<name>"``. Raises :class:`ClauseResolutionError` if
    the clause is unregistered or its anchors no longer resolve.
    """
    clause_obj = _BY_REF.get(ref)
    if clause_obj is None:
        raise ClauseResolutionError(
            f"unknown clause {ref!r}; registered: {', '.join(sorted(_BY_REF))}"
        )
    text = prompt_text(clause_obj.source)
    start = _line_start(text, _locate(clause_obj, text, clause_obj.starts_at, "start"))
    if clause_obj.ends_before is None:
        end = text.find("\n", start)
        span = text[start:] if end == -1 else text[start:end]
    else:
        stop = _locate(clause_obj, text, clause_obj.ends_before, "end")
        if stop <= start:
            raise ClauseResolutionError(
                f"clause {ref!r} is inverted: its end anchor "
                f"{clause_obj.ends_before!r} now precedes its start anchor "
                f"{clause_obj.starts_at!r}. The prompt was reordered — re-anchor the clause."
            )
        span = text[start : _line_start(text, stop)]
    return textwrap.dedent(span).strip()


def clause(source: str, name: str) -> str:
    """The live prompt text of one clause, by source and name."""
    return resolve(f"{source}.{name}")


def quote(ref: str) -> str:
    """One judge criterion that grades against the agent's own prompt text.

    The judge is handed the shipped rule verbatim rather than someone's summary
    of it, which is the entire point: edit the prompt and this criterion changes
    with it.
    """
    clause_obj = _BY_REF.get(ref)
    body = resolve(ref)
    governs = clause_obj.governs if clause_obj else ""
    lead = f"The agent's own shipped prompt states this rule ({governs}) verbatim:"
    return (
        f'{lead}\n"""\n{body}\n"""\n'
        f"Judge ONLY whether the assistant's reply obeys that rule for this request. "
        f"Grade the rule as written, not a softer reading of it."
    )


def contract_criteria(refs: list[str]) -> list[str]:
    """Judge criteria composed from live prompt clauses, one per ref.

    The composition entry point for suites: a case names the contracts it is
    really about and gets the prompt's own words appended to its rubric. Any
    hand-written criteria the case already carries are kept — those say what
    THIS request is, these say what the product promises.
    """
    if not refs:
        return []
    unknown = [ref for ref in refs if ref not in _BY_REF]
    if unknown:
        raise ClauseResolutionError(
            f"unknown prompt contract(s) {unknown}; registered: {', '.join(sorted(_BY_REF))}"
        )
    return [quote(ref) for ref in refs]


def contract_failures() -> list[str]:
    """Every clause that no longer resolves, as ready-to-read failure messages.

    Collects instead of raising on the first break so one prompt edit surfaces
    all of its damage in a single CI run. :func:`resolve` is still the loud path
    for anything that runs during an eval.
    """
    failures: list[str] = []
    for clause_obj in CLAUSES:
        try:
            resolve(clause_obj.ref)
        except ClauseResolutionError as e:
            failures.append(str(e))
    return failures
