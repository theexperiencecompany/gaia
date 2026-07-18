"""Flexible mid-run sensitive-action policy.

Decides, per sensitive step, whether the agent should hand off to the human
(live-view), proceed autonomously, or abort. Defaults are safe (hand off for
payments/credentials/irreversible), but a deployment or user who has set up an
agent-usable payment method / autonomous mode can let specific categories
proceed — so the flow is only as intrusive as the user wants.
"""

from app.config.settings import settings
from app.constants.browser import HandoffStrategy, SensitiveCategory

_STRATEGY_SETTING: dict[SensitiveCategory, str] = {
    SensitiveCategory.PAYMENT: "BROWSER_USE_PAYMENT_STRATEGY",
    SensitiveCategory.CREDENTIALS: "BROWSER_USE_CREDENTIALS_STRATEGY",
    SensitiveCategory.IRREVERSIBLE: "BROWSER_USE_IRREVERSIBLE_STRATEGY",
}


def resolve_strategy(
    category: SensitiveCategory, *, autonomous_override: bool | None = None
) -> HandoffStrategy:
    """Return the handoff strategy for a sensitive step.

    ``autonomous_override`` is a per-task signal (e.g. the user told the agent to
    use their agent card): when True, sensitive steps proceed; when False, they
    always hand off; when None, the configured per-category default applies.
    """
    if category == SensitiveCategory.NONE:
        return HandoffStrategy.PROCEED
    # A per-task override always wins over the global setting.
    if autonomous_override is True:
        return HandoffStrategy.PROCEED
    if autonomous_override is False:
        return HandoffStrategy.HANDOFF
    if settings.BROWSER_USE_AUTONOMOUS_SENSITIVE:
        return HandoffStrategy.PROCEED

    setting_name = _STRATEGY_SETTING.get(category)
    raw = getattr(settings, setting_name, None) if setting_name else None
    try:
        return HandoffStrategy(raw) if raw else HandoffStrategy.HANDOFF
    except ValueError:
        return HandoffStrategy.HANDOFF
