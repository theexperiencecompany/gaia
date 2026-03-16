"""
Shared grep matching utilities for VFS content search.

Provides the core line-matching and context-building logic used by both
server-side (MongoVFS.grep_content post-processing) and client-side
(VFSCommandParser._search_content / _grep_gridfs_file) grep paths.
"""

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GrepOptions:
    """Options controlling grep matching behaviour."""

    case_insensitive: bool = False
    invert: bool = False
    only_matching: bool = False
    before_context: int = 0
    after_context: int = 0
    max_matches: int = 200
    max_line_length: int = 200


def compile_pattern(pattern: str, case_insensitive: bool = False) -> re.Pattern[str]:
    """Compile a regex pattern, falling back to escaped literal on error."""
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        return re.compile(pattern, flags)
    except re.error:
        return re.compile(re.escape(pattern), flags)


def search_file_content(
    content: str,
    compiled: re.Pattern[str],
    *,
    file_path: str,
    base_path: str,
    opts: GrepOptions,
) -> dict[str, Any] | None:
    """
    Search a single file's content and return structured match results.

    Returns a dict ``{"path": str, "name": str, "matches": [...]}``
    or ``None`` if no matches.

    Each match entry has:
      - ``line_num``: int (1-based, 0 for separator lines)
      - ``line``: str
      - ``is_context``: bool
    """
    lines = content.split("\n")
    wants_context = (
        opts.before_context > 0 or opts.after_context > 0
    ) and not opts.invert

    # First pass: find matching line indices
    match_indices: list[int] = []
    for i, line in enumerate(lines):
        hit = compiled.search(line) is not None
        if hit != opts.invert:
            match_indices.append(i)
            if len(match_indices) >= opts.max_matches:
                break

    if not match_indices:
        return None

    file_matches = _build_match_entries(
        lines, match_indices, compiled, opts, wants_context
    )

    if not file_matches:
        return None

    rel_name = _relative_name(file_path, base_path)
    return {"path": file_path, "name": rel_name, "matches": file_matches}


def _build_match_entries(
    lines: list[str],
    match_indices: list[int],
    compiled: re.Pattern[str],
    opts: GrepOptions,
    wants_context: bool,
) -> list[dict[str, Any]]:
    """Build the list of match/context dicts from matched line indices."""
    file_matches: list[dict[str, Any]] = []

    if wants_context:
        include_set: set[int] = set()
        for idx in match_indices:
            start = max(0, idx - opts.before_context)
            end = min(len(lines) - 1, idx + opts.after_context)
            for j in range(start, end + 1):
                include_set.add(j)
        match_set = set(match_indices)

        prev_idx = -2
        for idx in sorted(include_set):
            if prev_idx >= 0 and idx > prev_idx + 1:
                file_matches.append(
                    {"line_num": 0, "line": "--", "is_context": False}
                )
            prev_idx = idx
            line = lines[idx]
            is_match = idx in match_set

            if is_match and opts.only_matching:
                for m in compiled.finditer(line):
                    file_matches.append(
                        {"line_num": idx + 1, "line": m.group(), "is_context": False}
                    )
            else:
                display_line = line[: opts.max_line_length]
                if len(line) > opts.max_line_length:
                    display_line += "..."
                file_matches.append(
                    {
                        "line_num": idx + 1,
                        "line": display_line,
                        "is_context": not is_match,
                    }
                )
    else:
        for idx in match_indices:
            line = lines[idx]
            if opts.only_matching and not opts.invert:
                for m in compiled.finditer(line):
                    file_matches.append(
                        {"line_num": idx + 1, "line": m.group(), "is_context": False}
                    )
            else:
                display_line = line[: opts.max_line_length]
                if len(line) > opts.max_line_length:
                    display_line += "..."
                file_matches.append(
                    {"line_num": idx + 1, "line": display_line, "is_context": False}
                )

    return file_matches


def _relative_name(file_path: str, base_path: str) -> str:
    """Compute a display-friendly relative name from a base path."""
    if base_path and file_path.startswith(base_path.rstrip("/") + "/"):
        return file_path[len(base_path.rstrip("/")) + 1 :]
    return file_path.rsplit("/", 1)[-1]
