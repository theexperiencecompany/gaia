"""Sensitive-action classifier for the browser human-in-the-loop gate.

A structured LLM judgment — not keyword matching — decides whether a planned
browser step must pause for human approval. A deterministic structural fast
path skips the judge when every planned action is pure navigation/reading, so
the common safe case costs nothing.
"""

from app.agents.llm.client import ainvoke_structured
from app.constants.browser import NON_COMMITTING_ACTIONS, SensitiveCategory
from app.constants.log_tags import LogTag
from app.schemas.browser import SensitiveActionVerdict
from shared.py.wide_events import log

_CLASSIFIER_PROMPT = """You are a safety gate for an autonomous web-browsing agent.
Given the agent's next goal and the concrete browser actions it is about to \
execute on the current page, decide whether it requires explicit human approval.

Require approval ONLY when the action would:
- submit a payment, confirm a purchase/booking, or move money (category: payment)
- enter a password, one-time code / OTP / 2FA, or other secret (category: credentials)
- perform an irreversible or hard-to-undo action such as deleting an account, \
sending a message on the user's behalf, or confirming a legally binding submission \
(category: irreversible)

Do NOT require approval for navigating, searching, reading, scrolling, or filling \
in non-committing form fields (names, addresses, search queries, dates, filters).

Current URL: {url}
Next goal: {goal}
Planned actions: {actions}
"""


def is_structurally_safe(action_names: list[str]) -> bool:
    """True when every planned action is a known non-committing action."""
    return bool(action_names) and all(name in NON_COMMITTING_ACTIONS for name in action_names)


async def classify_step(
    *,
    goal: str,
    action_names: list[str],
    actions_detail: str,
    url: str,
) -> SensitiveActionVerdict:
    """Return a verdict on whether this step needs human approval.

    Structurally-safe steps return NONE without an LLM call. Any classifier
    error fails safe — it returns "requires approval" rather than silently
    letting a possibly-sensitive action through.
    """
    if is_structurally_safe(action_names):
        return SensitiveActionVerdict(requires_approval=False, category=SensitiveCategory.NONE)

    prompt = _CLASSIFIER_PROMPT.format(
        url=url or "(unknown)", goal=goal or "(none)", actions=actions_detail
    )
    try:
        return await ainvoke_structured(
            SensitiveActionVerdict, prompt, label="browser_sensitive_action_classifier"
        )
    except Exception as exc:  # noqa: BLE001 — never let a classifier failure bypass the gate
        log.warning(
            f"{LogTag.AGENT} Browser approval classifier failed; failing safe (require approval): {exc}"
        )
        return SensitiveActionVerdict(
            requires_approval=True,
            category=SensitiveCategory.IRREVERSIBLE,
            reason="Could not verify this action is safe, so pausing for your confirmation.",
        )
