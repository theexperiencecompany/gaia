"""What a sandboxed copy of scripts/ci needs to run a script that reports through verdict.py."""

# Relative to scripts/ci: verdict.py and every lib module it imports.
VERDICT_FILES = ("verdict.py", "lib/github.py", "lib/output_findings.py", "lib/nx_affected.py")
