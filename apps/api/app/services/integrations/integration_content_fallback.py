"""Deterministic marketplace copy for a custom integration whose LLM content generation failed.

Built only from the integration's real tool names and descriptions plus its
category and auth type, so same-category pages still differ by more than the
name. Pure and deterministic; the stored result is the one source the
marketplace page renders.
"""

from app.constants.integrations import (
    DEFAULT_INTEGRATION_CATEGORY,
    FAQ_COUNT,
    HOW_IT_WORKS_COUNT,
    USE_CASES_COUNT,
)
from app.models.db_oauth import MCPAuthType
from app.models.integration_models import AuthType, StoredIntegrationTool
from app.models.oauth_models import IntegrationContent, IntegrationFAQ, IntegrationHowItWorksStep

# Leading verbs cycle so integrations with fewer than USE_CASES_COUNT tools still
# get five distinct lines, each naming a real tool.
_USE_CASE_VERBS: tuple[str, ...] = (
    "Ask GAIA to",
    "Tell GAIA to",
    "Have GAIA",
    "Let GAIA",
    "Get GAIA to",
)

_FREE_FAQ_ANSWER_TEMPLATE = (
    "Community integrations like {name} are included with every GAIA plan at no "
    "extra charge — connect it, run automations, and use all available tools as "
    "part of your subscription. Paid plans unlock higher usage limits, priority "
    "processing, and advanced workflow features."
)


def humanize_tool_name(tool_name: str) -> str:
    """Render a tool slug as plain English, turning send_message into send message."""
    return tool_name.replace("_", " ").replace("-", " ").strip().lower()


def _first_sentence(text: str | None, max_len: int = 140) -> str | None:
    """First sentence of free text, trimmed to max_len, or None when unusable."""
    if not text:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    for sep in (". ", "! ", "? "):
        if sep in cleaned:
            cleaned = cleaned.partition(sep)[0].rstrip(".!?") + "."
            break
    if len(cleaned) > max_len:
        trimmed = cleaned[: max_len - 1].rpartition(" ")[0]
        cleaned = (trimmed or cleaned[: max_len - 1]).rstrip(",;:") + "…"
    return cleaned or None


def _named_tools(tools: list[StoredIntegrationTool]) -> list[StoredIntegrationTool]:
    """Tools with a non-blank name, in stored order."""
    return [t for t in tools if t.name and t.name.strip()]


def _connect_copy(name: str, auth_type: AuthType | None, tool_count: int) -> str:
    """Auth-aware connect paragraph shared by the how-it-works step and FAQ 1.

    Names the action count so even the structurally similar connect copy varies
    per page beyond the integration name.
    """
    intro = f'Open the GAIA Marketplace, find {name}, and click "Add to your GAIA".'
    ready = (
        f" Once authorised, all {tool_count} {name} "
        f"action{'s' if tool_count != 1 else ''} are ready to use."
    )
    if auth_type is None:
        return (
            f"{intro} Approve access or paste an API token if asked — "
            f"you're connected in under two minutes.{ready}"
        )
    kind = MCPAuthType(auth_type)
    if kind is MCPAuthType.OAUTH:
        return (
            f"{intro} Approve access on the OAuth consent screen — "
            f"you're connected in under two minutes.{ready}"
        )
    if kind is MCPAuthType.BEARER:
        return (
            f"{intro} Paste your {name} API token when asked — "
            f"you're connected in under two minutes.{ready}"
        )
    return f"{intro} No credentials needed — you're connected in under two minutes.{ready}"


def _build_use_cases(
    name: str,
    named: list[StoredIntegrationTool],
) -> list[str]:
    """Five distinct capability lines, every one naming a real tool."""
    lines: list[str] = []
    seen_snippets: set[str] = set()
    for i in range(USE_CASES_COUNT):
        tool = named[i % len(named)]
        human = humanize_tool_name(tool.name)
        verb = _USE_CASE_VERBS[i % len(_USE_CASE_VERBS)]
        snippet = _first_sentence(tool.description)
        if snippet and snippet not in seen_snippets:
            seen_snippets.add(snippet)
            lines.append(f"{verb} {human} in {name} — {snippet}")
        else:
            lines.append(f"{verb} {human} in {name} with a plain-English instruction")
    return lines


