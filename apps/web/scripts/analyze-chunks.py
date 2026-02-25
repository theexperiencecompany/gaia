"""
Analyze Turbopack SSR chunks to identify what packages/modules are inside.

Turbopack embeds module paths as comments or identifiers in the chunk files.
This script extracts them and estimates per-package contribution.

Usage: python3 scripts/analyze-chunks.py [chunk_path]
  If no path given, analyzes the top 5 largest chunks.
"""

import re, sys, os
from collections import defaultdict
from pathlib import Path

chunks_dir = Path(".next/server/chunks")
ssr_dir = chunks_dir / "ssr"


def analyze_chunk(filepath):
    text = Path(filepath).read_text(errors="ignore")
    size_kb = len(text) / 1024

    # Turbopack embeds paths like:
    #   [project]/node_modules/package-name/file.js
    #   [project]/apps/web/src/features/...
    # Also look for: "node_modules/pkg/..." patterns
    patterns = [
        # [project]/node_modules/...
        re.compile(r'\[project\]/node_modules/((?:@[\w.-]+/)?[\w.-]+)'),
        # [project]/apps/web/src/...
        re.compile(r'\[project\]/apps/web/(src/[\w.-]+/[\w.-]+)'),
        # Plain node_modules references
        re.compile(r'node_modules/((?:@[\w.-]+/)?[\w.-]+)/'),
    ]

    # Find all matches with positions
    all_matches = []
    for pat in patterns:
        for m in pat.finditer(text):
            all_matches.append((m.start(), m.group(1)))

    if not all_matches:
        return size_kb, {}

    all_matches.sort(key=lambda x: x[0])

    # Estimate sizes by position gaps
    pkg_sizes = defaultdict(int)
    for i in range(len(all_matches)):
        pkg = all_matches[i][1]
        start = all_matches[i][0]
        end = all_matches[i + 1][0] if i + 1 < len(all_matches) else len(text)
        pkg_sizes[pkg] += end - start

    return size_kb, dict(pkg_sizes)


def main():
    if len(sys.argv) > 1:
        files = [sys.argv[1]]
    else:
        # Find top 10 largest chunks
        all_chunks = []
        for d in [chunks_dir, ssr_dir]:
            if d.exists():
                for f in d.glob("*.js"):
                    if not f.name.endswith(".map"):
                        all_chunks.append((f, f.stat().st_size))
        all_chunks.sort(key=lambda x: x[1], reverse=True)
        files = [str(f) for f, _ in all_chunks[:10]]

    grand_totals = defaultdict(int)

    for filepath in files:
        name = os.path.basename(filepath)
        parent = os.path.basename(os.path.dirname(filepath))
        label = f"{parent}/{name}" if parent != "chunks" else name

        size_kb, pkg_sizes = analyze_chunk(filepath)

        print(f"\n{'='*70}")
        print(f"{label}  ({size_kb:.0f} KiB)")
        print(f"{'='*70}")

        if not pkg_sizes:
            print("  (no recognizable module paths found)")
            continue

        print(f"  {'Module/Package':<50} {'KiB':>8}")
        print(f"  {'-'*60}")
        for pkg, size in sorted(pkg_sizes.items(), key=lambda x: x[1], reverse=True)[:15]:
            print(f"  {pkg:<50} {size/1024:>8.1f}")
            grand_totals[pkg] += size

    if len(files) > 1:
        print(f"\n{'='*70}")
        print(f"GRAND TOTALS ACROSS ALL ANALYZED CHUNKS")
        print(f"{'='*70}")
        print(f"  {'Module/Package':<50} {'KiB':>8}")
        print(f"  {'-'*60}")
        for pkg, size in sorted(grand_totals.items(), key=lambda x: x[1], reverse=True)[:30]:
            print(f"  {pkg:<50} {size/1024:>8.1f}")


if __name__ == "__main__":
    main()
