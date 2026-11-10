"""Meta-tests: the speech transports are imported only by the outbox, plus a shrinking list of known callers.

import-linter cannot hold this fence: app/services is a namespace package (no __init__.py),
so grimp never puts any services module in its graph. Giving it one makes the existing
"app.utils never pulls the model stack" contracts see the real chains through services and fail.
"""

from __future__ import annotations

import ast
from pathlib import Path
import subprocess

TRANSPORT_PACKAGE = "app.services.outbox.transport"
OUTBOX_DIR = "apps/api/app/services/outbox/"

#: Producers that still speak to the user without the outbox, and why. Remove a line when its
#: caller moves behind the outbox; adding one is a design decision, not a convenience.
KNOWN_SPEAKERS: dict[str, str] = {
    "apps/api/app/agents/core/background/result_delivery.py": "executor and tracked-todo results pushed to an open chat",
    "apps/api/app/utils/notification/orchestrator.py": "notification record pushed to the in-app list",
    "apps/api/app/services/hil/notify.py": "approval prompt pushed to a backgrounded mobile app",
    "apps/api/app/agents/core/background/workflow_platform_delivery.py": "workflow run results sent to the user's chat platform",
    "apps/api/app/utils/notification/channels/external.py": "notification channel adapter for external chat platforms",
    "apps/api/app/services/platform_link_completion.py": "linked-account confirmation and first-contact greeting",
    "apps/api/app/services/platform_message_service.py": "proactive messages and reactions to a bot platform",
    "apps/api/app/services/chat/artifact_forwarder.py": "artifact files forwarded to the chat platform",
    "apps/api/app/services/browser/bot_delivery.py": "browser-run progress photos, hand-off and recap messages",
}

#: The ceiling for len(KNOWN_SPEAKERS). Lower it as callers move behind the outbox; never raise it.
KNOWN_SPEAKERS_CEILING = 9


def _repo_root() -> Path:
    return Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())


def _tracked_app_files() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "apps/api/app"], cwd=_repo_root(), text=True)
    return [line for line in out.splitlines() if line.endswith(".py")]


def _imports_a_transport(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(TRANSPORT_PACKAGE):
                return True
            if node.module == TRANSPORT_PACKAGE.rpartition(".")[0] and any(
                alias.name == "transport" for alias in node.names
            ):
                return True
        if isinstance(node, ast.Import) and any(
            alias.name.startswith(TRANSPORT_PACKAGE) for alias in node.names
        ):
            return True
    return False


def _speakers_outside_the_outbox() -> set[str]:
    root = _repo_root()
    return {
        path
        for path in _tracked_app_files()
        if not path.startswith(OUTBOX_DIR) and _imports_a_transport((root / path).read_text())
    }


def test_only_known_speakers_import_a_speech_transport() -> None:
    unknown = _speakers_outside_the_outbox() - KNOWN_SPEAKERS.keys()
    assert not unknown, (
        f"{sorted(unknown)} import a speech transport; user-facing words go through app.services.outbox"
    )


def test_every_known_speaker_still_imports_a_transport() -> None:
    stale = KNOWN_SPEAKERS.keys() - _speakers_outside_the_outbox()
    assert not stale, (
        f"{sorted(stale)} no longer import a transport; delete them from KNOWN_SPEAKERS"
    )


def test_the_known_speaker_list_only_shrinks() -> None:
    assert len(KNOWN_SPEAKERS) <= KNOWN_SPEAKERS_CEILING
    assert len(KNOWN_SPEAKERS) == KNOWN_SPEAKERS_CEILING, (
        "KNOWN_SPEAKERS shrank: lower KNOWN_SPEAKERS_CEILING to match so it cannot grow back"
    )
