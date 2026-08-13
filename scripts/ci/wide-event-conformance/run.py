#!/usr/bin/env python3
"""Cross-runtime wide-event conformance gate.

Runs the two emitters for real, captures the NDJSON each actually prints, and
fails when the two shapes disagree or when either breaks the shared contract in
``contract.json``.

This exists because a comment asking the next engineer to "mirror this in the
other file" is not a mechanism. The check is black-box on purpose: it never
imports either logging module, so it cannot be satisfied by a constant that
happens to match — only by output that matches.

What it asserts:

  1. Every line from both runtimes carries the shared envelope, with the right
     JSON types and the shared timestamp format.
  2. Each runtime carries the extra keys contract.json declares for it, with
     the declared types, and TypeScript does not grow stand-ins for Python's
     loguru provenance. An asymmetry that is not written down is drift, even
     when it looks like an improvement — declare it and it stops failing.
  3. A caller field colliding with an envelope key is re-emitted under the ONE
     shared collision prefix, and the real envelope value survives.
  4. Paired scenarios have identical key -> JSON-type maps, once the declared
     asymmetric keys are removed. This is the drift detector: rename a field,
     change a type, or add a field on one side only, and the pair stops
     matching.
  5. Boundary events on both surfaces carry the same boundary fields with the
     same types, and their errors[]/warnings[]/audit[] entries have identical
     key sets.

Usage:
    python3 scripts/ci/wide-event-conformance/run.py [--show-capture]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
CONTRACT_PATH = HERE / "contract.json"

# `libs` is the gaia-shared workspace member — the only package the emitter
# needs (loguru). Resolving against apps/api instead would install the whole
# backend to exercise one sink.
PYTHON_EMITTER = ["uv", "run", "--project", "libs", "python", str(HERE / "emit_python.py")]
TYPESCRIPT_EMITTER = ["pnpm", "exec", "tsx", str(HERE / "emit_typescript.ts")]

_JSON_TYPE_NAMES = {
    str: "string",
    bool: "boolean",
    int: "number",
    float: "number",
    list: "array",
    dict: "object",
    type(None): "null",
}


def json_type(value: object) -> str:
    """The JSON type name of a decoded value (bool before int, as in JSON).

    A namespace object also carries its sorted key names. Plain ``"object"`` made
    the two runtimes look identical whenever both merely HAD the namespace, so a
    runtime that dropped keys from it (the ``set`` clobbering bug) diffed clean.
    """
    if isinstance(value, dict):
        return "object{" + ",".join(sorted(str(k) for k in value)) + "}"
    return _JSON_TYPE_NAMES.get(type(value), "unknown")


class Failures:
    """Collected drift, reported all at once so one run shows every problem."""

    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, check: str, detail: str) -> None:
        self.items.append(f"[{check}] {detail}")

    def __bool__(self) -> bool:
        return bool(self.items)


def run_emitter(name: str, command: list[str], overlay: dict[str, str]) -> list[dict[str, Any]]:
    """Run one emitter under the probe environment and return what it printed.

    A non-zero exit, a crash, or a non-JSON line is a hard failure: the whole
    point is that the real stack produced this, so "it did not run" must never
    silently become "no drift found".
    """
    if shutil.which(command[0]) is None:
        raise SystemExit(
            f"conformance: cannot run the {name} emitter — {command[0]!r} is not on PATH.\n"
            f"  Python emitter needs uv (astral-sh/setup-uv), TypeScript needs pnpm + tsx."
        )
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, **overlay},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"conformance: the {name} emitter exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )

    # Both descriptors, because the runtimes split levels across them
    # differently (console.warn/error → stderr in Node) and a container log
    # driver captures both. Toolchain chatter that is not a JSON object is
    # skipped here rather than failing, since neither `uv` nor `pnpm` promises
    # a silent stderr; framing of the log stream itself is a separate concern
    # owned by the sink tests.
    events: list[dict[str, Any]] = []
    for raw in result.stdout.splitlines() + result.stderr.splitlines():
        stripped = raw.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"conformance: the {name} emitter printed an unparseable JSON line: {exc}\n"
                f"  {stripped[:200]!r}\n"
                f"  A structured sink must emit exactly one JSON object per line."
            ) from exc
        if isinstance(event, dict):
            events.append(event)
    if not events:
        raise SystemExit(f"conformance: the {name} emitter produced no lines")
    return events


def declared(section: dict[str, Any]) -> dict[str, str]:
    """A contract section's key -> type map, minus its `$comment` prose."""
    return {k: v for k, v in section.items() if not k.startswith("$")}


