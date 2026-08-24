"""The wide-event output contract — what a log line must be, checked black-box.

`tools/evlog_map` reads the *source* and asks whether a handler would be able to
explain a failure. This asks the opposite, and the harder, question: given the
NDJSON the running system actually emitted, is it usable? It parses captured
output and knows nothing about the code that produced it — no imports, no
fixtures, no cooperation from the app. If a line is unparseable, missing its
identity, carrying a secret, or describing a 500 with no recorded reason, it
fails here regardless of how well-instrumented the source looked.

**Use it whenever you have emitted logs in hand**: after driving the stack with
the ``driving-gaia`` skill, after a bot or worker run, on a captured
``structured-<date>.json``, or on anything piped out of a container. It is the
shared contract every surface is measured against — HTTP, ARQ worker, LiveKit
voice, and the TypeScript bots — so a pass means the same thing on all four and
no caller has to invent its own assertions.

    python3 tools/logcheck/logcheck.py <file-or-'-'> [--surface http|worker|voice|bot]
    python3 tools/logcheck/logcheck.py capture.ndjson --strict-stream --unique-traces
    from logcheck import check_lines, Violation

What it enforces: NDJSON framing (one JSON object per line, nothing glued in
front of it), the core keys every line carries, the level vocabulary, ISO-8601
timestamps, ``ctx_``/``field_`` collisions where app code fought a core field
and lost, secret patterns, the 200KB line cap, truncation integrity (shedding
payload is fine, shedding the event's identity is not), the rule that a failing
unit of work must record *why* it failed, agreement between ``errors[]`` and
``final_level``, one canonical event per trace, the worker and bot event shapes,
and — with ``--strict-stream`` — that a contractually pure NDJSON stream carries
nothing but NDJSON.

Exit 1 if any invariant is violated. Add invariants here, never in a caller.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

# The envelope every emitted line carries on BOTH runtimes — the shared half of
# libs/shared/py/logging.py::_CORE_KEYS and ENVELOPE_KEYS in
# libs/shared/ts/src/bots/utils/logger.ts. env/service/commit used to be
# boundary-only on the Python side; the sink stamps them on every line now, so
# the two surfaces share one required set.
SHARED_CORE_KEYS = ("time", "level", "env", "service", "commit", "logger", "message")
# `module`/`line`/`worker` are loguru-record provenance with no TypeScript
# equivalent, declared Python-only in
# scripts/ci/wide-event-conformance/contract.json. Requiring them of the bots
# would restate a deliberate asymmetry as a violation on every line.
CORE_KEYS = (*SHARED_CORE_KEYS, "module", "line", "worker")
BOT_CORE_KEYS = SHARED_CORE_KEYS
# AUDIT (28) and SECURITY (38) are GAIA's custom loguru levels — both surfaces
# emit AUDIT (`log.audit` / `wideLog.audit`), so a level checker that rejects it
# rejects every audit-trail line.
LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "AUDIT",
    "WARNING",
    "ERROR",
    "SECURITY",
    "CRITICAL",
}
# libs/shared/py/logging.py::MAX_JSON_LINE_BYTES
MAX_LINE_BYTES = 200_000
# `bot_event` is libs/shared/ts/src/bots/utils/wide-events.ts::WIDE_EVENT_MESSAGE.
BOUNDARY_MESSAGES = {"http_request", "worker_task", "background_task", "bot_event"}
# A colliding context key is re-emitted under one prefix rather than corrupting a
# core field — `ctx_`, on both runtimes (_COLLIDING_KEY_PREFIX in
# libs/shared/py/logging.py, COLLIDING_KEY_PREFIX in
# libs/shared/ts/src/bots/utils/logger.ts). `field_` is the TypeScript spelling
# from before the two converged; it is still matched so an unmigrated build's
# output is not read as clean.
COLLISION_PREFIXES = ("ctx_", "field_")
# The accumulated entry lists a boundary event carries (log.error/warning/audit).
ENTRY_LIST_KEYS = ("errors", "warnings", "audit")
# Every exit path a unit of work can report — wide_events.py::_wide_event_boundary
# and the bots' withWideEvent set exactly one of these.
OUTCOMES = frozenset({"success", "failed", "cancelled"})
# The Promtail label a bot container is allowed to claim.
BOT_SERVICE = re.compile(r"(discord|slack|telegram|whatsapp)-bot|gaia-bots")

# An unstructured HTTP access line ("1.2.3.4:5678 - "GET /x HTTP/1.1" 200").
# The canonical wide event is the one record per request; a second, trace-less
# access line duplicates it, cannot be joined to it, and doubles log volume.
ACCESS_LOG_MESSAGE = re.compile(r'^\S+:\d+ - "[A-Z]+ .* HTTP/\d')
# A structured event object appearing somewhere other than the start of a line.
# Means another writer on the same fd (a progress bar, a bare print, a library
# that forgot its newline) landed in front of it: that event is now unparseable
# and is lost to every downstream query.
EMBEDDED_EVENT = re.compile(r'\{\s*"(?:time|level|logger|message)"\s*:')

# Values that must never reach a log line. Matched against the serialized event.
SECRET_PATTERNS = (
    re.compile(r"\bsk_live_[A-Za-z0-9]+"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
)


@dataclass
class Violation:
    """One invariant broken on one line."""

    line_no: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"  line {self.line_no}: [{self.rule}] {self.detail}"


def _reject_constant(name: str) -> Any:  # noqa: ANN401 -- framework contract
    raise ValueError(f"bare {name} is not valid JSON — strict parsers drop the line")


def _iso(value: Any) -> bool:  # noqa: ANN401 -- framework contract
    try:
        datetime.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _check_framing(i: int, raw: str, strict_stream: bool) -> tuple[Any, list[Violation]]:
    """Parse one raw line. Returns ``(event, violations)``; event is None if unusable.

    A structured sink must emit exactly one JSON object per line. When that
    fails on a line that looks like log output, something (a raw newline in a
    field, a torn write, an interleaved sink) broke NDJSON framing — the
    failure mode that silently destroys every downstream query.
    """
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        if raw.lstrip().startswith("{"):
            return None, [Violation(i, "ndjson-framing", f"unparseable JSON object: {exc}")]
        if EMBEDDED_EVENT.search(raw):
            # A real event sits inside this line but not at its start: another
            # writer on the same descriptor emitted without a trailing newline
            # and the event got glued behind it. The event still "exists" but
            # no `| json` will ever parse it, so it is lost exactly like a
            # dropped line — and skipping it as noise is how that loss stays
            # invisible.
            return None, [
                Violation(
                    i,
                    "ndjson-framing",
                    f"event object glued behind non-JSON output: {raw[:60]!r}…",
                )
            ]
        if strict_stream:
            # For a stream that is contractually pure NDJSON (LOG_FORMAT=json
            # stdout, structured-<date>.json) anything else on the descriptor is
            # a parse failure for the shipper, not harmless noise.
            return None, [
                Violation(i, "stream-purity", f"non-JSON line in NDJSON stream: {raw[:80]!r}")
            ]
        return None, []
    if not isinstance(event, dict):
        return None, [
            Violation(i, "ndjson-framing", f"top level is {type(event).__name__}, not object")
        ]
    return event, []


def _check_envelope(i: int, raw: str, event: dict[str, Any], surface: str) -> list[Violation]:
    """The keys, types and limits every emitted line owes, boundary or not."""
    out: list[Violation] = []

    # Python's json module both emits and accepts bare NaN/Infinity, so a line
    # carrying them round-trips here while every strict parser in the pipeline
    # (Loki's Go `| json`, jq, browsers) rejects it — the line is dropped
    # downstream and nothing in Python ever notices. Only a strict re-parse can
    # see it.
    try:
        json.loads(raw, parse_constant=_reject_constant)
    except ValueError as exc:
        out.append(Violation(i, "json-strictness", str(exc)))

    nbytes = len(raw.encode("utf-8"))
    if nbytes > MAX_LINE_BYTES:
        out.append(Violation(i, "line-size", f"{nbytes} bytes exceeds cap {MAX_LINE_BYTES}"))

    for key in BOT_CORE_KEYS if surface == "bot" else CORE_KEYS:
        if key not in event:
            out.append(Violation(i, "core-keys", f"missing {key!r}"))

    level = event.get("level")
    if level not in LEVELS:
        out.append(Violation(i, "level-vocabulary", f"{level!r} not in {sorted(LEVELS)}"))
    if "time" in event and not _iso(event["time"]):
        out.append(Violation(i, "timestamp", f"not ISO-8601: {event['time']!r}"))
    if not isinstance(event.get("message"), str):
        out.append(
            Violation(i, "message-type", f"message is {type(event.get('message')).__name__}")
        )
    return out


def _check_reserved_and_entries(i: int, event: dict[str, Any]) -> list[Violation]:
    """Collisions with core keys, and the shape of the accumulated entry lists."""
    out = [
        Violation(i, "reserved-collision", f"{key!r} — app code set a core key")
        for key in event
        if key.startswith(COLLISION_PREFIXES)
    ]

    # Fields whose *type* a dashboard depends on. A string duration cannot be
    # unwrapped by LogQL and a non-list errors[] breaks every failure panel —
    # both are reachable from app code on both surfaces (`log.set(errors=...)`
    # / `wideLog.set({ errors: ... })`), and both fail silently.
    for key in ENTRY_LIST_KEYS:
        if key in event and not isinstance(event[key], list):
            out.append(
                Violation(i, "entry-array-type", f"{key} is {type(event[key]).__name__}, not list")
            )
    for key in ENTRY_LIST_KEYS:
        entries = event.get(key)
        if not isinstance(entries, list):
            continue
        out.extend(
            Violation(i, "entry-shape", f"entry without a str 'msg': {entry!r:.60}")
            for entry in entries
            if not isinstance(entry, dict) or not isinstance(entry.get("msg"), str)
        )
    return out


def _check_leaks(i: int, event: dict[str, Any]) -> list[Violation]:
    """Content that must never reach a line: duplicate access logs, secrets."""
    out: list[Violation] = []
    # An unstructured access line is a second record for a request that the
    # canonical event already covers, carries no trace_id to join on, and
    # (unlike the wide event) embeds the raw request target — so it leaks
    # whatever the caller put in the URL and doubles ingest for nothing.
    if ACCESS_LOG_MESSAGE.match(str(event.get("message", ""))):
        out.append(
            Violation(
                i,
                "access-log-duplication",
                f"unstructured HTTP access line beside the canonical event: "
                f"{str(event.get('message'))[:60]!r}",
            )
        )

    blob = json.dumps(event, default=str)
    for pat in SECRET_PATTERNS:
        found = pat.search(blob)
        if found:
            out.append(Violation(i, "secret-leak", f"matched {pat.pattern}: {found.group()[:24]}…"))
    return out


def _check_boundary_identity(i: int, event: dict[str, Any]) -> list[Violation]:
    """What makes a boundary event a boundary event, truncated or not."""
    out: list[Violation] = []
    # Oversized lines are replaced by a minimal entry. Shedding bulk is
    # legitimate; shedding the event's identity and outcome is not — a caller
    # who can inflate the line (an over-long header, a big error payload) would
    # otherwise be able to delete its own request from the record while still
    # getting a 200. Truncation must cost payload, never the fields that make
    # the boundary event a boundary event.
    if event.get("line_truncated"):
        lost = [k for k in ("service", "env", "trace_id", "duration_ms") if not event.get(k)]
        if lost:
            out.append(
                Violation(
                    i,
                    "truncation-integrity",
                    f"truncation dropped boundary identity {lost} "
                    f"(original_size_bytes={event.get('original_size_bytes')})",
                )
            )

    out.extend(
        Violation(i, "boundary-identity", f"missing/empty {key!r}")
        for key in ("service", "env", "trace_id")
        if not event.get(key)
    )
    duration = event.get("duration_ms")
    if not isinstance(duration, (int, float)):
        out.append(Violation(i, "duration", f"duration_ms is {duration!r}"))
    return out


def _check_bot_event(i: int, event: dict[str, Any]) -> list[Violation]:
    """The bot boundary event's own shape (libs/shared/ts/src/bots)."""
    out: list[Violation] = []
    trace = event.get("trace_id")
    # withWideEvent mints the trace_id; app code that sets one of these via
    # wideLog.set() overwrites it (state.fields is spread AFTER them), which
    # silently breaks bot↔backend trace correlation.
    if not re.fullmatch(r"[0-9a-f]{16}", str(trace)):
        out.append(Violation(i, "bot-trace-id", f"trace_id not a 16-hex boundary id: {trace!r}"))
    out.extend(
        Violation(i, "bot-shape", f"missing/empty {key!r}")
        # `task` is the boundary's unit-of-work name on both runtimes (it was
        # `operation` on the bots until the shapes converged). `operation` is
        # the domain verb app code sets and is not guaranteed on every event.
        for key in ("task", "outcome", "final_level", "platform")
        if not event.get(key)
    )
    outcome = event.get("outcome")
    if outcome not in OUTCOMES:
        out.append(Violation(i, "bot-shape", f"outcome={outcome!r}"))
    # A failed unit of work with nothing in errors[] is an event that tells an
    # operator a bot broke but never why.
    if outcome == "failed" and not event.get("errors"):
        out.append(Violation(i, "failure-recorded", "outcome=failed with empty errors[]"))
    if event.get("errors") and event.get("final_level") != "ERROR":
        out.append(
            Violation(
                i,
                "level-consistency",
                f"errors[] present but final_level={event.get('final_level')!r}",
            )
        )
    # service is the Promtail label for the emitting container.
    if not re.fullmatch(BOT_SERVICE, str(service := event.get("service"))):
        out.append(Violation(i, "bot-service-identity", f"service={service!r}"))
    return out


