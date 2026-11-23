"""What a sandboxed copy of scripts/ci needs to run a script that reports through verdict.py."""

# Relative to scripts/ci: verdict.py, every lib module it imports and the slice definitions it reads.
VERDICT_FILES = (
    "verdict.py",
    "lib/github.py",
    "lib/output_findings.py",
    "lib/nx_affected.py",
    "lib/test_slices.py",
    "lib/test-slices.json",
)
