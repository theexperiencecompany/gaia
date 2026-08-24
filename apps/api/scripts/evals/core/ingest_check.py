"""Verify what actually landed in Opik, by asking Opik.

This exists because of how the ingestion defects survived: every one of them was
"confirmed" by reading the code that does the writing. The writer looked correct
and was correct in isolation — a gate really did produce a score, a trace really
did carry a run id. Nobody queried the result and asked whether the totals made
sense, so a project accumulated 25,144 traces for a 45-case suite, and another
reported 461,794,459 tokens (~700k per trace, for single agent runs) and nobody
noticed for days.

So this is deliberately not a unit test of our writer. It is an independent
reader that pulls the numbers back out of the live backend and refuses to call
an ingest successful when they are impossible, or when they disagree with the
journals on disk — which are the source of truth. :mod:`.invariants` does the
same job for journals; this is the same idea one layer out.

Run it after every seed. A check nobody runs is a check that does not exist.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from http import HTTPStatus
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .journal import RunJournal
from .seed import SEEDABLE_STATUSES

#: One case is one agent run. Even a long multi-turn LongMemEval case with a
#: haystack of sessions lands in the low hundreds of thousands; past this the
#: number is not a big case, it is an accumulator that was never reset.
#: The bound nobody had. Every check here originally looked only for numbers too
#: LARGE, which is why two suites reporting medians of 56 and 16 tokens per case
#: went unnoticed for months: a case cannot run an agent, with a system prompt,
#: for two seconds and spend fifty tokens. Too-small is as wrong as too-large and
#: is much easier to miss, because an implausibly cheap number looks like good
#: news. Only applied to cases that actually worked (see MIN_WORKING_SECONDS) so
#: an instant refusal or a cache hit is not flagged.
#:
#: There is deliberately no upper bound. One was tried at 400k and it was
#: measuring the wrong thing: instrumenting the live API showed a trivial
#: one-word exchange costs ~22.7k input tokens per turn on this stack (system
#: prompt plus tool schemas dominate), and a real capability case has a median of
#: 131k with legitimate cases reaching 9.6M. Size never separated corrupt from
#: expensive — an honest run just is expensive. ``tokens_source`` is the
#: discriminator, and a cap would only have flagged honest data.
MIN_TOKENS_PER_WORKING_TRACE = 500
MIN_WORKING_SECONDS = 2.0

#: Statuses that reached a verdict, so a token reading was owed. ``errored`` is
#: absent on purpose — the case never got far enough to spend anything.
GRADED_STATUSES = frozenset({"passed", "failed", "skipped"})

#: A whole suite costing more than this locally means the token counts feeding
#: it are wrong, not that we spent it — every lane here is cheap or free.
MAX_PLAUSIBLE_PROJECT_COST_USD = 15.0

#: The only provenance whose tokens may be turned into a dollar figure. Anything
#: else is a guess wearing a number's clothes: ``estimated`` is len(text)//4 and
#: cannot see a system prompt, and ``unknown`` is a pre-fix journal whose counts
#: were differenced off a meter shared by concurrent cases.
TRUSTED_TOKEN_SOURCE = "metered"

_PAGE = 1000


@dataclass
class ProjectFacts:
    """What Opik reports for one project, read back rather than assumed."""

    name: str
    exists: bool = True
    traces: int = 0
    case_traces: int = 0
    non_case_traces: int = 0
    non_case_names: dict[str, int] = field(default_factory=dict)
    opik_owned_traces: int = 0
    traces_with_cost: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    errors: int = 0
    duplicate_keys: int = 0
    missing_metadata: dict[str, int] = field(default_factory=dict)
    max_trace_tokens: int = 0
    token_sources: dict[str, int] = field(default_factory=dict)
    starved_traces: int = 0
    starved_examples: list[str] = field(default_factory=list)
    untrusted_cost_usd: float = 0.0

    @property
    def tokens_per_trace(self) -> float:
        return self.total_tokens / self.case_traces if self.case_traces else 0.0


@dataclass
class Finding:
    """One reason an ingest must not be called successful."""

    project: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"  {self.project:<20} {self.rule:<22} {self.detail}"


#: Metadata every trace must carry. Without these a trace cannot be attributed
#: to a run, a suite or a build — which is what made corrupt runs unfilterable
#: and forced a full teardown instead of a targeted purge.
REQUIRED_METADATA = ("run_id", "suite", "app_version", "case_id")

#: Keys the journal may genuinely not know. ``app_version`` was added after most
#: of these runs were recorded, so a trace from an older journal cannot carry it
#: and no amount of re-ingesting will conjure one.
#:
#: Handled the way :mod:`.flaky` handles the identical problem: unstamped runs
#: are POOLED APART rather than tolerated. There, outcomes from runs with no
#: version go in their own bucket so they can neither manufacture a flake nor be
#: credited to a fix; here, traces from unstamped runs are counted and reported
#: as their own category so they can never be mistaken for stamped ones. In both
#: cases the unstamped data stays visible and stays out of the comparison.
#:
#: Absence is a FAILURE only when the run's own journal HAS the value and it did
#: not reach the trace — that is a propagation defect, and it is the case this
#: check exists to catch. Failing on the rest would make the check permanently
#: red, and a check that cannot pass gets switched off.
BEST_EFFORT_METADATA = frozenset({"app_version"})

#: Trace names Opik itself writes. ``evaluate()`` opens one ``evaluation_task``
#: trace per dataset item, so these are the experiment machinery working, not
#: our pollution. Excluding them keeps the non-case rule pointed at the real
#: defect — a check that reports a known-good thing as a fault gets ignored, and
#: then it is not a check.
OPIK_OWNED_TRACE_NAMES = frozenset({"evaluation_task"})


def _api(base_url: str, path: str, **query: object) -> dict[str, object]:
    response = httpx.get(
        f"{base_url}{path}",
        params={key: str(value) for key, value in query.items()},
        headers={"Comet-Workspace": "default"},
        timeout=120,
    )
    response.raise_for_status()
    loaded: dict[str, object] = response.json()
    return loaded


def api_base(url_override: str) -> str:
    """The private REST root, derived from OPIK_URL_OVERRIDE.

    The scheme is checked here rather than suppressed at the call site: this URL
    comes from the environment, and ``urlopen`` would happily accept ``file:``
    and turn a misconfigured variable into a local file read.
    """
    parsed = urlparse(url_override)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"OPIK_URL_OVERRIDE must be http(s), got {url_override!r}")
    return url_override.rstrip("/") + "/v1/private"


def project_names(base_url: str, prefix: str = "gaia-") -> list[str]:
    content = _api(base_url, "/projects", size=200).get("content")
    if not isinstance(content, list):
        return []
    names = [str(p.get("name")) for p in content if isinstance(p, dict)]
    return sorted(n for n in names if n.startswith(prefix))


def trace_count(base_url: str, project: str) -> int:
    """How many traces a project holds, without downloading any of them."""
    return int(str(_api(base_url, "/traces", project_name=project, size=1).get("total") or 0))


class ProjectMissingError(LookupError):
    """The project holds no traces because it does not exist."""


def _all_traces(base_url: str, project: str) -> list[dict[str, object]]:
    """Every trace, paginated.

    The first audit of this data summed cost over a single 2,000-row page while
    printing the server's full count beside it, so a project past one page
    reported a truncated cost against a complete trace count. Reading all of it
    is the only way the totals mean anything.
    """
    out: list[dict[str, object]] = []
    page = 1
    while True:
        try:
            data = _api(base_url, "/traces", project_name=project, page=page, size=_PAGE)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != HTTPStatus.NOT_FOUND:
                raise
            raise ProjectMissingError(project) from e
        chunk = data.get("content") or []
        if not isinstance(chunk, list):
            return out
        out.extend(item for item in chunk if isinstance(item, dict))
        total = int(str(data.get("total") or 0))
        if len(chunk) < _PAGE or len(out) >= total:
            return out
        page += 1


def read_project(base_url: str, project: str) -> ProjectFacts:
    facts = ProjectFacts(name=project)
    try:
        traces = _all_traces(base_url, project)
    except ProjectMissingError:
        # Absent, not empty. Reported as zero traces so the journal comparison
        # fires — the alternative, skipping it, is how a stage that wrote nothing
        # came to report success.
        facts.exists = False
        return facts
    keys: Counter[tuple[str, str]] = Counter()
    missing: Counter[str] = Counter()
    non_case: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for trace in traces:
        facts.traces += 1
        name = str(trace.get("name") or "")
        metadata = trace.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if not name.startswith("case-"):
            if name in OPIK_OWNED_TRACE_NAMES:
                facts.opik_owned_traces += 1
                continue
            facts.non_case_traces += 1
            non_case[name or "<unnamed>"] += 1
            continue
        facts.case_traces += 1
        keys[(name, str(metadata.get("run_id") or ""))] += 1
        for key in REQUIRED_METADATA:
            if not metadata.get(key):
                missing[key] += 1
        cost = float(str(trace.get("total_estimated_cost") or 0) or 0)
        facts.total_cost_usd += cost
        facts.traces_with_cost += 1 if cost > 0 else 0
        usage = trace.get("usage")
        tokens = int(str((usage or {}).get("total_tokens") or 0)) if isinstance(usage, dict) else 0
        facts.total_tokens += tokens
        facts.max_trace_tokens = max(facts.max_trace_tokens, tokens)
        facts.errors += 1 if trace.get("error_info") else 0
        source = str(metadata.get("tokens_source") or "unknown")
        sources[source] += 1
        if source != TRUSTED_TOKEN_SOURCE:
            facts.untrusted_cost_usd += cost
        worked = float(str(metadata.get("duration_s") or 0) or 0) >= MIN_WORKING_SECONDS
        # Only meaningful for a metered trace that reached a verdict. An
        # unmetered one reports zero because we withheld it, and an errored one
        # because the case died before it could spend anything — that is the
        # outage showing through, not a broken meter, and it fires on exactly
        # the runs an outage already ruined.
        #
        # Judged on STATUS, not on whether an error string is present: 424
        # records are `failed` and still carry one ("gate score below
        # threshold"), because a graded wrong answer records why it was wrong.
        # Keying on the string would have silently exempted every one of them.
        if (
            source == TRUSTED_TOKEN_SOURCE
            and worked
            and str(metadata.get("status") or "") in GRADED_STATUSES
            and tokens < MIN_TOKENS_PER_WORKING_TRACE
        ):
            facts.starved_traces += 1
            if len(facts.starved_examples) < 5:
                facts.starved_examples.append(
                    f"{trace.get('name')}@{metadata.get('run_id')}={tokens}tok"
                )
    facts.token_sources = dict(sources)
    facts.duplicate_keys = sum(n - 1 for n in keys.values() if n > 1)
    facts.missing_metadata = dict(missing)
    facts.non_case_names = dict(non_case.most_common(6))
    return facts


def journal_expectations(
    runs_dir: Path, suite_projects: dict[str, str], only_projects: set[str] | None = None
) -> dict[str, int]:
    """How many distinct case traces each project should hold, per the journals.

    Distinct ``(case, run)`` pairs, not records: a journal legitimately carries
    the same case twice when a run was resumed, and both collapse onto one trace.

    A run marked ``excluded`` is left out, because the ingest never writes it —
    counting it here would report a mismatch on every correctly-skipped run.
    """
    expected: Counter[str] = Counter()
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not run_dir.is_dir() or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        # Same filter as ingest: a still-running run appends between seed and
        # read-back, so counting it makes the reconciliation a moving target.
        if meta.get("excluded") or str(meta.get("status") or "") == "running":
            continue
        project = suite_projects.get(str(meta.get("suite") or ""))
        if project is None or (only_projects is not None and project not in only_projects):
            continue
        seen = {
            str(record["case_id"])
            for record in RunJournal(runs_dir, run_dir.name).records()
            if record.get("status") in SEEDABLE_STATUSES
        }
        expected[project] += len(seen)
    return dict(expected)


def journal_missing_app_version(
    runs_dir: Path, suite_projects: dict[str, str], only_projects: set[str] | None = None
) -> dict[str, int]:
    """Case records per project whose own run.json records no app_version."""
    unknown: Counter[str] = Counter()
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not run_dir.is_dir() or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        if meta.get("excluded") or meta.get("app_version"):
            continue
        project = suite_projects.get(str(meta.get("suite") or ""))
        if project is None or (only_projects is not None and project not in only_projects):
            continue
        unknown[project] += len(
            {
                str(record["case_id"])
                for record in RunJournal(runs_dir, run_dir.name).records()
                if record.get("status") in SEEDABLE_STATUSES
            }
        )
    return dict(unknown)


def check(
    facts: ProjectFacts, expected_cases: int | None, unversioned_cases: int = 0
) -> list[Finding]:
    """Every way this project's data is impossible or disagrees with the journals."""
    found: list[Finding] = []
    if not facts.exists:
        return [
            Finding(
                facts.name,
                "project missing",
                f"the journals describe {expected_cases or 0} case(s) here and the project does "
                f"not exist — the seed wrote nothing",
            )
        ]
    if facts.non_case_traces:
        found.append(
            Finding(
                facts.name,
                "non-case traces",
                f"{facts.non_case_traces} traces that are not cases: {facts.non_case_names} "
                f"— gate results belong on a case trace as feedback scores",
            )
        )
    if facts.duplicate_keys:
        found.append(
            Finding(
                facts.name,
                "duplicates",
                f"{facts.duplicate_keys} redundant traces for a (case, run) that already exists",
            )
        )
    for key, count in sorted(facts.missing_metadata.items()):
        if key not in BEST_EFFORT_METADATA:
            found.append(
                Finding(facts.name, "missing metadata", f"{count} case traces carry no {key!r}")
            )
            continue
        # Only the excess over what the journals themselves cannot supply is a
        # defect; the rest is reported as `unstamped` in the table, not hidden.
        unexplained = count - unversioned_cases
        if unexplained > 0:
            found.append(
                Finding(
                    facts.name,
                    "metadata not propagated",
                    f"{unexplained} case traces carry no {key!r} even though their run.json "
                    f"records one — the value exists and did not reach the trace",
                )
            )
    if facts.starved_traces:
        found.append(
            Finding(
                facts.name,
                "implausible tokens",
                f"{facts.starved_traces} traces worked >={MIN_WORKING_SECONDS:g}s but report "
                f"<{MIN_TOKENS_PER_WORKING_TRACE} tokens — an agent turn cannot be that cheap: "
                f"{facts.starved_examples}",
            )
        )
    if facts.untrusted_cost_usd > 0:
        untrusted = {k: v for k, v in facts.token_sources.items() if k != TRUSTED_TOKEN_SOURCE}
        found.append(
            Finding(
                facts.name,
                "untrusted cost",
                f"${facts.untrusted_cost_usd:,.3f} of cost comes from tokens that were not "
                f"metered: {untrusted} — a price times a guess is not a cost",
            )
        )
    if facts.total_cost_usd > MAX_PLAUSIBLE_PROJECT_COST_USD:
        found.append(
            Finding(
                facts.name,
                "implausible cost",
                f"${facts.total_cost_usd:,.2f} for {facts.case_traces} cases",
            )
        )
    metered = facts.token_sources.get(TRUSTED_TOKEN_SOURCE, 0)
    if metered and facts.total_tokens == 0:
        # Only a fault when the tokens were supposed to be there. A project whose
        # counts were deliberately withheld as unmetered reports zero on purpose,
        # and flagging that would train people to ignore the finding.
        found.append(
            Finding(
                facts.name,
                "no tokens",
                f"{metered} case traces claim metered tokens but the project totals zero "
                f"— the llm span is missing",
            )
        )
    if expected_cases is not None and facts.case_traces != expected_cases:
        found.append(
            Finding(
                facts.name,
                "journal mismatch",
                f"Opik has {facts.case_traces} case traces, journals describe {expected_cases}",
            )
        )
    return found


