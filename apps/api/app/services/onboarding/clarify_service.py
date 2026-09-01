"""Legacy clarify-answer rendering.

The no-Gmail clarify follow-up was removed with the paid-first onboarding
flow — nothing writes ``onboarding.clarify_answers`` any more. Accounts that
ran the old flow still carry them, and the Gmail intelligence pipeline still
folds them into its prompt, so the renderer stays.
"""

from __future__ import annotations

from app.models.onboarding_models import ClarifyAnswerRecord


def format_clarify_context(clarify_answers: list[ClarifyAnswerRecord] | None) -> str:
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
