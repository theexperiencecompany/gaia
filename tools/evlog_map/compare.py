"""Per-file ratchet against a baseline map.

Comparing one aggregate score across the two runs is subtly wrong: head and
base cover asymmetric file sets (new files exist only at HEAD, renames only
under their old path), so an aggregate lets a dark new file hide behind a
touched legacy file, and blocks PRs whose new files are merely below the
average. The ratchet is therefore per file:

- a file present in both runs must score at least what it scored at base;
- a file absent from the baseline (brand-new) must meet the new-file floor;
- a file whose entry points were all discovered at base and none at HEAD is a
  discovery collapse — the score would read 100 because there is nothing left
  to score, so it is failed outright;
- renames are matched via an explicit old→new map so a moved legacy file is
  compared against itself, not treated as new.

Both sides key files by their monorepo-anchored path (``repo_relative``), so
a merge-base worktree at any location compares equal to the working tree.
"""

from __future__ import annotations

from pathlib import Path

from facts import repo_relative
from scan import MapResult, weighted_score

# One discovered entry point: ``(score, sensitivity level, exempt)``.
EntryStat = tuple[int, str, bool]


def head_file_entries(result: MapResult) -> dict[str, list[EntryStat]]:
    """Per-file discovered entry points for a scan, keyed by repo-anchored path."""
    by_file: dict[str, list[EntryStat]] = {}
    for entry in result.entries:
        key = repo_relative(entry.file)
        by_file.setdefault(key, []).append((entry.score, entry.sensitivity.level, entry.exempt))
    return by_file


def baseline_file_entries(baseline: dict[str, object]) -> dict[str, list[EntryStat]]:
    """Per-file discovered entry points reconstructed from a ``--json`` baseline."""
    by_file: dict[str, list[EntryStat]] = {}
    entries = baseline.get("entries")
    if not isinstance(entries, list):
        raise ValueError("baseline is not an evlog map --json output (no entries array)")
    for entry in entries:
        key = repo_relative(Path(str(entry["file"])))
        sensitivity = entry.get("sensitivity", {})
        by_file.setdefault(key, []).append(
            (
                int(entry["score"]),
                str(sensitivity.get("level", "low")),
                bool(entry.get("exempt", False)),
            )
        )
    return by_file


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
    head_entries: dict[str, list[EntryStat]],
    base_entries: dict[str, list[EntryStat]],
    renames: dict[str, str],
    min_new_score: int,
) -> list[str]:
    """Failure messages for every file that regressed, went dark, or missed the floor."""
    rebased = {renames.get(key, key): items for key, items in base_entries.items()}
    failures: list[str] = []
    for key in sorted(rebased):
        if rebased[key] and not head_entries.get(key):
            failures.append(
                f"discovery collapse: {key} had {len(rebased[key])} entry point(s) at the "
                "baseline and none at HEAD — the scanner can no longer see them, so its "
                "score is vacuous"
            )
    for key in sorted(head_entries):
        head = weighted_score(head_entries[key])
        base_items = rebased.get(key)
        if base_items is None:
            if head < min_new_score:
                failures.append(
                    f"new file {key} scores {head} — below the {min_new_score} floor "
                    "for files with no baseline"
                )
            continue
        base = weighted_score(base_items)
        if head < base:
            failures.append(
                f"observability regression: {key} scores {head} at HEAD vs {base} at the baseline"
            )
    return failures
