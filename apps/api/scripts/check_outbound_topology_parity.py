#!/usr/bin/env python3
"""Fail if the outbound RabbitMQ topology drifts between Python and TypeScript.

The bot outbound queues are declared on BOTH sides — Python
(app/constants/outbound.py, derived from BOT_CONVERSATION_SOURCES) and
TypeScript (libs/shared/ts/src/bots/consumer/topology.ts). RabbitMQ rejects
a redeclare whose arguments differ, so a mismatch surfaces only at runtime as a
confusing publish/consume failure. This guard turns that into a fast, obvious
pre-commit/CI failure instead.

Both files are parsed textually (no app import) so the check stays fast and has
no runtime dependencies.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
# Defined in app/constants/chat.py; app/models/chat_models.py only re-exports it.
CHAT_CONSTANTS = REPO_ROOT / "apps/api/app/constants/chat.py"
TOPOLOGY_TS = REPO_ROOT / "libs/shared/ts/src/bots/consumer/topology.ts"
ENVELOPE_TS = REPO_ROOT / "libs/shared/ts/src/bots/consumer/envelope.ts"
OUTBOUND_PY = REPO_ROOT / "apps/api/app/constants/outbound.py"


def python_bot_platforms() -> set[str]:
    """Platform tokens in BOT_CONVERSATION_SOURCES (the Python source of truth)."""
    text = CHAT_CONSTANTS.read_text(encoding="utf-8")
    match = re.search(
        r"BOT_CONVERSATION_SOURCES:\s*frozenset\[ConversationSource\]\s*=\s*"
        r"frozenset\(\s*\{(.*?)\}\s*\)",
        text,
        re.DOTALL,
    )
    if not match:
        sys.exit(f"could not locate BOT_CONVERSATION_SOURCES in {CHAT_CONSTANTS}")
    return {m.lower() for m in re.findall(r"ConversationSource\.(\w+)", match.group(1))}


def ts_outbound_platforms() -> set[str]:
    """Return the keys of the TS OUTBOUND_QUEUES record.

    Values are template literals containing ${...}, so the block is
    captured up to the closing };.
    """
    text = TOPOLOGY_TS.read_text(encoding="utf-8")
    match = re.search(
        r"OUTBOUND_QUEUES:\s*Record<PlatformName,\s*string>\s*=\s*\{(.*?)\n\};",
        text,
        re.DOTALL,
    )
    if not match:
        sys.exit(f"could not locate OUTBOUND_QUEUES in {TOPOLOGY_TS}")
    return set(re.findall(r"^\s*(\w+):\s*`", match.group(1), re.MULTILINE))


def envelope_version_drift() -> list[str]:
    """Describe where the envelope version differs between the Python and TS constants."""
    py_match = re.search(r"^OUTBOUND_ENVELOPE_VERSION\s*=\s*(\d+)", OUTBOUND_PY.read_text(), re.M)
    ts_match = re.search(
        r"^export const OUTBOUND_ENVELOPE_VERSION\s*=\s*(\d+)", ENVELOPE_TS.read_text(), re.M
    )
    if not py_match or not ts_match:
        sys.exit("could not locate OUTBOUND_ENVELOPE_VERSION in outbound.py and envelope.ts")
    if py_match.group(1) == ts_match.group(1):
        return []
    return [f"envelope version: Python v{py_match.group(1)}, TypeScript v{ts_match.group(1)}"]


def receipts_queue_drift() -> list[str]:
    """Describe where the receipts queue name differs between the two sides.

    Both sides build it as ``<prefix>receipts`` from the same prefix, so the
    suffix is what can drift.
    """
    py_match = re.search(
        r'^OUTBOUND_RECEIPTS_QUEUE\s*=\s*f"\{OUTBOUND_QUEUE_PREFIX\}(\w+)"',
        OUTBOUND_PY.read_text(),
        re.M,
    )
    ts_match = re.search(
        r"^export const OUTBOUND_RECEIPTS_QUEUE\s*=\s*`\$\{OUTBOUND_QUEUE_PREFIX\}(\w+)`",
        TOPOLOGY_TS.read_text(),
        re.M,
    )
    if not py_match or not ts_match:
        sys.exit("could not locate OUTBOUND_RECEIPTS_QUEUE in outbound.py and topology.ts")
    if py_match.group(1) == ts_match.group(1):
        return []
    return [f"receipts queue: Python {py_match.group(1)!r}, TypeScript {ts_match.group(1)!r}"]


def main() -> int:
    py = python_bot_platforms()
    ts = ts_outbound_platforms()
    drift = envelope_version_drift() + receipts_queue_drift()
    if py == ts and not drift:
        return 0
    print("Outbound topology drift between Python and TypeScript:", file=sys.stderr)
    if py - ts:
        print(f"  only in Python (BOT_CONVERSATION_SOURCES): {sorted(py - ts)}", file=sys.stderr)
    if ts - py:
        print(f"  only in TypeScript (OUTBOUND_QUEUES): {sorted(ts - py)}", file=sys.stderr)
    if py != ts:
        print(
            "  add the missing platform to BOTH app/constants/chat.py and topology.ts.",
            file=sys.stderr,
        )
    for line in drift:
        print(f"  {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
