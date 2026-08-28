"""Small-scope mutation testing for the account mutation surface.

Applies one mutation at a time to a production module, runs the minimal unit
suite that covers it, restores the file, and reports killed/survived. Runs via
subprocess (in-process pytest.main hangs on this repo's root conftest) but each
run is the venv interpreter directly — no uv cold start — and only the covering
file, so a mutant costs ~5s.

Bounded by design: 16 mutants ≈ 2 minutes serial; --jobs caps parallelism.

Usage:
  .venv/bin/python scripts/dev/mutation_check_account.py [--only M1,M2] [--jobs 2]
Run from apps/api (or anywhere; paths are repo-anchored).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

REPO_API = Path(__file__).resolve().parents[2] / "apps" / "api"

# Minimal covering suite per mutated module.
COVERING_TESTS: dict[str, list[str]] = {
    "app/agents/tools/core/mutations.py": ["tests/unit/agents/tools/test_mutations_factory.py"],
    "app/services/account_settings.py": ["tests/unit/services/test_account_settings.py"],
    "app/constants/account.py": ["tests/unit/constants/test_account.py"],
    "app/services/storage/account_vfs.py": ["tests/unit/storage/test_account_vfs.py"],
}

MUTATIONS = [
    # (id, file, old, new) — every `old` must occur exactly once in the file.
    # --- factory: auth + error envelope -----------------------------------
    (
        "M01",
        "app/agents/tools/core/mutations.py",
        "return user_id.strip() or None",
        "return user_id",
    ),
    ("M02", "app/agents/tools/core/mutations.py", "if not user_id:", "if False:"),
    ("M03", "app/agents/tools/core/mutations.py", 'detail += f" Fix: {e.fix}"', "pass"),
    (
        "M04",
        "app/agents/tools/core/mutations.py",
        'capture_context_event(event, {"area": area})',
        'capture_context_event(event, {"area": "wrong"})',
    ),
    ("M05", "app/agents/tools/core/mutations.py", "return result", 'return "done"'),
    # --- appliers: guards and boundaries ----------------------------------
    ("M06", "app/services/account_settings.py", "if not given:", "if False:"),
    ("M07", "app/services/account_settings.py", "if not style:", "if False:"),
    (
        "M08",
        "app/services/account_settings.py",
        "len(value) > MAX_CUSTOM_INSTRUCTIONS_CHARS",
        "len(value) > MAX_CUSTOM_INSTRUCTIONS_CHARS + 1",
    ),
    ("M09", "app/services/account_settings.py", "if not is_valid_timezone(tz):", "if False:"),
    (
        "M10",
        "app/services/account_settings.py",
        "v.voice_id == query or v.name.lower() == query.lower()",
        "v.name.lower() == query.lower()",
    ),
    ("M11", "app/services/account_settings.py", "catalog.voices[:15]", "catalog.voices"),
    (
        "M12",
        "app/services/account_settings.py",
        "value = instructions.strip() or None",
        'value = instructions.strip() or ""',
    ),
    # --- refusal map -------------------------------------------------------
    (
        "M13",
        "app/constants/account.py",
        'if not rel_path.startswith(f"{ACCOUNT_DIR}/"):\n        return None',
        "return None",
    ),
    (
        "M14",
        "app/constants/account.py",
        'AccountArea.NOTIFICATIONS: "update_notification_settings"',
        'AccountArea.NOTIFICATIONS: "update_preferences"',
    ),
    # --- materializer: the self-heal contract ------------------------------
    (
        "M15",
        "app/services/storage/account_vfs.py",
        'if matches_text(target, doc["body"]):',
        "if True:",
    ),
    # M16 is an ACCEPTED EQUIVALENT MUTANT: chmod-before-unlink is defensive
    # for filesystems that refuse to unlink read-only files (JuiceFS); on
    # macOS/Linux plain unlink succeeds either way, so no behavioral test can
    # distinguish it without spying on chmod calls.
    (
        "M16",
        "app/services/storage/account_vfs.py",
        "existing.chmod(0o644)\n            existing.unlink(missing_ok=True)",
        "existing.unlink(missing_ok=True)",
    ),
]


def run_pytest(test_files: list[str]) -> bool:
    # Must go through `uv run`: the root conftest needs its env setup — a bare
    # venv interpreter hangs on boot.
    result = subprocess.run(
        [
            "uv",
            "run",
            "--group",
            "backend",
            "--group",
            "dev",
            "python",
            "-m",
            "pytest",
            *test_files,
            "-q",
            "-x",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_API,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return result.returncode == 0


def check_mutant(mid: str, rel_file: str, old: str, new: str) -> tuple[str, str]:
    path = REPO_API / rel_file
    original = originals[rel_file]
    if original.count(old) != 1:
        return mid, "SKIP - pattern not unique/found"
    try:
        path.write_text(original.replace(old, new))
        outcome = "KILLED" if not run_pytest(COVERING_TESTS[rel_file]) else "SURVIVED"
    finally:
        path.write_text(original)
    return mid, outcome


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None)
    args = parser.parse_args()
    only = set(args.only.split(",")) if args.only else None

    global originals
    originals = {rel: (REPO_API / rel).read_text() for _, rel, _, _ in MUTATIONS}

    # Baseline must be green before any mutation is meaningful.
    all_covering = sorted({f for files in COVERING_TESTS.values() for f in files})
    if not run_pytest(all_covering):
        print("BASELINE RED - fix the suite first; mutation results would be noise.")
        return 2
    print(f"baseline green ({MUTANTS_QUEUED(only)} mutants queued)\n")

    selected = [m for m in MUTATIONS if only is None or m[0] in only]
    killed: list[str] = []
    survived: list[str] = []
    equivalent = {"M16"}  # documented accepted-equivalent in MUTATIONS above
    # Strictly serial: concurrent mutants of the SAME file overwrite and restore
    # each other mid-run (a race that produced false survivors).
    for mutant in selected:
        mid, outcome = check_mutant(*mutant)
        print(f"{mid} {outcome}  ({mutant[1]})", flush=True)
        if outcome == "KILLED":
            killed.append(mid)
        elif outcome == "SURVIVED":
            survived.append(mid)

    unexpected = [mid for mid in survived if mid not in equivalent]
    print(f"\n{len(killed)} killed / {len(survived)} survived")
    if survived:
        print("SURVIVED:", ", ".join(survived))
    if unexpected:
        print("UNEXPECTED SURVIVORS:", ", ".join(unexpected))
        return 1
    return 0


def MUTANTS_QUEUED(only: set[str] | None) -> int:
    return sum(1 for m in MUTATIONS if only is None or m[0] in only)


if __name__ == "__main__":
    raise SystemExit(main())
