"""The observability rules — what each entry point must prove, and its cost.

Ported from evlog's rule registry (``packages/cli/src/lib/map/rules``), with
each check re-expressed in this repo's idiom:

- wide event    → ``log.set(...)`` (HTTP) / ``wide_task()`` ``log_context()`` (workers, voice)
- context       → a canonical ``WideEventFields`` key, so dashboards can query it
- structured errors → ``AppError`` / ``create_error`` / ``HTTPException(detail=...)``
- audit         → ``log.audit(...)`` on money/auth routes
- error handling → every ``except`` logs the error or re-raises it intact

Every rule is a requirement: a failed check costs its weight from the entry
point's 100. Error context and info noise used to be non-scoring nudges; the
backend has since been swept clean of both, so they are held at their own weight
like everything else — the score is the ratchet that keeps them clean.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from directives import Suppression, find_suppression
from facts import FileFacts, HandlerFacts
from sensitivity import Sensitivity

HANDLER_KINDS = ("api", "websocket", "worker", "voice")
HTTP_KINDS = ("api", "websocket")
# Workers keep their historical context exemption; voice entry points set
# canonical VoiceContext fields, so they are held to the context check too.
CONTEXT_KINDS = (*HTTP_KINDS, "voice")

STRUCTURED_ERROR_FACTORIES = frozenset({"AppError", "create_error"})
GENERIC_EXCEPTIONS = frozenset({"Exception", "ValueError", "RuntimeError", "TypeError", "KeyError"})
INFO_NOISE_THRESHOLD = 3


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one rule against one entry point."""

    status: str  # "pass" | "fail" | "n/a"
    message: str = ""
    line: int = 0
    suppressed: bool = False


