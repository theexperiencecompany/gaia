"""output_findings.py — what a tool printed, read back as findings at file:line.

`verdict.py check` (every gated check step's shell) and `verdict.py collect`
both turn a tool's output into the findings a verdict carries. Each reader
below knows one output shape; all of them run over the text, and a tool whose
output none of them recognises still yields one finding carrying its first
error lines, so a red check never reports "<tool> failed" and nothing else.

A finding's `detail` starts with its error lines — the assertion, the message
the tool printed — because that is what a reader sees first: `mise ci:remote`
previews the first three. A finding with no location has file "" and line 0;
a made-up location would send the reader to a line that says nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import re
from typing import NamedTuple, NotRequired, TypedDict

DETAIL_LINES = 20
MESSAGE_CHARS = 500
MAX_FINDINGS = 200
# How far below a vitest FAIL header its `❯ file:line:col` frame may sit.
VITEST_FRAME_WINDOW = 40

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class Finding(TypedDict):
    """One concrete thing a reader can go fix, at the line it is on."""

    file: str
    line: int
    message: str
    detail: NotRequired[str]


class _Hit(NamedTuple):
    """A finding and the output line it was read from, so readers merge in output order."""

    position: int
    finding: Finding


def _finding(file: str, line: int, message: str, detail: list[str] | None = None) -> Finding:
    found: Finding = {"file": file, "line": line, "message": message.strip()[:MESSAGE_CHARS]}
    body = [d for d in (detail or []) if d.strip()][:DETAIL_LINES]
    if body:
        found["detail"] = "\n".join(body)
    return found


# --- GitHub workflow commands -------------------------------------------------
# Our own lints and checks.mjs print `::error file=,line=::` themselves; it is
# the most precise thing in any log, so it is read first.

_COMMAND = re.compile(r"^::error(?: (?P<props>[^:]*))?::(?P<message>.*)$")
_UNESCAPE = (("%0D", "\r"), ("%0A", "\n"), ("%3A", ":"), ("%2C", ","), ("%25", "%"))


def _unescape(text: str) -> str:
    for escaped, raw in _UNESCAPE:
        text = text.replace(escaped, raw)
    return text


def _workflow_commands(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines):
        match = _COMMAND.match(raw.strip())
        if not match:
            continue
        props = dict(
            part.split("=", 1) for part in (match.group("props") or "").split(",") if "=" in part
        )
        file = _unescape(props.get("file", ""))
        if not file:
            continue
        line = props.get("line", "")
        message, *rest = _unescape(match.group("message")).splitlines() or [""]
        yield _Hit(index, _finding(file, int(line) if line.isdigit() else 1, message, rest))


# --- pytest ---------------------------------------------------------------------
# The short summary names every failed test; its section above holds where it
# failed (`path.py:12: AssertionError`) and the `E ` lines that say why.

_PYTEST_SUMMARY = re.compile(r"^(?P<kind>FAILED|ERROR) (?P<node>\S.*?)(?: - (?P<message>.*))?$")
_PYTEST_SECTION = re.compile(r"^_{3,} (?P<name>.+?) _{3,}$")
_PYTEST_END = re.compile(r"^={3,}")
_PYTEST_LOCATION = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+): ")


def _pytest_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in lines:
        header = _PYTEST_SECTION.match(raw.strip())
        if header:
            current = sections.setdefault(header.group("name"), [])
            continue
        if _PYTEST_END.match(raw.strip()):
            current = None
            continue
        if current is not None:
            current.append(raw)
    return sections


def _section_for(node: str, sections: dict[str, list[str]]) -> list[str]:
    parts = node.split("::")[1:]
    if not parts:
        return []
    qualified = ".".join(parts)
    return sections.get(qualified) or sections.get(parts[-1]) or []


def _pytest(lines: list[str]) -> Iterator[_Hit]:
    sections: dict[str, list[str]] | None = None
    for index, raw in enumerate(lines):
        match = _PYTEST_SUMMARY.match(raw.strip())
        if not match or "::" not in match.group("node"):
            continue
        if sections is None:
            sections = _pytest_sections(lines)
        node = match.group("node").strip()
        file = node.split("::", 1)[0]
        body = _section_for(node, sections)
        locations = [m for m in map(_PYTEST_LOCATION.match, body) if m]
        own = [m for m in locations if m.group("file") == file]
        line = int((own or locations)[-1].group("line")) if locations else 1
        errors = [b.strip()[1:].strip() for b in body if b.startswith("E ")]
        summary = match.group("message") or ""
        message = f"{match.group('kind')} {node}" + (f" — {summary}" if summary else "")
        yield _Hit(index, _finding(file, line, message, errors or [summary]))


# --- vitest and Playwright -----------------------------------------------------

_VITEST_FAIL = re.compile(
    r"\bFAIL\s+(?:\|[^|]+\|\s+)?(?P<file>\S+\.(?:test|spec)\.[cm]?[jt]sx?)\s+>\s+(?P<name>.+?)\s*$"
)
_VITEST_FRAME = re.compile(r"❯\s+(?P<file>\S+?):(?P<line>\d+):\d+")
_VITEST_RULE = re.compile(r"^\s*⎯")


def _vitest(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines):
        match = _VITEST_FAIL.search(raw)
        if not match:
            continue
        file, line, errors = match.group("file"), 1, []
        for following in lines[index + 1 : index + 1 + VITEST_FRAME_WINDOW]:
            if _VITEST_FAIL.search(following) or _VITEST_RULE.match(following):
                break
            frame = _VITEST_FRAME.search(following)
            if frame:
                if frame.group("file").endswith(file):
                    line = int(frame.group("line"))
                    break
                continue
            errors.append(following.strip())
        yield _Hit(index, _finding(file, line, f"FAIL {file} > {match.group('name')}", errors))


_PLAYWRIGHT_FAIL = re.compile(
    r"^\s*\d+\) \[[^\]]+\] › (?P<file>\S+?):(?P<line>\d+):\d+ › (?P<name>.+?)\s*─*\s*$"
)
_CODE_FRAME = re.compile(r"^\s*>?\s*\d+ \|")


def _playwright(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines):
        match = _PLAYWRIGHT_FAIL.match(raw)
        if not match:
            continue
        errors: list[str] = []
        for following in lines[index + 1 :]:
            if _PLAYWRIGHT_FAIL.match(following) or _CODE_FRAME.match(following):
                break
            errors.append(following.strip())
            if len(errors) >= DETAIL_LINES:
                break
        file, line = match.group("file"), int(match.group("line"))
        yield _Hit(index, _finding(file, line, f"FAILED {file} › {match.group('name')}", errors))


_BANDIT_ISSUE = re.compile(r"^>> Issue: (?P<message>\[\S+\] .+)$")
_BANDIT_LOCATION = re.compile(r"^Location: (?:\./)?(?P<file>\S+?):(?P<line>\d+)(?::\d+)?$")
# The `Location:` line sits a few lines below its `>> Issue:` line.
BANDIT_LOCATION_WINDOW = 6


def _bandit(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines):
        issue = _BANDIT_ISSUE.match(raw.strip())
        if not issue:
            continue
        for following in lines[index + 1 : index + 1 + BANDIT_LOCATION_WINDOW]:
            where = _BANDIT_LOCATION.match(following.strip())
            if where:
                file, line = where.group("file"), int(where.group("line"))
                yield _Hit(index, _finding(file, line, issue.group("message")))
                break


# ruff's default output: `F401 [*] message`, then ` --> path:line:col`.
_RUFF_RULE = re.compile(r"^(?P<code>[A-Z]+[0-9]+) (?:\[\*\] )?(?P<message>\S.*)$")
_RUFF_ARROW = re.compile(r"^-->\s*(?P<file>\S+?):(?P<line>\d+):\d+$")


def _ruff(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines[:-1]):
        rule = _RUFF_RULE.match(raw.strip())
        where = _RUFF_ARROW.match(lines[index + 1].strip()) if rule else None
        if rule and where:
            message = f"{rule.group('code')} {rule.group('message')}"
            yield _Hit(index, _finding(where.group("file"), int(where.group("line")), message))


# --- one line per finding ----------------------------------------------------------
# (pattern, message) — the message reads the match, or None for the line itself.

_LineReader = tuple[re.Pattern[str], Callable[[re.Match[str]], str] | None]

_LINE_READERS: list[_LineReader] = [
    # mypy: path:line[:col]: error: msg
    (re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):(?:\d+:)?\s*error:"), None),
    # tsc: path(line,col): error TS...
    (re.compile(r"^(?P<file>[^\(\s]+)\((?P<line>\d+),\d+\):\s*error"), None),
    # ruff concise: path:line:col: CODE msg
    (re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):\d+:\s*[A-Z]+\d+\s"), None),
    # biome concise: path:line:col lint/category
    (re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):\d+\s+\S"), None),
    # tools/lints: `  path:line  message`
    (
        re.compile(r"^(?P<file>[\w./@+-]*[/.][\w./@+-]*):(?P<line>\d+)\s{2,}(?P<message>\S.*)$"),
        None,
    ),
    # checks.mjs file-sizes: `  1169 / 700  path`
    (
        re.compile(r"^(?P<size>\d+) / (?P<cap>\d+)\s+(?P<file>\S+)$"),
        lambda m: f"{m.group('size')} lines, over its {m.group('cap')}-line cap",
    ),
    # ruff format --check
    (
        re.compile(r"^Would reformat: (?P<file>\S+)$"),
        lambda _m: "not ruff-formatted — run `ruff format` on it",
    ),
]


def _line_readers(lines: list[str]) -> Iterator[_Hit]:
    for index, raw in enumerate(lines):
        text = raw.strip()
        for pattern, describe in _LINE_READERS:
            match = pattern.match(text)
            if not match:
                continue
            groups = match.groupdict()
            line = int(groups.get("line") or 1)
            message = describe(match) if describe else groups.get("message") or text
            yield _Hit(index, _finding(match.group("file"), line, message))
            break


def annotated_locations(text: str) -> set[str]:
    """Return the `file:line` of every `::error` the tool printed — GitHub already shows those."""
    lines = [ANSI.sub("", raw) for raw in text.splitlines()]
    return {f"{h.finding['file']}:{h.finding['line']}" for h in _workflow_commands(lines)}


_READERS = (_workflow_commands, _pytest, _vitest, _playwright, _bandit, _ruff, _line_readers)

# --- the fallback ------------------------------------------------------------------

_ERRORISH = re.compile(
    r"(?i)(\berr(or)?s?\b|\bfailed\b|\bfailure\b|\bfatal\b|exception|traceback|violation|✗|×|❌|^E\s)"
)
_NOISE = re.compile(r"^(::(?!error)|##\[(?!error)|Process completed with exit code)")


def _fallback(lines: list[str], fallback: str | None) -> list[Finding]:
    body = [line.strip() for line in lines if line.strip() and not _NOISE.match(line.strip())]
    if not body:
        return []
    errorish = [line for line in body if _ERRORISH.search(line)]
    shown = [
        _unescape(_COMMAND.sub(r"\g<message>", line)) for line in (errorish or body[-DETAIL_LINES:])
    ]
    return [_finding(fallback or "", 1 if fallback else 0, shown[0], shown)]


def read(text: str, *, fallback: str | None = None, path_prefix: str = "") -> list[Finding]:
    """Every finding in a tool's output, in output order, else one carrying its first error lines.

    `fallback` pins a location-less result to a file the reader opens anyway (a
    manifest for a tool that names a package); without it that result has none.
    """
    lines = [ANSI.sub("", raw) for raw in text.splitlines()]
    seen: set[tuple[str, int, str]] = set()
    hits: list[_Hit] = []
    for reader in _READERS:
        for hit in reader(lines):
            key = (hit.finding["file"], hit.finding["line"], hit.finding["message"])
            if key not in seen:
                seen.add(key)
                hits.append(hit)
    found = [hit.finding for hit in sorted(hits, key=lambda h: h.position)][:MAX_FINDINGS]
    if not found:
        found = _fallback(lines, fallback)
    if path_prefix:
        for finding in found:
            if finding["file"] and not finding["file"].startswith("/"):
                finding["file"] = f"{path_prefix}{finding['file']}"
    return found
