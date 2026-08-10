"""Shared types for the GAIA eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

#: The score at or above which a gate counts as satisfied.
#:
#: It lives here because two modules have to agree on it: the run loop grades a
#: case against it, and the falsifiability sweep asks whether a forgery cleared
#: it. Two literals drift, and a drift makes the sweep report a gate as proven
#: while the run loop passes it.
GATE_PASS_THRESHOLD = 0.5


@dataclass
class Case:
    """One eval scenario: prompt(s), ground truth, and how to run/score it."""

    id: str
    ticket: str
    prompt: str
    expected: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    transport: str = "in-process"
    setup: dict[str, Any] = field(default_factory=dict)

    @property
    def gates(self) -> list[str]:
        return list(self.expected.get("score", {}).get("gates", []))

    @property
    def skip_reason(self) -> str:
        """Why we decline to attempt this case, or "" if we attempt it.

        A skip is not an outage. An outage means we failed to conduct the test
        and the case leaves the denominator; a skip means the question was asked
        of us and we have no way to answer it — an unsupported attachment, a
        capability we lack — which on an external benchmark is a wrong answer
        worth 0.0, in the denominator, exactly as that benchmark's own scorer
        counts it. Declared on the case rather than inferred from the run's error
        text, because a skip and a crash both arrive as a string and telling them
        apart by reading it is how they got conflated in the first place.
        """
        return str(self.expected.get("skip_reason") or "")


@dataclass
class CaseRun:
    """What actually happened when the agent ran a case."""

    case_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    end_state: dict[str, Any] | None = None
    text: str = ""
    raw: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    duration_s: float = 0.0
    error: str | None = None


@dataclass(frozen=True)
class ProviderPrice:
    """List price for a lane's model, plus the discount actually applied to it.

    Two costs fall out of this and they answer different questions: list cost is
    what reproducing the eval costs at rack rate (the comparable number), paid
    cost is what the lane actually billed us (the budget number).
    """

    price_in_per_1m: float = 0.0
    price_out_per_1m: float = 0.0
    discount_pct: float = 0.0

    def list_cost(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in / 1e6 * self.price_in_per_1m + tokens_out / 1e6 * self.price_out_per_1m

    def paid_cost(self, tokens_in: int, tokens_out: int) -> float:
        return self.list_cost(tokens_in, tokens_out) * max(0.0, 1.0 - self.discount_pct / 100.0)


PriceBook = dict[str, ProviderPrice]

_NO_PRICE = ProviderPrice()


@dataclass
class CaseTrace:
    """One case execution as Opik sees it: identity, outcome, and the meter.

    Built from a journal record so the live run loop and the backfill seeder
    produce byte-identical traces — the journal is the only source of truth.
    """

    run_id: str
    case_id: str
    ticket: str
    prompt: str
    output: str
    status: str
    provider: str
    model: str
    category: str = ""
    suite: str = ""
    app_version: str = ""
    tokens_source: str = "unknown"
    """How this case's tokens were obtained: metered | estimated | none | unknown.

    Cost is tokens times a price, so a cost figure is only as trustworthy as the
    count under it. Three suites measured tokens by differencing a *shared* run
    meter while 3-14 cases ran concurrently, crediting each case with its
    neighbours' spend; two never measured at all and inferred tokens from string
    length. Carrying the provenance onto the trace is what lets a reader — and
    :mod:`.ingest_check` — refuse to add an estimate into a dollar total.
    ``unknown`` means the journal predates the field and must not be trusted.
    """
    scores: dict[str, float] = field(default_factory=dict)
    duration_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    list_cost_usd: float = 0.0
    discount_pct: float = 0.0
    error: str = ""
    ended_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tool_calls: tuple[dict[str, Any], ...] = ()
    """What the agent actually did, straight from the journal. Rendered as one
    ``tool`` span per call so a reader inspecting a failed case in Opik sees the
    calls, not just the final text."""
    rescored: bool = False
    """True when this verdict was adopted from a rescore sibling rather than
    the original run — visible so a re-graded verdict is never mistaken for an
    original one."""

    @property
    def name(self) -> str:
        return f"case-{self.case_id}"

    @property
    def key(self) -> tuple[str, str]:
        """Identity for idempotent seeding: one trace per case per run.

        The run id has to be part of it — the same case legitimately re-runs in
        later runs, and those are distinct executions, not duplicates.
        """
        return (self.name, self.run_id)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            # Named run_id, not run: this is the key every consumer reaches for,
            # and an audit that looked for "run_id" concluded no trace carried a
            # run at all — the data was there under a name nobody guessed.
            "run_id": self.run_id,
            # Without these three a trace cannot be attributed to a suite, a
            # build, or a case without joining back to the journal by hand. That
            # is what made a corrupt run impossible to exclude from a total.
            "suite": self.suite,
            "app_version": self.app_version,
            "case_id": self.case_id,
            "tokens_source": self.tokens_source,
            "provider": self.provider,
            "model": self.model,
            "status": self.status,
            # The dimension every dashboard breaks accuracy down by. A suite's
            # aggregate pass rate hides which capability is broken, and Opik can
            # only group by a key the trace actually carries — so a case's
            # category has to travel with it, not stay behind in the journal.
            "category": self.category,
            "ticket": self.ticket,
            "rescored": self.rescored,
            "duration_s": round(self.duration_s, 2),
            "tokens": self.tokens_in + self.tokens_out,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "list_cost_usd": round(self.list_cost_usd, 6),
            "discount_pct": self.discount_pct,
            "scored": sorted(self.scores),
            "error": self.error,
            "errored": bool(self.error),
        }

    @property
    def started_at(self) -> datetime:
        """Real wall-clock start, so replayed traces land on the timeline they
        actually ran on instead of bunching up at seed time."""
        return self.ended_at - timedelta(seconds=self.duration_s)

    @property
    def tokens_trusted(self) -> bool:
        """Whether these counts may be turned into a number anyone reads.

        Opik derives a project's cost and token totals from what the span
        carries, so publishing an unmetered count does not produce a rough
        figure — it produces a precise, wrong, official-looking one, which is
        worse than an empty panel that prompts someone to ask why.
        """
        return self.tokens_source == "metered"

    @property
    def usage(self) -> dict[str, int] | None:
        """Token usage in the shape Opik aggregates on, or None if untrusted."""
        if not self.tokens_trusted:
            return None
        return {
            "prompt_tokens": self.tokens_in,
            "completion_tokens": self.tokens_out,
            "total_tokens": self.tokens_in + self.tokens_out,
        }

    @property
    def error_info(self) -> dict[str, str] | None:
        """Opik's error envelope — for cases that ERRORED, never merely failed.

        A graded wrong answer records why it was wrong in ``error`` too ("gate
        score below threshold"), and writing that into the envelope made every
        failed case count as an error in Opik's project list — 105 phantom
        "errors" on suites whose runs had zero. The envelope means "the machine
        broke", and only an errored status earns it.

        All three keys are required by the API — omitting ``traceback`` fails
        validation and silently drops the whole trace.
        """
        if not self.error or self.status != "errored":
            return None
        kind, _, message = self.error.partition(": ")
        return {
            "exception_type": kind or "EvalFailure",
            "message": message or self.error,
            "traceback": self.error,
        }

    @classmethod
    def from_record(
        cls,
        run_id: str,
        record: dict[str, Any],
        prices: PriceBook,
        *,
        suite: str,
        app_version: str,
    ) -> CaseTrace:
        """Build the trace for one journaled case.

        ``suite`` and ``app_version`` are required, and keyword-only, because
        they used to default to "". The seeder passed them and the live run loop
        did not, so every trace written during a run was missing both while the
        same case re-seeded later carried them — two sources of truth for one
        trace, reconciled only by whoever happened to re-seed. A default is what
        let one caller silently omit them; without one, the omission is a
        TypeError at import time rather than a blank field in a dashboard.
        """
        tokens = record.get("tokens") or {}
        tokens_in = int(tokens.get("input", 0))
        tokens_out = int(tokens.get("output", 0))
        source = str(tokens.get("source") or "unknown")
        # A price times a guess is not a cost: only provider-metered figures may
        # be priced. Estimates and legacy unmetered counts keep their tokens
        # (labelled) but carry zero cost, so no dashboard total launders them.
        price = (
            prices.get(record.get("provider", ""), _NO_PRICE) if source == "metered" else _NO_PRICE
        )
        # Older journals carry the category only inside the case's expectations;
        # newer ones lift it to the top level. Both are the same declaration.
        expected = record.get("expected") or {}
        return cls(
            run_id=run_id,
            case_id=record["case_id"],
            ticket=record.get("ticket", ""),
            prompt=record.get("prompt", ""),
            output=record.get("text") or _last_assistant(record.get("messages") or []),
            status=record.get("status", "?"),
            provider=record.get("provider", "?"),
            model=record.get("model", "?"),
            category=str(record.get("category") or expected.get("category") or "uncategorised"),
            suite=suite,
            app_version=app_version,
            tokens_source=source,
            scores=record.get("scores") or {},
            duration_s=float(record.get("duration_s") or 0.0),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=price.paid_cost(tokens_in, tokens_out),
            list_cost_usd=price.list_cost(tokens_in, tokens_out),
            discount_pct=price.discount_pct,
            error=record.get("error") or "",
            ended_at=_parse_ts(record.get("ts")),
            tool_calls=tuple(record.get("tool_calls") or []),
            rescored=bool(record.get("rescored")),
        )


def _parse_ts(value: object) -> datetime:
    """Journal timestamp, falling back to now for pre-``ts`` records."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def _last_assistant(messages: list[dict[str, str]]) -> str:
    """Fallback output for journals written before records carried ``text``."""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            return str(message.get("content", ""))
    return str(messages[-1].get("content", "")) if messages else ""


@dataclass
class ProviderError(Exception):
    """Raised by a transport when the provider itself failed (not the agent).

    Triggers rotation to the next provider in the catalog.
    """

    provider: str
    reason: str

    def __str__(self) -> str:
        return f"provider {self.provider} failed: {self.reason}"


@dataclass
class InfraError(Exception):
    """Raised by a transport when a backend the suite needs is unavailable.

    Distinct from :class:`ProviderError`: rotating to another LLM lane cannot
    fix a dead datastore, and nothing about the agent was measured. The run
    loop aborts instead of journaling cases that never ran — an outage graded
    as a wrong answer becomes a fabricated 0% in the report.
    """

    backend: str
    reason: str

    def __str__(self) -> str:
        return f"{self.backend} unavailable: {self.reason}"


class ProviderHealth:
    """Result of a boot-time provider health check."""

    def __init__(self, ok: bool, reason: str = "") -> None:
        self.ok = ok
        self.reason = reason

    def __bool__(self) -> bool:
        return self.ok
