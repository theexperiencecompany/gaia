"""
No-Gmail clarify follow-up.

Generates 3 LLM-authored questions (scope / blocker / constraint) that run
between the focus answer and the todo pipeline so the generator has enough
signal to produce concrete actions. Gmail users skip this — their inbox is
the signal source.

The endpoint that calls this is `POST /onboarding/clarify-questions`. The
answers come back on the existing `POST /onboarding` payload as
`clarify_answers` and get persisted on the user document.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import CLARIFY_QUESTIONS_PROMPT
from app.core.lazy_loader import providers

ClarifyQuestionKind = Literal["scope", "blocker", "constraint"]
_KINDS: tuple[ClarifyQuestionKind, ...] = ("scope", "blocker", "constraint")


class _ClarifyQuestion(BaseModel):
    kind: ClarifyQuestionKind = Field(
        description="One of scope, blocker, or constraint — see prompt for definitions"
    )
    question: str = Field(description="The question text, ending with a question mark")
    options: list[str] = Field(
        description="Exactly 3 short, specific options — never generic placeholders"
    )


class _ClarifyQuestionList(BaseModel):
    questions: list[_ClarifyQuestion] = Field(
        description="Exactly 3 questions in order: scope, blocker, constraint"
    )


def _fallback_questions() -> list[dict[str, Any]]:
    return [
        {
            "id": "scope",
            "kind": "scope",
            "question": "What needs to move forward this week?",
            "options": [
                "The main project — shipping the next milestone",
                "External work — outreach, meetings, customers",
                "Internal work — planning, hiring, ops",
            ],
        },
        {
            "id": "blocker",
            "kind": "blocker",
            "question": "Where are you actually stuck right now?",
            "options": [
                "Too many open threads, nothing's closing",
                "Waiting on someone else to come back",
                "I know what to do, just not getting to it",
            ],
        },
        {
            "id": "constraint",
            "kind": "constraint",
            "question": "How much focused time can you realistically carve out?",
            "options": [
                "A few hours every day",
                "One or two deep-work blocks total",
                "Honestly, very little — I'm mostly in meetings",
            ],
        },
    ]


async def generate_clarify_questions(
    name: str,
    profession: str,
    focus: str,
) -> list[dict[str, Any]]:
    """Produce the 3-question follow-up set for the no-Gmail path."""
    t0 = time.monotonic()
    prompt = CLARIFY_QUESTIONS_PROMPT.format(
        name=name,
        profession=profession,
        focus=focus,
        format_instructions=(
            "Return a JSON object with a 'questions' key containing exactly 3 "
            "items in the order: scope, blocker, constraint. Each item has "
            "'kind', 'question', and 'options' (list of 3 strings)."
        ),
    )

    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        structured_llm = llm.with_structured_output(_ClarifyQuestionList)
        parsed: _ClarifyQuestionList = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        by_kind = {q.kind: q for q in parsed.questions}
        questions: list[dict[str, Any]] = []
        for kind in _KINDS:
            q = by_kind.get(kind)
            if q is None:
                continue
            options = [opt.strip() for opt in q.options if opt and opt.strip()][:3]
            if len(options) < 2:
                continue
            questions.append(
                {
                    "id": kind,
                    "kind": kind,
                    "question": q.question.strip(),
                    "options": options,
                }
            )

        if len(questions) < 3:
            log.warning(
                "[clarify] LLM returned incomplete set, falling back",
                received=len(questions),
            )
            return _fallback_questions()

        log.info(
            "[clarify] questions generated",
            duration_s=round(time.monotonic() - t0, 2),
        )
        return questions

    except Exception as e:
        log.warning(
            "[clarify] generation failed, using fallback",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return _fallback_questions()


def format_clarify_context(clarify_answers: list[dict[str, Any]] | None) -> str:
    """Render persisted clarify answers as a prompt fragment."""
    if not clarify_answers:
        return ""

    lines: list[str] = []
    for answer in clarify_answers:
        value = (answer.get("value") or "").strip()
        if not value:
            continue
        kind = (answer.get("kind") or "").strip() or "context"
        lines.append(f"- {kind.capitalize()}: {value}")

    if not lines:
        return ""

    return "Clarifying context the user just shared:\n" + "\n".join(lines) + "\n\n"
