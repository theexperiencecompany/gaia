#!/usr/bin/env python3
"""Read production as an anonymous visitor after a backend deploy and decide whether it holds.

The targets are prod-smoke-targets.toml. Each is retried; a rollback-gated target wrong on
every attempt fails the deploy (verdict fail), anything that recovers or only an
alert-gated target breaks warns (verdict warn). A burst of the reads a web build starts with
checks the anonymous rate limit. No target reachable at all is the runner's problem, not the
release's: verdict error. The verdict and a one-line summary go to GITHUB_OUTPUT; a crash
writes none, so only verdict=fail is ever a rollback cause.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import http.client
import json
import os
from pathlib import Path
import sys
import time
import tomllib
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGETS_FILE = Path(__file__).with_name("prod-smoke-targets.toml")
LIMITS_FILE = REPO_ROOT / "apps/api/app/constants/request_limits.py"
ANONYMOUS_CEILING_NAME = "ANONYMOUS_VIEWER_PER_MINUTE"

USER_AGENT = "gaia-deploy-smoke/1.0 (+https://github.com/theexperiencecompany/gaia)"
#: Tries per target; with RETRY_DELAY_SECONDS between them a target gets about a minute.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 20.0
REQUEST_TIMEOUT_SECONDS = 15.0
#: A Retry-After past this is a limit a deploy cannot wait out (the ceilings are per minute).
MAX_RETRY_AFTER_SECONDS = 60
#: Slower than this but correct warns; measured 2026-11-24: API reads 0.5-0.6 s, pages 0.8-3.2 s.
API_LATENCY_BUDGET_SECONDS = 2.0
WEB_LATENCY_BUDGET_SECONDS = 6.0
#: The burst is this share of the anonymous ceiling: 120/min gives 30 reads, a quarter of it.
BURST_SHARE = 4
BODY_HEAD_BYTES = 200
NEXT_ERROR_MARKER = b"__next_error__"
TOO_MANY_REQUESTS = 429
OK = 200


class Gate(StrEnum):
    """What a target failing on every attempt does to the deploy."""

    ROLLBACK = "rollback"
    ALERT = "alert"


class Base(StrEnum):
    """Which public origin a target's path is read from."""

    API = "api"
    WEB = "web"

    @property
    def latency_budget(self) -> float:
        """Seconds a correct answer may take before it warns."""
        return API_LATENCY_BUDGET_SECONDS if self is Base.API else WEB_LATENCY_BUDGET_SECONDS


class Verdict(StrEnum):
    """The smoke's decision, written to GITHUB_OUTPUT as verdict=."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"


VERDICT_MEANING = {
    Verdict.PASS: "production answers an anonymous visitor as expected",
    Verdict.WARN: "production holds; the warnings above go to the deploy alert",
    Verdict.FAIL: "production fails an anonymous visitor: a rollback cause",
    Verdict.ERROR: "the smoke could not reach production: not a rollback cause",
}


@dataclass(frozen=True)
class Target:
    """One public read: where it is, what proves it is the real thing, and what its failure does."""

    name: str
    base: Base
    path: str
    gate: Gate
    burst: bool = False
    json_equals: dict[str, object] = field(default_factory=dict)
    json_keys: tuple[str, ...] = ()
    json_nonempty: str | None = None
    html: str | None = None
    slugs_from: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, object]) -> Target:
        """Build a target from one line of the targets file; an unknown key is a typo, so it raises."""
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"target {raw.get('name')!r}: unknown keys {sorted(unknown)}")
        equals = raw.get("json_equals", {})
        keys = raw.get("json_keys", [])
        if not isinstance(equals, dict) or not isinstance(keys, list):
            raise ValueError(
                f"target {raw.get('name')!r}: json_equals is a table, json_keys a list"
            )
        return cls(
            name=str(raw["name"]),
            base=Base(str(raw["base"])),
            path=str(raw["path"]),
            gate=Gate(str(raw["gate"])),
            burst=raw.get("burst") is True,
            json_equals={str(key): value for key, value in equals.items()},
            json_keys=tuple(str(key) for key in keys),
            json_nonempty=_optional_str(raw.get("json_nonempty")),
            html=_optional_str(raw.get("html")),
            slugs_from=_optional_str(raw.get("slugs_from")),
        )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


@dataclass
class Reply:
    """One HTTP exchange: the status (None when nothing answered), headers, body and time taken."""

    status: int | None
    body: bytes
    headers: dict[str, str]
    elapsed: float
    error: str | None = None

    def head(self) -> str:
        """Return the body's first bytes on one line, for a failure message."""
        text = self.body[:BODY_HEAD_BYTES].decode("utf-8", "replace")
        return " ".join(text.split())

    def retry_after(self) -> int | None:
        """Return the Retry-After a 429 named, when it is a wait a deploy can sit out."""
        value = self.headers.get("retry-after", "")
        if not value.isdigit() or int(value) > MAX_RETRY_AFTER_SECONDS:
            return None
        return int(value)

    def limit_text(self) -> str:
        """Return the limit a 429's envelope names (e.g. "120 per 1 minute"), else its first bytes."""
        try:
            message = json.loads(self.body).get("message")
        except (ValueError, AttributeError):
            message = None
        return str(message) if message else self.head()