def _check_worker_event(i: int, event: dict[str, Any]) -> list[Violation]:
    """The ARQ/background boundary event's own shape.

    ``libs/shared/py/wide_events.py::_wide_event_boundary`` sets ``task`` on
    entry and ``outcome`` on every exit path (success / cancelled / failed), so
    both are contract-guaranteed on every one of these events. They are also the
    only two fields that make the event usable: without ``task`` nobody can tell
    which unit of work it describes, and without ``outcome`` a finished job is
    indistinguishable from one still running — which is exactly how a silently
    dying background task stays invisible.
    """
    out: list[Violation] = []
    # A field the sink shed to stay under the byte cap is named in
    # dropped_fields, which is a *record* of the loss, not a silent one. Only an
    # absent-and-unaccounted-for field is a violation.
    shed = set(event.get("dropped_fields") or [])
    if not event.get("task"):
        out.append(Violation(i, "worker-shape", "missing/empty 'task'"))
    outcome = event.get("outcome")
    if outcome not in OUTCOMES:
        out.append(Violation(i, "worker-shape", f"outcome={outcome!r}"))
    # The exception path appends a "task failed" entry before setting
    # outcome=failed, so a failed boundary with nothing in errors[] means the
    # entry was lost between accumulation and emit.
    if outcome == "failed" and not (event.get("errors") or "errors" in shed):
        out.append(Violation(i, "failure-recorded", "outcome=failed with empty errors[]"))
    # log.error() bumps max_level, which becomes final_level — a disagreement
    # means one of the two paths did not run.
    if event.get("errors") and event.get("final_level") not in ("ERROR", "CRITICAL"):
        out.append(
            Violation(
                i,
                "level-consistency",
                f"errors[] present but final_level={event.get('final_level')!r}",
            )
        )
    return out