def render(
    all_facts: list[ProjectFacts],
    findings: list[Finding],
    unversioned: dict[str, int] | None = None,
) -> str:
    lines = [
        "",
        "=" * 96,
        "OPIK INGESTION CHECK  (read back from the live backend, not from our writer)",
        "=" * 96,
        f"{'project':<20}{'traces':>8}{'cases':>8}{'stray':>8}{'unstampd':>9}{'w/cost':>8}"
        f"{'cost $':>10}{'tokens':>14}{'tok/case':>10}{'errors':>8}",
    ]
    unversioned = unversioned or {}
    for facts in all_facts:
        lines.append(
            f"{facts.name[:19]:<20}{facts.traces:>8}{facts.case_traces:>8}"
            f"{facts.non_case_traces:>8}{unversioned.get(facts.name, 0):>9}"
            f"{facts.traces_with_cost:>8}"
            f"{facts.total_cost_usd:>10.3f}{facts.total_tokens:>14,}"
            f"{facts.tokens_per_trace:>10,.0f}{facts.errors:>8}"
        )
    lines.append("-" * 96)
    total_unstamped = sum(unversioned.get(f.name, 0) for f in all_facts)
    lines.append(
        f"{'TOTAL':<20}{sum(f.traces for f in all_facts):>8}"
        f"{sum(f.case_traces for f in all_facts):>8}"
        f"{sum(f.non_case_traces for f in all_facts):>8}"
        f"{total_unstamped:>9}"
        f"{sum(f.traces_with_cost for f in all_facts):>8}"
        f"{sum(f.total_cost_usd for f in all_facts):>10.3f}"
        f"{sum(f.total_tokens for f in all_facts):>14,}"
    )
    if total_unstamped:
        lines.append(
            f"\n  unstampd = {total_unstamped} traces from runs recorded before app-version "
            f"stamping existed.\n  Their journals carry no version, so none can be invented. "
            f"Counted apart rather than\n  accepted silently, the same way core/flaky.py pools "
            f"unstamped runs — they will\n  disappear as those suites are re-run."
        )
    if findings:
        lines += ["", f"FAILED — {len(findings)} finding(s); these numbers must not be published:"]
        lines += [str(f) for f in findings]
    else:
        lines += ["", "PASSED — every project is internally plausible and matches the journals."]
    return "\n".join(lines + [""])
