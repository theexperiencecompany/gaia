"""Tests for the wide-event output contract checker.

Run from the repo root:

    uv run --no-project --with pytest pytest tools/logcheck -q

An unvalidated validator is worthless: a checker whose rule silently stops
firing reports "OK" over exactly the output it exists to reject, and every
caller that trusts it inherits the blind spot. So the suite is symmetric —

* ``fixtures/poisoned-*.ndjson`` must produce **exactly** the expected
  ``(line, rule)`` list, in order. Not "at least these": an exact match is what
  makes a check that stopped firing fail here, and it is also what stops a
  new false positive from sneaking in.
* ``fixtures/good-*.ndjson`` are real captures from a live local stack (HTTP +
  ARQ worker, and the bot surface). They must pass clean, which is what keeps
  a tightened rule from being merged as a false alarm.

The two size-related invariants are built in the test rather than committed:
a 200KB fixture would be a 200KB file in the repo to assert one integer.

Every test is mutation-verified: inverting the invariant it covers makes it fail.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import logcheck
from logcheck import MAX_LINE_BYTES, Violation, check_lines
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
# libs/shared/py/logging.py::MAX_JSON_LINE_BYTES — the cap the sink enforces,
# set below Loki's max_line_size. Spelled out here rather than imported so a
# change to the checker's constant fails a test instead of moving the fixture.
SINK_CAP_BYTES = 200_000

# Every defect the poisoned HTTP capture carries, in emission order. One line
# per defect, except where a single broken event genuinely breaks several
# invariants at once (lines 15-17).
EXPECTED_HTTP_VIOLATIONS = [
    (1, "ndjson-framing"),  # torn write — unterminated JSON object
    (2, "ndjson-framing"),  # event glued behind a progress bar on the same fd
    (3, "stream-purity"),  # bare non-JSON noise in a contractually pure stream
    (4, "json-strictness"),  # bare NaN: Python round-trips it, Loki drops the line
    (5, "core-keys"),
    (6, "level-vocabulary"),
    (7, "timestamp"),
    (8, "message-type"),
    (9, "reserved-collision"),  # ctx_ — Python app code fought a core key
    (10, "reserved-collision"),  # field_ — the TypeScript equivalent
    (11, "entry-array-type"),
    (12, "entry-shape"),
    (13, "access-log-duplication"),
    (14, "secret-leak"),
    (15, "boundary-identity"),
    (15, "duration"),
    (15, "failure-recorded"),  # a 500 that never records why
    (15, "level-consistency"),
    (16, "truncation-integrity"),  # truncation cost the event its identity
    (16, "boundary-identity"),
    (16, "duration"),
    (17, "worker-shape"),  # no task
    (17, "worker-shape"),  # outcome outside the vocabulary
    (18, "failure-recorded"),  # failed task with an empty errors[]
    (0, "one-event-per-request"),  # two canonical events for one trace_id
]

EXPECTED_BOT_VIOLATIONS = [
    (1, "bot-trace-id"),  # app code overwrote the minted boundary id
    (2, "failure-recorded"),
    (3, "level-consistency"),
    (4, "bot-service-identity"),  # not a Promtail-labelled bot container
    (5, "bot-shape"),
]


def _pairs(violations: list[Violation]) -> list[tuple[int, str]]:
    return [(v.line_no, v.rule) for v in violations]


def _read(name: str) -> list[str]:
    return (FIXTURES / name).read_text(encoding="utf-8").splitlines()


def test_poisoned_http_capture_produces_exactly_the_expected_violations() -> None:
    violations = check_lines(
        _read("poisoned-http-capture.ndjson"),
        surface="http",
        unique_traces=True,
        strict_stream=True,
    )
    assert _pairs(violations) == EXPECTED_HTTP_VIOLATIONS


def test_poisoned_bot_capture_produces_exactly_the_expected_violations() -> None:
    violations = check_lines(
        _read("poisoned-bot-capture.ndjson"), surface="bot", strict_stream=True
    )
    assert _pairs(violations) == EXPECTED_BOT_VIOLATIONS


def test_a_real_http_and_worker_capture_passes_clean() -> None:
    violations = check_lines(
        _read("good-http-capture.ndjson"),
        surface="http",
        unique_traces=True,
        strict_stream=True,
    )
    assert violations == []


def test_a_real_bot_capture_passes_clean() -> None:
    violations = check_lines(
        _read("good-bot-capture.ndjson"), surface="bot", unique_traces=True, strict_stream=True
    )
    assert violations == []


def _boundary_event(**overrides: object) -> dict[str, object]:
    event = {
        "time": "2026-08-02T11:00:00.000Z",
        "level": "INFO",
        "env": "development",
        "service": "gaia-backend",
        "commit": "local",
        "logger": "REQUEST",
        "message": "http_request",
        "module": "m",
        "line": 1,
        "worker": "main",
        "trace_id": "5555555555555555",
        "duration_ms": 3.0,
        "final_level": "INFO",
        "method": "GET",
        "path": "/api/v1/todos",
        "status_code": 200,
    }
    event.update(overrides)
    return event


def test_the_checkers_byte_cap_is_the_one_the_sink_enforces() -> None:
    # Drift here is invisible: the checker keeps passing lines the sink already
    # truncated, or flags lines it never would have. Read the sink's own
    # declaration rather than trusting the copy.
    source = (REPO_ROOT / "libs/shared/py/logging.py").read_text(encoding="utf-8")
    declared = re.search(r"^MAX_JSON_LINE_BYTES = ([\d_]+)", source, re.MULTILINE)
    assert declared, "MAX_JSON_LINE_BYTES no longer declared in libs/shared/py/logging.py"
    assert int(declared.group(1).replace("_", "")) == SINK_CAP_BYTES == MAX_LINE_BYTES


def test_a_line_over_the_byte_cap_is_a_violation_and_a_line_under_it_is_not() -> None:
    # Loki rejects the line outright, so an over-cap line is a dropped event.
    # Sized from the contract, not from the checker's own constant — otherwise
    # raising the constant would move the fixture with it and this could never fail.
    over = json.dumps(_boundary_event(payload="x" * SINK_CAP_BYTES))
    assert _pairs(check_lines([over])) == [(1, "line-size")]

    under = json.dumps(_boundary_event(payload="x" * 1000))
    assert check_lines([under]) == []


def test_truncation_may_shed_payload_but_never_the_events_identity() -> None:
    # Shedding bulk is the sink working as designed...
    shed = _boundary_event(
        line_truncated=True, original_size_bytes=300_123, dropped_fields=["payload"]
    )
    assert check_lines([json.dumps(shed)]) == []

    # ...shedding what makes it a boundary event is a caller deleting its own
    # request from the record by inflating the line.
    gutted = _boundary_event(line_truncated=True, original_size_bytes=300_123, trace_id="")
    assert ("truncation-integrity", 1) in [
        (v.rule, v.line_no) for v in check_lines([json.dumps(gutted)])
    ]


def test_noise_beside_the_events_is_tolerated_unless_the_stream_must_be_pure() -> None:
    lines = ["[transformers] PyTorch was not found.", json.dumps(_boundary_event())]
    assert check_lines(lines) == []
    assert _pairs(check_lines(lines, strict_stream=True)) == [(1, "stream-purity")]


def test_the_cli_exits_1_on_a_poisoned_capture_and_0_on_a_clean_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["logcheck", str(FIXTURES / "poisoned-http-capture.ndjson"), "--strict-stream"]
    )
    assert logcheck.main() == 1

    monkeypatch.setattr(
        sys, "argv", ["logcheck", str(FIXTURES / "good-http-capture.ndjson"), "--strict-stream"]
    )
    assert logcheck.main() == 0