def _check_http_request(i: int, event: dict[str, Any]) -> list[Violation]:
    """The HTTP boundary event's own shape, and the rule the whole effort exists for."""
    out = [
        Violation(i, "http-shape", f"missing {key!r}")
        for key in ("path", "method", "status_code")
        if key not in event
    ]
    status = event.get("status_code")
    if not isinstance(status, int):
        return out
    # A failing request with no recorded reason is the exact defect this whole
    # effort exists to prevent.
    if status >= 500 and not event.get("errors"):
        out.append(Violation(i, "failure-recorded", f"{status} with empty errors[]"))
    if 400 <= status < 500 and not (event.get("errors") or event.get("warnings")):
        out.append(Violation(i, "failure-recorded", f"{status} with no errors[]/warnings[]"))
    if status >= 500 and event.get("final_level") != "ERROR":
        out.append(
            Violation(
                i, "level-consistency", f"{status} but final_level={event.get('final_level')!r}"
            )
        )
    return out


def _check_boundary(i: int, event: dict[str, Any], surface: str) -> list[Violation]:
    """Every invariant that applies only to the one canonical event per unit of work."""
    out = _check_boundary_identity(i, event)
    message = event.get("message")
    if surface == "bot" and message == "bot_event":
        out += _check_bot_event(i, event)
    if message in ("worker_task", "background_task"):
        out += _check_worker_event(i, event)
    if surface == "http" and message == "http_request":
        out += _check_http_request(i, event)
    return out