@dataclass
class Outcome:
    """A target's attempts and the problem each one had (None for a pass)."""

    target: Target
    url: str
    replies: list[Reply] = field(default_factory=list)
    problems: list[str | None] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.problems) and self.problems[-1] is None

    @property
    def unreachable(self) -> bool:
        return bool(self.replies) and all(reply.status is None for reply in self.replies)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, timeout: float) -> Reply:
    """GET url once with no redirect followed; a transport failure is a Reply with no status."""
    request = urllib.request.Request(  # noqa: S310 - Origins admits only http(s) origins
        url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
    )
    start = time.monotonic()
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            body = response.read()
            status, headers = response.status, response.headers
    except urllib.error.HTTPError as exc:
        body, status, headers = exc.read(), exc.code, exc.headers
    except (OSError, http.client.HTTPException) as exc:
        reason = getattr(exc, "reason", exc)
        return Reply(
            None, b"", {}, time.monotonic() - start, error=f"{type(exc).__name__}: {reason}"
        )
    lowered = {key.lower(): value for key, value in headers.items()}
    return Reply(status, body, lowered, time.monotonic() - start)


def _json_problem(target: Target, body: bytes) -> str | None:
    try:
        document = json.loads(body)
    except ValueError:
        return "body is not JSON"
    if target.json_nonempty == ".":
        return None if isinstance(document, list) and document else "expected a non-empty JSON list"
    if not isinstance(document, dict):
        return "expected a JSON object"
    missing = [key for key in target.json_keys if key not in document]
    if missing:
        return f"JSON lacks {', '.join(missing)}"
    for key, want in target.json_equals.items():
        if document.get(key) != want:
            return f"JSON {key}={document.get(key)!r}, expected {want!r}"
    if target.json_nonempty and not document.get(target.json_nonempty):
        return f"JSON {target.json_nonempty} is empty"
    return None


def content_problem(target: Target, reply: Reply) -> str | None:
    """Why a 200 is not the real thing (an error page, the wrong shape), or None."""
    if target.html is not None:
        if NEXT_ERROR_MARKER in reply.body:
            return "rendered the Next error page"
        if target.html.encode() not in reply.body:
            return f"page lacks {target.html!r}"
        return None
    return _json_problem(target, reply.body)


def problem_of(target: Target, reply: Reply) -> str | None:
    """Classify one reply: None when it is the expected page or read."""
    if reply.status is None:
        return f"no answer ({reply.error})"
    if reply.status == TOO_MANY_REQUESTS:
        return f"429 rate limited ({reply.limit_text()})"
    if reply.status != OK:
        location = reply.headers.get("location")
        return f"{reply.status}" + (f" -> {location}" if location else "")
    return content_problem(target, reply)


@dataclass(frozen=True)
class Pacing:
    """How long the smoke waits; the defaults are the constants, the flags exist for tests."""

    attempts: int = ATTEMPTS
    retry_delay: float = RETRY_DELAY_SECONDS
    timeout: float = REQUEST_TIMEOUT_SECONDS


def check_target(target: Target, url: str, pacing: Pacing) -> Outcome:
    """Read url until it passes or the attempts run out; a 429 waits its Retry-After instead."""
    outcome = Outcome(target, url)
    for attempt in range(pacing.attempts):
        reply = fetch(url, pacing.timeout)
        problem = problem_of(target, reply)
        outcome.replies.append(reply)
        outcome.problems.append(problem)
        if problem is None or attempt == pacing.attempts - 1:
            break
        wait = reply.retry_after() if reply.status == TOO_MANY_REQUESTS else None
        time.sleep(max(pacing.retry_delay, float(wait or 0)))
    return outcome