def _build_how_it_works(
    name: str,
    named: list[StoredIntegrationTool],
    category: str,
    auth_type: AuthType | None,
) -> list[IntegrationHowItWorksStep]:
    """Connect (auth-aware) -> instruct (real tool example) -> automate."""
    first = humanize_tool_name(named[0].name)
    second = humanize_tool_name(named[1].name) if len(named) > 1 else first
    return [
        IntegrationHowItWorksStep(
            title=f"Connect {name} to GAIA",
            body=_connect_copy(name, auth_type, len(named)),
        ),
        IntegrationHowItWorksStep(
            title="Tell GAIA what to do in plain English",
            body=(
                f'Describe the outcome — for example "{first} and show me the '
                f'result" or "run {second} every morning". GAIA maps it to the '
                f"right {name} actions and reports back in chat."
            ),
        ),
        IntegrationHowItWorksStep(
            title=f"GAIA runs {name} on autopilot",
            body=(
                f"Schedule it — a daily {name} briefing or an alert when {first} "
                f"returns something new — and GAIA runs it around the clock "
                f"across your {category} stack."
            ),
        ),
    ]


def _build_faqs(
    name: str,
    description: str | None,
    named: list[StoredIntegrationTool],
    category: str,
    auth_type: AuthType | None,
) -> list[IntegrationFAQ]:
    """Connect + capability inventory + one tool-specific Q + pricing."""
    count = len(named)
    top = [tool.name for tool in named[:3]]
    top_human = [humanize_tool_name(t) for t in top]
    top_list = ", ".join(top_human)

    capability_answer = (
        f"GAIA exposes all {count} {name} action{'s' if count != 1 else ''} — "
        f"including {top_list} — so you can run any of them by describing it in "
        "plain English. It can also combine "
        f"{name} with your other tools, for example summarising {name} activity "
        "in a scheduled daily briefing."
    )
    snippet = _first_sentence(named[0].description)
    if snippet:
        capability_answer += f" For example: {snippet}"
    user_snippet = _first_sentence(description, max_len=120)
    if user_snippet and user_snippet not in capability_answer:
        capability_answer = f"{user_snippet} {capability_answer}"

    first_human = top_human[0]
    tool_question = f"How do I {first_human} with {name} through GAIA?"
    if snippet:
        tool_answer = (
            f"{snippet} Just describe it in plain English — for example "
            f'"{first_human} and show me the result" — and GAIA calls the '
            "action for you."
        )
    elif count > len(top_human):
        tool_answer = (
            f"Anything the available {name} actions support — {top_list} and "
            f"{count - len(top_human)} more — combined with your email, "
            "calendar, and tasks. Describe the outcome once and GAIA runs it on "
            "schedule."
        )
    else:
        tool_answer = (
            f"Describe the outcome in plain English — for example "
            f'"{first_human} and report back" — and GAIA runs the {name} '
            f"{category} actions for you."
        )

    return [
        IntegrationFAQ(
            question=f"How do I connect {name} to GAIA?",
            answer=_connect_copy(name, auth_type, count),
        ),
        IntegrationFAQ(
            question=f"What can GAIA do with {name}?",
            answer=capability_answer,
        ),
        IntegrationFAQ(
            question=tool_question,
            answer=tool_answer,
        ),
        IntegrationFAQ(
            question=f"Is the {name} integration free?",
            answer=_FREE_FAQ_ANSWER_TEMPLATE.format(name=name),
        ),
    ]


def build_fallback_content(
    name: str,
    description: str | None,
    tools: list[StoredIntegrationTool],
    category: str,
    auth_type: AuthType | None,
) -> IntegrationContent | None:
    """Deterministic tool-grounded content satisfying the 5/3/4 contract; None with no named tool to ground it.

    Same-category pages differ by more than the name: every use-case line names
    a real tool, the capability FAQ inventories this integration's top three
    tools, and one FAQ is specific to its first tool's description.
    """
    named = _named_tools(tools)
    if not named:
        return None
    clean_category = (
        category or DEFAULT_INTEGRATION_CATEGORY
    ).strip() or DEFAULT_INTEGRATION_CATEGORY
    # Sliced to the shared contract so a USE_CASES/HOW_IT_WORKS/FAQ count change
    # fails loudly here (and in the unit tests) instead of drifting silently.
    return IntegrationContent(
        use_cases=_build_use_cases(name, named)[:USE_CASES_COUNT],
        how_it_works=_build_how_it_works(name, named, clean_category, auth_type)[
            :HOW_IT_WORKS_COUNT
        ],
        faqs=_build_faqs(name, description, named, clean_category, auth_type)[:FAQ_COUNT],
    )