def check_lines(
    lines: Iterable[str],
    surface: str = "http",
    unique_traces: bool = False,
    strict_stream: bool = False,
) -> list[Violation]:
    """Validate raw NDJSON lines. `lines` are as-emitted, including non-JSON noise."""
    out: list[Violation] = []
    seen_trace_boundaries: dict[str, int] = {}

    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        event, framing = _check_framing(i, line, strict_stream)
        out += framing
        if event is None:
            continue

        out += _check_envelope(i, line, event, surface)
        out += _check_reserved_and_entries(i, event)
        out += _check_leaks(i, event)

        if event.get("message") not in BOUNDARY_MESSAGES:
            continue
        out += _check_boundary(i, event, surface)

        trace = event.get("trace_id")
        if trace and event.get("message") == "http_request":
            seen_trace_boundaries[trace] = seen_trace_boundaries.get(trace, 0) + 1

    # Only meaningful when the caller guarantees one request per trace_id. A
    # client may legitimately reuse an x-trace-id across requests, so this is
    # opt-in: harnesses that mint a unique id per request turn it on, and it
    # then catches double-emission of the canonical event.
    if unique_traces:
        out.extend(
            Violation(
                0, "one-event-per-request", f"trace_id {trace} has {count} http_request events"
            )
            for trace, count in seen_trace_boundaries.items()
            if count > 1
        )
    return out


