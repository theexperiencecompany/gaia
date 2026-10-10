"""Sensitivity classification (money / auth / PII) per entry point.

Ported from evlog's ``sensitivity.ts``: whole-word term matching on the route
path (anchored, so ``/api/authors`` is not "auth"), package imports, and
PII-field-names-next-to-write-calls. A high-sensitivity route gets the
25-point audit requirement and counts double in the global score.

The term lists are upstream's, tuned to this repo: ``session``, ``register``
and ``token`` are dropped (here they name chat sessions, device registration
and LiveKit media tokens — pure false positives), and ``usage`` is added on
the money side (usage endpoints are plan-quota/billing adjacent). Genuine
auth surfaces still match via ``auth``/``login``/``oauth``/… or the ``workos``
import — except the handful that carry no such word at all, which
``CREDENTIAL_ROUTES`` names one mounted path at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from facts import FileFacts, HandlerFacts, repo_relative

MONEY_IMPORTS = frozenset({"stripe", "razorpay", "dodopayments", "paddle"})
AUTH_IMPORTS = frozenset({"workos"})

MONEY_TERMS = (
    "checkout",
    "payment",
    "billing",
    "invoice",
    "refund",
    "subscription",
    "charge",
    "payout",
    "usage",
)
AUTH_TERMS = (
    "auth",
    "oauth",
    "login",
    "logout",
    "signin",
    "signup",
    "password",
    "mfa",
    "otp",
)

_PII_FIELDS = re.compile(r"email|phone|address|ssn|iban", re.IGNORECASE)

# Credential and account-takeover surfaces no term list can see: none of them
# contains an auth word, and the words that *would* catch them (``token``,
# ``session``, ``register``) name chat sessions and LiveKit media tokens far
# more often than credentials here — re-adding them would mislabel dozens of
# routes. Enumerating the real ones by their mounted path is the honest
# mechanism: refresh-token rotation, device pairing, the one-time connect-code
# redemption, and binding a chat account to a GAIA account.
CREDENTIAL_ROUTES = frozenset(
    {
        "/api/v1/device/token",
        "/api/v1/device/pair/start",
        "/api/v1/device/pair/poll",
        "/api/v1/device/pair/approve",
        "/api/v1/integrations/connect-link",
        "/api/v1/platform-links/{platform}",
        "/api/v1/bot/create-link-token",
        "/api/v1/bot/unlink",
        "/api/v1/bot/link-token-info/{token}",
    }
)


def _compile_terms(terms: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple(
        (term, re.compile(rf"(?:^|[^a-z0-9]){term}s?(?:[^a-z0-9]|$)", re.IGNORECASE))
        for term in terms
    )


_MONEY_PATTERNS = _compile_terms(MONEY_TERMS)
_AUTH_PATTERNS = _compile_terms(AUTH_TERMS)


@dataclass(frozen=True)
class Sensitivity:
    """How much an entry point matters: money/auth high, PII medium."""

    # One ordered vocabulary across both scanners: "low" | "medium" | "high".
    # scripts/ci/checks.mjs evlog-map-bots classifies binary (low/high) and has no PII
    # tier; naming the floor "none" instead of "low" made the two reports
    # incomparable on a field they both emit, for no gain.
    level: str  # "high" | "medium" | "low"
    reasons: tuple[str, ...]

    @property
    def label(self) -> str:
        if any(reason.startswith("money:") for reason in self.reasons):
            return "money"
        if any(reason.startswith("auth:") for reason in self.reasons):
            return "auth"
        if self.level == "medium":
            return "pii"
        return ""


def _match_term(haystack: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    for term, pattern in patterns:
        if pattern.search(haystack):
            return term
    return None


def classify(handler: HandlerFacts, file_facts: FileFacts) -> Sensitivity:
    """Classify one entry point from its route path, module path and imports."""
    reasons: list[str] = []
    haystack = f"{repo_relative(file_facts.path)} {handler.route_path}".lower()

    for pkg in sorted(MONEY_IMPORTS & file_facts.imports):
        reasons.append(f"money: imports {pkg}")
    money_term = _match_term(haystack, _MONEY_PATTERNS)
    if money_term:
        reasons.append(f'money: path says "{money_term}"')

    for pkg in sorted(AUTH_IMPORTS & file_facts.imports):
        reasons.append(f"auth: imports {pkg}")
    auth_term = _match_term(haystack, _AUTH_PATTERNS)
    if auth_term:
        reasons.append(f'auth: path says "{auth_term}"')
    for route in sorted(set(handler.route_paths) & CREDENTIAL_ROUTES):
        reasons.append(f"auth: {route} issues or redeems a credential")

    touches_pii = any(_PII_FIELDS.search(name) for name in file_facts.names)
    if touches_pii and file_facts.has_write_calls:
        reasons.append("pii: write operation with sensitive fields")

    has_money = any(reason.startswith("money:") for reason in reasons)
    has_auth = any(reason.startswith("auth:") for reason in reasons)
    if has_money or has_auth:
        return Sensitivity(level="high", reasons=tuple(reasons))
    if reasons:
        return Sensitivity(level="medium", reasons=tuple(reasons))
    return Sensitivity(level="low", reasons=())