def check_envelope(
    runtime: str, events: list[dict[str, Any]], contract: dict[str, Any], failures: Failures
) -> None:
    """Every line carries the shared envelope plus its own declared additions.

    Three asymmetries are legal, and only because contract.json spells them out:
    Python's loguru provenance (module/line/worker), which TypeScript must NOT
    invent; the TS envelope's platform/component, which Python may carry as an
    ordinary field of the same type; and per-service `service` values.
    """
    envelope = contract["envelope"]
    shared: dict[str, Any] = envelope["shared"]
    python_only = declared(envelope["python_only"])
    ts_envelope = declared(envelope["typescript_envelope"])
    # Required-on-this-runtime vs may-appear-and-must-then-match.
    required = python_only if runtime == "python" else ts_envelope
    optional = ts_envelope if runtime == "python" else {}
    forbidden = {} if runtime == "python" else python_only

    for event in events:
        where = f"{runtime} {event.get('message')!r}"
        for key, spec in shared.items():
            if key not in event:
                failures.add("envelope", f"{where}: missing shared envelope key {key!r}")
                continue
            actual = json_type(event[key])
            if actual != spec["type"]:
                failures.add(
                    "envelope",
                    f"{where}: {key!r} is {actual}, contract says {spec['type']}",
                )
                continue
            pattern = spec.get("pattern")
            if pattern and not re.fullmatch(pattern, str(event[key])):
                failures.add(
                    "envelope",
                    f"{where}: {key}={event[key]!r} does not match {pattern}",
                )
            allowed = spec.get("enum")
            if allowed and event[key] not in allowed:
                failures.add("envelope", f"{where}: {key}={event[key]!r} not in {allowed}")

        for key, expected in required.items():
            if key not in event:
                failures.add("envelope", f"{where}: missing required {runtime} key {key!r}")
            elif json_type(event[key]) != expected:
                failures.add(
                    "envelope",
                    f"{where}: {key!r} is {json_type(event[key])}, contract says {expected}",
                )
        for key, expected in optional.items():
            if key in event and json_type(event[key]) != expected:
                failures.add(
                    "envelope",
                    f"{where}: {key!r} is {json_type(event[key])}, but the other runtime "
                    f"stamps it as {expected} — the shared key must keep one type",
                )
        for key in forbidden:
            if key in event:
                failures.add(
                    "envelope",
                    f"{where}: carries {key!r}, which contract.json declares Python-only — "
                    f"declare it as shared if emitting it here is intended",
                )


def check_collision(
    runtime: str, events: list[dict[str, Any]], contract: dict[str, Any], failures: Failures
) -> None:
    """A caller field named like an envelope key lands under the shared prefix."""
    prefix = contract["collision_prefix"]["value"]
    scenario = next(s for s in contract["scenarios"] if s["id"] == "collision")
    line = find_by_message(events, scenario["message"])
    if line is None:
        failures.add("collision", f"{runtime}: no {scenario['message']!r} line was emitted")
        return
    for key in scenario["collides_with"]:
        prefixed = f"{prefix}{key}"
        if prefixed not in line:
            failures.add(
                "collision",
                f"{runtime}: caller set {key!r} but the line has no {prefixed!r} — the "
                f"collision prefix must be {prefix!r} on both runtimes",
            )
        if line.get(key) == "HIJACKED":
            failures.add(
                "collision",
                f"{runtime}: app code overwrote the envelope's {key!r} — it must be "
                f"re-emitted as {prefixed!r} instead",
            )