@dataclass(frozen=True)
class Finding:
    """A gap a rule found; reporting nothing means the rule passed."""

    message: str
    line: int


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule may read about the entry point under review."""

    handler: HandlerFacts
    file_facts: FileFacts
    sensitivity: Sensitivity
    canonical_fields: frozenset[str]


@dataclass(frozen=True)
class Rule:
    """One check: its identity, cost, applicability and verdict function."""

    id: str
    category: str  # "requirement" | "opportunity"
    title: str  # compact chip label for report lines
    question: str
    kinds: tuple[str, ...]
    check: Callable[[RuleContext], Finding | None]
    weight: int = 0
    when: Callable[[RuleContext], bool] | None = None


def _check_wide_event(ctx: RuleContext) -> Finding | None:
    handler = ctx.handler
    if handler.kind == "voice":
        # The LiveKit worker has no logging middleware, so unlike ARQ tasks a
        # bare log.set() proves nothing — only a boundary makes fields emit.
        if handler.has_boundary:
            return None
        return Finding(
            message=(
                "no wide_task()/log_context() boundary — the voice worker has no "
                "middleware, every log.set() here is silently discarded"
            ),
            line=handler.line,
        )
    if handler.kind == "worker":
        if handler.has_boundary or handler.sets_wide_event:
            return None
        return Finding(
            message=(
                "no wide_task()/log_context() boundary — every log.set() in this "
                "task is silently discarded"
            ),
            line=handler.line,
        )
    if handler.sets_wide_event:
        return None
    return Finding(
        message=(
            "handler adds nothing to its request event — only method, path and status are recorded"
        ),
        line=handler.line,
    )


def _check_context(ctx: RuleContext) -> Finding | None:
    if ctx.handler.set_field_names & ctx.canonical_fields:
        return None
    return Finding(
        message=(
            "log.set() uses no canonical WideEventFields key — fields outside the "
            "schema are invisible to the shared dashboards"
        ),
        line=ctx.handler.line,
    )


def _check_structured_errors(ctx: RuleContext) -> Finding | None:
    for raised in ctx.handler.raises:
        if raised.is_bare or raised.callee is None:
            continue
        if raised.callee in STRUCTURED_ERROR_FACTORIES:
            continue
        if raised.callee == "HTTPException":
            if raised.has_detail:
                continue
            return Finding(
                message="HTTPException without detail= — the client learns nothing",
                line=raised.line,
            )
        if raised.callee in GENERIC_EXCEPTIONS:
            return Finding(
                message=(
                    f"raises bare {raised.callee} — use AppError/create_error with "
                    "why/fix so the error explains itself"
                ),
                line=raised.line,
            )
    return None


def _check_audit(ctx: RuleContext) -> Finding | None:
    if ctx.handler.calls_audit:
        return None
    label = ctx.sensitivity.label or "sensitive"
    return Finding(
        message=f"{label} route with no log.audit(...) — no audit trail",
        line=ctx.handler.line,
    )


def _check_error_handling(ctx: RuleContext) -> Finding | None:
    for clause in ctx.handler.excepts:
        if clause.is_empty:
            return Finding(message="empty except block swallows errors", line=clause.line)
        if not clause.handled:
            return Finding(
                message=(
                    "except block loses the caught error — record it on the event "
                    "(log.error/warning) or re-raise it (bare raise, or "
                    "'raise ... from <caught>' so __cause__ survives)"
                ),
                line=clause.line,
            )
    return None


def _check_error_context(ctx: RuleContext) -> Finding | None:
    bare = [
        call
        for call in ctx.handler.log_calls
        if call.method in {"warning", "error", "exception", "critical"}
        and call.msg_is_fstring
        and not call.has_kwargs
    ]
    if not bare:
        return None
    return Finding(
        message=(
            f"{len(bare)} error/warning call(s) interpolate data into prose — pass "
            "structured kwargs (error_type=, ids) so the fields are queryable"
        ),
        line=bare[0].line,
    )


def _check_info_noise(ctx: RuleContext) -> Finding | None:
    info_calls = [call for call in ctx.handler.log_calls if call.method == "info"]
    if len(info_calls) < INFO_NOISE_THRESHOLD:
        return None
    return Finding(
        message=(
            f"{len(info_calls)} log.info() lines — info never reaches the wide "
            "event; accumulate context with log.set() instead"
        ),
        line=info_calls[0].line,
    )


RULES: tuple[Rule, ...] = (
    Rule(
        id="wide-event",
        category="requirement",
        title="logger",
        question="Does this entry point contribute to a wide event?",
        kinds=HANDLER_KINDS,
        weight=40,
        check=_check_wide_event,
    ),
    Rule(
        id="context",
        category="requirement",
        title="context",
        question="Does it attach canonical, queryable context?",
        kinds=CONTEXT_KINDS,
        weight=15,
        when=lambda ctx: ctx.handler.sets_wide_event,
        check=_check_context,
    ),
    Rule(
        id="structured-errors",
        category="requirement",
        title="errors",
        question="Do raised errors explain why and what to do next?",
        kinds=HANDLER_KINDS,
        weight=20,
        when=lambda ctx: any(not r.is_bare for r in ctx.handler.raises),
        check=_check_structured_errors,
    ),
    Rule(
        id="audit",
        category="requirement",
        title="audit",
        question="Do sensitive operations leave an audit trail?",
        kinds=("api",),
        weight=25,
        when=lambda ctx: ctx.sensitivity.level == "high",
        check=_check_audit,
    ),
    Rule(
        id="error-handling",
        category="requirement",
        title="catch",
        question="Does every caught error survive its except block?",
        kinds=HANDLER_KINDS,
        weight=15,
        when=lambda ctx: bool(ctx.handler.excepts),
        check=_check_error_handling,
    ),
    Rule(
        id="error-context",
        category="requirement",
        title="err-ctx",
        question="Do error logs carry structured fields?",
        kinds=HANDLER_KINDS,
        weight=15,
        check=_check_error_context,
    ),
    Rule(
        id="info-noise",
        category="requirement",
        title="info",
        question="Is real-time narration standing in for event context?",
        kinds=HANDLER_KINDS,
        weight=10,
        check=_check_info_noise,
    ),
)

REQUIREMENTS: tuple[Rule, ...] = tuple(r for r in RULES if r.category == "requirement")
RULE_IDS: frozenset[str] = frozenset(r.id for r in RULES)


@dataclass
class RuleResults:
    """Requirement results and opportunity results, kept apart."""

    checks: dict[str, CheckResult] = field(default_factory=dict)
    suggestions: dict[str, CheckResult] = field(default_factory=dict)


def run_rules(ctx: RuleContext, suppressions: list[Suppression]) -> RuleResults:
    """Every applicable rule against one entry point.

    Irrelevant-by-kind rules are left out entirely; rules gated by ``when``
    report ``n/a``; suppressed findings report ``n/a`` with the comment's
    reason — never ``pass``, so waived coverage stays visible.
    """
    results = RuleResults()
    for rule in RULES:
        if ctx.handler.kind not in rule.kinds:
            continue
        bucket = results.checks if rule.category == "requirement" else results.suggestions
        if rule.when and not rule.when(ctx):
            if rule.category == "requirement":
                bucket[rule.id] = CheckResult(status="n/a")
            continue
        finding = rule.check(ctx)
        if finding is None:
            # An opportunity with nothing to say is silence, not a row.
            if rule.category == "requirement":
                bucket[rule.id] = CheckResult(status="pass")
            continue
        anchor_lines = (finding.line, ctx.handler.line, ctx.handler.deco_line)
        suppression = find_suppression(suppressions, rule.id, anchor_lines)
        if suppression:
            if rule.category == "requirement":
                bucket[rule.id] = CheckResult(
                    status="n/a",
                    message=f"disabled: {suppression.reason}",
                    line=suppression.declared_at,
                    suppressed=True,
                )
            continue
        bucket[rule.id] = CheckResult(status="fail", message=finding.message, line=finding.line)
    return results