def first_slug(outcome: Outcome, key: str) -> str | None:
    """Return the slug of the first item of the list at key in the target's passing reply."""
    if not outcome.passed:
        return None
    document = json.loads(outcome.replies[-1].body)
    items = document.get(key) if isinstance(document, dict) else None
    first = items[0] if isinstance(items, list) and items else None
    slug = first.get("slug") if isinstance(first, dict) else None
    return str(slug) if slug else None


def anonymous_ceiling(limits_file: Path) -> int:
    """Read ANONYMOUS_VIEWER_PER_MINUTE from the API's constants without importing the app."""
    tree = ast.parse(limits_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            names = [
                t.id
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(t, ast.Name)
            ]
            if ANONYMOUS_CEILING_NAME in names:
                return int(ast.literal_eval(node.value))
    raise ValueError(f"{ANONYMOUS_CEILING_NAME} is not assigned in {limits_file}")


@dataclass
class BurstPass:
    """One run of the burst: how many reads answered before a 429, and what else went wrong."""

    sent: int = 0
    refused: Reply | None = None
    errors: list[str] = field(default_factory=list)


def burst_pass(targets: Sequence[tuple[Target, str]], size: int, timeout: float) -> BurstPass:
    """Send size reads one after another, cycling the targets; stop at the first 429."""
    result = BurstPass()
    for index in range(size):
        target, url = targets[index % len(targets)]
        reply = fetch(url, timeout)
        result.sent += 1
        if reply.status == TOO_MANY_REQUESTS:
            result.refused = reply
            return result
        problem = problem_of(target, reply)
        if problem is not None:
            result.errors.append(f"{target.name}: {problem}")
    return result


@dataclass
class Report:
    """What the smoke found, already split into what fails the deploy and what only warns."""

    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def judge_burst(
    report: Report, targets: Sequence[tuple[Target, str]], size: int, pacing: Pacing
) -> None:
    """Burst once; on a 429 wait the window out and burst again, which must then pass."""
    first = burst_pass(targets, size, pacing.timeout)
    report.warnings += [f"burst: {error}" for error in first.errors]
    if first.refused is None:
        report.lines.append(f"burst: {first.sent} anonymous reads in a row, none refused")
        return
    refused = first.refused
    named = refused.retry_after()
    wait = MAX_RETRY_AFTER_SECONDS if named is None else named
    report.lines.append(
        f"burst: 429 after {first.sent - 1} reads ({refused.limit_text()}); waiting {wait}s for a fresh window"
    )
    time.sleep(wait + 1)
    second = burst_pass(targets, size, pacing.timeout)
    report.warnings += [f"burst: {error}" for error in second.errors]
    if second.refused is None:
        report.warnings.append(
            f"burst: this address was already rate limited ({refused.limit_text()}); "
            f"a fresh window took all {size} reads"
        )
        return
    report.failures.append(
        f"burst: 429 after {second.sent - 1} anonymous reads in a fresh window, under the {size} a web "
        f"build's first seconds make (limit: {second.refused.limit_text() if second.refused else '?'}, "
        f"{targets[(second.sent - 1) % len(targets)][1]})"
    )


def judge_target(report: Report, outcome: Outcome) -> None:
    """File a target's attempts under failures, warnings or the plain log."""
    target, url = outcome.target, outcome.url
    tries = len(outcome.problems)
    if outcome.passed:
        last = outcome.replies[-1]
        report.lines.append(
            f"{target.name}: {last.status} in {last.elapsed:.2f}s ({url}){_cache_note(last)}"
        )
        if tries > 1:
            report.warnings.append(
                f"{target.name}: passed on attempt {tries} after {outcome.problems[0]} ({url})"
            )
        budget = target.base.latency_budget
        if last.elapsed > budget:
            report.warnings.append(
                f"{target.name}: {last.elapsed:.1f}s, over the {budget:.0f}s budget ({url})"
            )
        return
    last = outcome.replies[-1]
    message = (
        f"{target.name}: {outcome.problems[-1]} on {tries}/{tries} attempts ({url}); "
        f"first bytes: {last.head() or '<empty>'}"
    )
    (report.failures if target.gate is Gate.ROLLBACK else report.warnings).append(message)


def _cache_note(reply: Reply) -> str:
    cache = reply.headers.get("x-opennext-cache")
    return f" [x-opennext-cache: {cache}]" if cache else ""


@dataclass(frozen=True)
class Origins:
    """Where each base of a target path points."""

    api: str
    web: str

    def __post_init__(self) -> None:
        for origin in (self.api, self.web):
            if not origin.startswith(("https://", "http://")):
                raise ValueError(f"origin {origin!r} is not http(s)")

    def url(self, target: Target, slug: str) -> str:
        base = self.api if target.base is Base.API else self.web
        path = target.path.replace("{slug}", slug).replace("{url_slug}", slug.replace("_", "-"))
        return base.rstrip("/") + path


def run(
    targets: Sequence[Target], origins: Origins, burst_size: int, pacing: Pacing
) -> tuple[Verdict, Report]:
    """Check every target in order, then burst; return the verdict and what led to it."""
    report = Report()
    outcomes: list[Outcome] = []
    slug: str | None = None
    for target in targets:
        if "{" in target.path and slug is None:
            message = f"{target.name}: no slug to read (every slugs_from list failed or was empty)"
            (report.failures if target.gate is Gate.ROLLBACK else report.warnings).append(message)
            continue
        outcome = check_target(target, origins.url(target, slug or ""), pacing)
        outcomes.append(outcome)
        judge_target(report, outcome)
        if target.slugs_from and slug is None:
            slug = first_slug(outcome, target.slugs_from)
    if outcomes and all(outcome.unreachable for outcome in outcomes):
        report.failures.append("nothing answered: production is unreachable from this runner")
        return Verdict.ERROR, report
    burst = [(t, origins.url(t, slug or "")) for t in targets if t.burst]
    if burst:
        judge_burst(report, burst, burst_size, pacing)
    if report.failures:
        return Verdict.FAIL, report
    return (Verdict.WARN if report.warnings else Verdict.PASS), report


def load_targets(path: Path) -> list[Target]:
    """Parse the targets file; raises on a malformed or unknown entry rather than skipping it."""
    raw = tomllib.loads(path.read_text())["targets"]
    return [Target.parse(entry) for entry in raw]


def publish(verdict: Verdict, report: Report) -> None:
    """Print the log and annotations, and write verdict= and summary= for the workflow."""
    for line in report.lines:
        print(f"smoke: {line}")
    for warning in report.warnings:
        print(f"::warning::smoke: {warning}", file=sys.stderr)
    for failure in report.failures:
        print(f"::error::smoke: {failure}", file=sys.stderr)
    summary = (report.failures or report.warnings or ["every target answered as expected"])[0]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a") as handle:
            handle.write(f"verdict={verdict}\nsummary={' '.join(summary.split())}\n")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a") as handle:
            handle.write(f"### Production smoke: {verdict}\n\n")
            for prefix, items in (
                ("FAIL", report.failures),
                ("WARN", report.warnings),
                ("ok", report.lines),
            ):
                handle.writelines(f"- {prefix} {item}\n" for item in items)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the smoke; exit 0 on pass or warn, 1 otherwise (verdict= says which)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="the API's public origin")
    parser.add_argument("--web", required=True, help="the web app's public origin")
    parser.add_argument("--targets", type=Path, default=TARGETS_FILE)
    parser.add_argument("--limits-file", type=Path, default=LIMITS_FILE)
    parser.add_argument("--retry-delay", type=float, default=RETRY_DELAY_SECONDS)
    parser.add_argument("--timeout", type=float, default=REQUEST_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    burst_size = anonymous_ceiling(args.limits_file) // BURST_SHARE
    pacing = Pacing(retry_delay=args.retry_delay, timeout=args.timeout)
    verdict, report = run(
        load_targets(args.targets), Origins(args.api, args.web), burst_size, pacing
    )
    publish(verdict, report)
    print(f"smoke: verdict {verdict} — {VERDICT_MEANING[verdict]}")
    return 0 if verdict in (Verdict.PASS, Verdict.WARN) else 1


if __name__ == "__main__":
    sys.exit(main())
