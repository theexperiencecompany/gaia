"""The capability suite meters every agent call by riding agent_helpers._build_agent_callbacks.

Its wrapper must keep the seam's signature: a stale one raised TypeError before any agent ran.
"""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler
import pytest
from scripts.evals.suites import capability

from app.helpers import agent_helpers


def test_the_patched_seam_still_builds_callbacks_and_adds_the_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = BaseCallbackHandler()
    monkeypatch.setattr(
        agent_helpers, "_build_agent_callbacks", agent_helpers._build_agent_callbacks
    )
    monkeypatch.setattr(capability, "_CALLBACK_PATCHED", False)
    monkeypatch.setattr(capability, "_ACTIVE_TRACKER", tracker)

    capability._patch_agent_callbacks()
    callbacks = agent_helpers._build_agent_callbacks(None)

    assert callbacks[-1] is tracker
