"""The feature flag registry: every flag GAIA evaluates is declared here, once.

A flag is a FeatureFlag member plus one FlagSpec entry in FEATURE_FLAGS. The
spec carries the dashboard description and the env default (read at call time,
so the setting stays the kill switch when PostHog cannot decide). A flag with a
user_toggle is user-facing: it is listed in Settings and a user's stored choice
beats the PostHog rollout. A flag without one is internal: evaluated by PostHog
only, never exposed to users, and a stored choice for it is ignored.
Evaluation lives in app/services/feature_flags.py.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from app.config.settings import settings


class FeatureFlag(StrEnum):
    """PostHog flag keys GAIA evaluates; member name is the code handle, value the dashboard key."""

    COMMS_OPENUI = "COMMS_OPENUI"
    CODE_MODE = "CODE_MODE"
    HIL_LEDGER = "HIL_LEDGER"
    HIL_JEV_JUDGE = "HIL_JEV_JUDGE"
    HIL_JEV_REPLY = "HIL_JEV_REPLY"
    BROWSER_OBSCURA = "BROWSER_OBSCURA"


class FeatureStage(StrEnum):
    """How finished a user-facing feature is, shown next to its toggle."""

    EXPERIMENTAL = "experimental"


@dataclass(frozen=True, kw_only=True)
class UserToggle:
    """The Settings copy for a flag users may switch themselves."""

    label: str
    description: str
    stage: FeatureStage


@dataclass(frozen=True, kw_only=True)
class FlagSpec:
    """One flag: its dashboard description, its default, and whether users may toggle it."""

    description: str
    default: Callable[[], bool]
    user_toggle: UserToggle | None = None


FEATURE_FLAGS: dict[FeatureFlag, FlagSpec] = {
    FeatureFlag.COMMS_OPENUI: FlagSpec(
        description=(
            "Include the OpenUI component reference in the comms prompt on "
            "renderable channels; off serves the markdown fallback."
        ),
        default=lambda: settings.ENABLE_COMMS_OPENUI,
    ),
    FeatureFlag.CODE_MODE: FlagSpec(
        description=(
            "Bash runs seed the `gaia.execute` client and mint a per-invocation "
            "token; off runs bash with no GAIA_EXECUTE_* env."
        ),
        default=lambda: settings.ENABLE_CODE_MODE,
    ),
    FeatureFlag.HIL_LEDGER: FlagSpec(
        description=(
            "Gated calls register PENDING in the approval ledger and return "
            "instead of parking the run; off keeps the interrupt barrier."
        ),
        default=lambda: settings.ENABLE_HIL_LEDGER,
    ),
    FeatureFlag.HIL_JEV_JUDGE: FlagSpec(
        description=(
            "Auto mode classifies with the JEV choice judge first, falling back "
            "to the LLM intent judge on transport failure; off keeps the LLM judge."
        ),
        default=lambda: settings.ENABLE_HIL_JEV_JUDGE,
    ),
    FeatureFlag.HIL_JEV_REPLY: FlagSpec(
        description=(
            "A bot user's chat reply to pending approvals is classified by the JEV "
            "reply classifier first, falling back to the LLM classifier on transport "
            "failure; off keeps the LLM classifier."
        ),
        default=lambda: settings.ENABLE_HIL_JEV_REPLY,
    ),
    FeatureFlag.BROWSER_OBSCURA: FlagSpec(
        description=(
            "Browser tasks run on the self-hosted Obscura engine instead of Chrome; "
            "a task Obscura cannot finish falls back to Chrome."
        ),
        default=lambda: False,
        user_toggle=UserToggle(
            label="Obscura browser engine",
            description=(
                "Run browser tasks on Obscura, a lighter self-hosted engine. It may "
                "break on some sites; when it does, GAIA falls back to Chrome."
            ),
            stage=FeatureStage.EXPERIMENTAL,
        ),
    ),
}