def check_resolution(
    runtime: str, events: list[dict[str, Any]], probe: dict[str, Any], failures: Failures
) -> None:
    """Both runtimes resolve env/commit from the same variables, in the same order.

    A type check cannot see this: reading a different variable still produces a
    string. Only running both under one known environment and comparing the
    VALUES can, which is why `run.py` owns the environment rather than
    inheriting it.
    """
    for key, expected in probe["expected"].items():
        wrong = {str(e.get(key)) for e in events if e.get(key) != expected}
        if wrong:
            failures.add(
                "resolution",
                f"{runtime}: with {probe['environment']}, {key} resolved to "
                f"{sorted(wrong)} instead of {expected!r} — the two runtimes read "
                f"different variables or apply a different precedence",
            )


def find_by_message(events: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    """The first line whose event name matches, or None."""
    return next((e for e in events if e.get("message") == message), None)


def find_boundary(
    events: list[dict[str, Any]], contract: dict[str, Any], runtime: str, outcome: str
) -> dict[str, Any] | None:
    """The canonical event for one outcome, by this runtime's boundary names."""
    names = set(contract["boundary"]["messages"][runtime])
    return next(
        (e for e in events if e.get("message") in names and e.get("outcome") == outcome), None
    )


def shape(event: dict[str, Any], ignored: set[str]) -> dict[str, str]:
    """key -> JSON type, minus the keys contract.json declares asymmetric."""
    return {k: json_type(v) for k, v in event.items() if k not in ignored}


def entry_shapes(event: dict[str, Any], key: str) -> list[dict[str, str]]:
    """Shapes of one entry array's elements (errors[]/warnings[]/audit[])."""
    entries = event.get(key)
    if not isinstance(entries, list):
        return []
    return [{k: json_type(v) for k, v in e.items()} for e in entries if isinstance(e, dict)]


def check_boundary_fields(
    runtime: str, event: dict[str, Any], contract: dict[str, Any], failures: Failures
) -> None:
    """The canonical event carries every boundary field, correctly typed."""
    for key, spec in contract["boundary"]["fields"].items():
        if key not in event:
            failures.add(
                "boundary",
                f"{runtime} {event.get('message')!r}: missing boundary field {key!r}",
            )
            continue
        actual = json_type(event[key])
        if actual != spec["type"]:
            failures.add(
                "boundary", f"{runtime}: {key!r} is {actual}, contract says {spec['type']}"
            )
            continue
        pattern = spec.get("pattern")
        if pattern and not re.fullmatch(pattern, str(event[key])):
            failures.add("boundary", f"{runtime}: {key}={event[key]!r} does not match {pattern}")
        allowed = spec.get("enum")
        if allowed and event[key] not in allowed:
            failures.add("boundary", f"{runtime}: {key}={event[key]!r} not in {allowed}")


def check_exception_fields(
    runtime: str, event: dict[str, Any], contract: dict[str, Any], failures: Failures
) -> None:
    """A line describing a throwable uses the two flat scalars, never an object."""
    for key, expected in contract["entry"]["exception"].items():
        if key.startswith("$"):
            continue
        if key not in event:
            failures.add(
                "exception-shape",
                f"{runtime} {event.get('message')!r}: missing {key!r} — a thrown value is "
                f"described by {sorted(k for k in contract['entry']['exception'] if not k.startswith('$'))}",
            )
        elif json_type(event[key]) != expected:
            failures.add(
                "exception-shape",
                f"{runtime} {event.get('message')!r}: {key!r} is {json_type(event[key])}, "
                f"contract says {expected} — a nested error object is the one shape "
                f"LogQL `| json` cannot unwrap",
            )


def diff_pair(label: str, py: dict[str, str], ts: dict[str, str], failures: Failures) -> None:
    """Report every key on which the two runtimes' shapes disagree."""
    for key in sorted(set(py) | set(ts)):
        in_py, in_ts = py.get(key), ts.get(key)
        if in_py == in_ts:
            continue
        if in_py is None:
            failures.add("cross-runtime", f"{label}: {key!r} is TypeScript-only ({in_ts})")
        elif in_ts is None:
            failures.add("cross-runtime", f"{label}: {key!r} is Python-only ({in_py})")
        else:
            failures.add(
                "cross-runtime", f"{label}: {key!r} is {in_py} in Python but {in_ts} in TypeScript"
            )


def main() -> int:
    """Emit from both runtimes, validate each, and diff the two shapes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show-capture", action="store_true", help="print the captured NDJSON from both runtimes"
    )
    args = parser.parse_args()

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    envelope = contract["envelope"]
    # Keys contract.json declares asymmetric. check_envelope type-checks them
    # per runtime; excluding them here keeps the pair diff about real drift.
    asymmetric = set(declared(envelope["python_only"])) | set(
        declared(envelope["typescript_envelope"])
    )

    probe = contract["resolution_probe"]
    captures = {
        "python": run_emitter("Python", PYTHON_EMITTER, probe["environment"]),
        "typescript": run_emitter("TypeScript", TYPESCRIPT_EMITTER, probe["environment"]),
    }
    if args.show_capture:
        for runtime, events in captures.items():
            print(f"--- {runtime} ---")
            for event in events:
                print(json.dumps(event))

    failures = Failures()
    for runtime, events in captures.items():
        check_envelope(runtime, events, contract, failures)
        check_collision(runtime, events, contract, failures)
        check_resolution(runtime, events, probe, failures)

    for scenario in contract["scenarios"]:
        if scenario["kind"] == "realtime":
            py = find_by_message(captures["python"], scenario["message"])
            ts = find_by_message(captures["typescript"], scenario["message"])
        else:
            py = find_boundary(captures["python"], contract, "python", scenario["outcome"])
            ts = find_boundary(captures["typescript"], contract, "typescript", scenario["outcome"])

        for runtime, event in (("python", py), ("typescript", ts)):
            if event is None:
                failures.add(
                    "scenario",
                    f"{runtime}: scenario {scenario['id']!r} produced no line — the emitter and "
                    f"contract.json disagree about what this runtime emits",
                )
        if py is None or ts is None:
            continue

        label = f"scenario {scenario['id']}"
        # The boundary event name differs by design (worker_task vs bot_event)
        # and is declared per runtime in the contract, so it is not compared.
        py_shape = shape(py, asymmetric | {"message"})
        ts_shape = shape(ts, asymmetric | {"message"})
        diff_pair(label, py_shape, ts_shape, failures)

        if scenario.get("carries_exception") and scenario["kind"] == "realtime":
            check_exception_fields("python", py, contract, failures)
            check_exception_fields("typescript", ts, contract, failures)

        if scenario["kind"] != "boundary":
            continue

        check_boundary_fields("python", py, contract, failures)
        check_boundary_fields("typescript", ts, contract, failures)
        for key in contract["boundary"]["entry_arrays"]:
            py_entries = entry_shapes(py, key)
            ts_entries = entry_shapes(ts, key)
            if len(py_entries) != len(ts_entries):
                failures.add(
                    "cross-runtime",
                    f"{label}: {key}[] has {len(py_entries)} entries in Python and "
                    f"{len(ts_entries)} in TypeScript",
                )
                continue
            for index, (py_entry, ts_entry) in enumerate(zip(py_entries, ts_entries, strict=True)):
                diff_pair(f"{label} {key}[{index}]", py_entry, ts_entry, failures)

    if failures:
        print(f"FAIL — {len(failures.items)} wide-event shape divergence(s):")
        for item in failures.items:
            print(f"  {item}")
        print(
            "\nThe Python and TypeScript log shapes have drifted. Fix BOTH of:\n"
            "  libs/shared/py/logging.py + libs/shared/py/wide_events.py\n"
            "  libs/shared/ts/src/bots/utils/logger.ts + .../wide-events.ts\n"
            "and update scripts/ci/wide-event-conformance/contract.json if the new\n"
            "shape is the intended one."
        )
        return 1

    checked = sum(len(events) for events in captures.values())
    print(
        f"OK — {checked} real log lines from both runtimes, "
        f"{len(contract['scenarios'])} scenarios, no shape divergence"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