def _resolve_input_path(raw: str) -> Path:
    """Resolve a CLI-supplied file path, rejecting traversal out of the CWD.

    Relative paths are confined to the working directory; absolute paths are
    accepted as-is. This keeps the tool from reading arbitrary files when it
    is driven by an agent with faulty arguments (CWE-22).
    """
    path = Path(raw)
    resolved = path.resolve()
    if not path.is_absolute():
        base = Path.cwd().resolve()
        if resolved != base and not resolved.is_relative_to(base):
            raise SystemExit(f"logcheck: refusing path outside the working directory: {raw}")
    return resolved


def main() -> int:
    """CLI: validate a capture, print every violation, exit 1 if there are any."""
    ap = argparse.ArgumentParser(
        prog="logcheck",
        description="Validate emitted wide-event NDJSON against the output contract.",
    )
    ap.add_argument("path", help="NDJSON file, or - for stdin")
    ap.add_argument("--surface", default="http", choices=["http", "worker", "voice", "bot"])
    ap.add_argument("--filter-trace", help="only check lines carrying this trace_id")
    ap.add_argument(
        "--unique-traces",
        action="store_true",
        help="assert one canonical event per trace_id (harness mints a unique id per request)",
    )
    ap.add_argument(
        "--strict-stream",
        action="store_true",
        help=(
            "the capture is a whole NDJSON stream (LOG_FORMAT=json stdout, "
            "structured-<date>.json), so every non-blank line must be a JSON object"
        ),
    )
    args = ap.parse_args()

    if args.path == "-":
        lines = list(sys.stdin)
    else:
        lines = (
            _resolve_input_path(args.path)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )
    if args.filter_trace:
        lines = [ln for ln in lines if args.filter_trace in ln]

    violations = check_lines(
        lines,
        args.surface,
        unique_traces=args.unique_traces,
        strict_stream=args.strict_stream,
    )
    checked = sum(1 for ln in lines if ln.strip())
    if violations:
        print(f"FAIL — {len(violations)} violation(s) across {checked} line(s):")
        for v in violations:
            print(v)
        return 1
    print(f"OK — {checked} line(s), no invariant violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
