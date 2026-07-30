"""Per-file ratchet against a baseline map.

Comparing one aggregate score across the two runs is subtly wrong: head and
base cover asymmetric file sets (new files exist only at HEAD, renames only
under their old path), so an aggregate lets a dark new file hide behind a
touched legacy file, and blocks PRs whose new files are merely below the
average. The ratchet is therefore per file:

- a file present in both runs must score at least what it scored at base;
- a file absent from the baseline (brand-new) must meet the new-file floor;
- renames are matched via an explicit old→new map so a moved legacy file is
  compared against itself, not treated as new.

Both sides key files by their monorepo-anchored path (``repo_relative``), so
a merge-base worktree at any location compares equal to the working tree.
"""

from __future__ import annotations

from pathlib import Path

from facts import repo_relative
from scan import MapResult, weighted_score


def head_file_scores(result: MapResult) -> dict[str, int]:
    """Per-file weighted scores for a scan, keyed by repo-anchored path."""
    by_file: dict[str, list[tuple[int, str, bool]]] = {}
    for entry in result.entries:
        key = repo_relative(entry.file)
        by_file.setdefault(key, []).append((entry.score, entry.sensitivity.level, entry.exempt))
    return {key: weighted_score(items) for key, items in by_file.items()}


def baseline_file_scores(baseline: dict[str, object]) -> dict[str, int]:
    """Per-file weighted scores reconstructed from a ``--json`` baseline."""
    by_file: dict[str, list[tuple[int, str, bool]]] = {}
    entries = baseline.get("entries")
    if not isinstance(entries, list):
        raise ValueError("baseline is not an evlog map --json output (no entries array)")
    for entry in entries:
        key = repo_relative(Path(str(entry["file"])))
        sensitivity = entry.get("sensitivity", {})
        by_file.setdefault(key, []).append(
            (
                int(entry["score"]),
                str(sensitivity.get("level", "none")),
                bool(entry.get("exempt", False)),
            )
        )
    return {key: weighted_score(items) for key, items in by_file.items()}


def load_rename_map(path: Path) -> dict[str, str]:
    """``old<TAB>new`` pairs mapping baseline paths to their HEAD paths."""
    renames: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        old, sep, new = line.partition("\t")
        if not sep or not old.strip() or not new.strip():
            raise ValueError(f"{path}:{lineno}: expected 'old<TAB>new', got {line!r}")
        renames[old.strip()] = new.strip()
    return renames


def compare_to_baseline(
    head_scores: dict[str, int],
    base_scores: dict[str, int],
    renames: dict[str, str],
    min_new_score: int,
) -> list[str]:
    """Failure messages for every file that regressed or missed the new-file floor."""
    rebased = {renames.get(key, key): score for key, score in base_scores.items()}
    failures: list[str] = []
    for key in sorted(head_scores):
        head = head_scores[key]
        base = rebased.get(key)
        if base is None:
            if head < min_new_score:
                failures.append(
                    f"new file {key} scores {head} — below the {min_new_score} floor "
                    "for files with no baseline"
                )
        elif head < base:
            failures.append(
                f"observability regression: {key} scores {head} at HEAD vs {base} at the baseline"
            )
    return failures
