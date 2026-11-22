"""The JEV Decisions route of the scripted stub: what a sim test says a reply to an approval means.

GAIA asks JEV (OpenRouter's /api/alpha/decisions) what a free-form chat reply to a
pending approval means. A test scripts that answer inline, in the reply it sends:

    [[jev:<choice>]]    every question in the call is answered with this choice

so "yes but make it high priority [[jev:amend]]" reads as an approval with a
change. The directive is read from the call's ``state.reply``, the field the
reply classifier sends the user's words in. A call with no directive (an
unscripted reply, the instant reaction, a trigger gate) is refused with 402,
what OpenRouter answers an account without credit: GAIA's callers then take
their own degradation path, as they do in production when JEV is down.

Pure stdlib, like directives.py, so it is unit-tested without the server.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

# The confidence a scripted answer carries: above every decision line GAIA applies.
SCRIPTED_CONFIDENCE = 0.99
NO_CREDIT_STATUS = 402
_JEV_DIRECTIVE_RE = re.compile(r"\[\[jev:([a-z_]+)\]\]")


class DecisionsScriptError(ValueError):
    """A [[jev:…]] directive names a choice a question does not offer. Surfaced as HTTP 500."""


@dataclass(frozen=True)
class DecisionsAnswer:
    """The stub's answer to one Decisions call: an HTTP status and its JSON body."""

    status: int
    body: dict[str, Any]


def scripted_choice(state: object) -> str | None:
    """Return the choice a [[jev:…]] directive in the state's reply names, or None."""
    reply = state.get("reply") if isinstance(state, dict) else None
    if not isinstance(reply, str):
        return None
    found = _JEV_DIRECTIVE_RE.findall(reply)
    if len(found) > 1:
        raise DecisionsScriptError(f"more than one [[jev:…]] directive in {reply[:120]!r}")
    return found[0] if found else None


def answer_decisions(body: dict[str, Any]) -> DecisionsAnswer:
    """Answer every choice question with the scripted choice; 402 when the call scripts none."""
    choice = scripted_choice(body.get("state"))
    if choice is None:
        return DecisionsAnswer(
            status=NO_CREDIT_STATUS,
            body={
                "error": {
                    "message": "llm-stub: this Decisions call carries no [[jev:…]] directive",
                    "code": NO_CREDIT_STATUS,
                }
            },
        )
    answers: dict[str, Any] = {}
    for name, question in (body.get("questions") or {}).items():
        offered = (question or {}).get("criteria") or {}
        if question.get("type") != "choice" or choice not in offered:
            raise DecisionsScriptError(
                f"question {name!r} does not offer the scripted choice {choice!r}"
            )
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": SCRIPTED_CONFIDENCE,
            "probabilities": {choice: SCRIPTED_CONFIDENCE},
        }
    return DecisionsAnswer(
        status=200, body={"answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}
    )
