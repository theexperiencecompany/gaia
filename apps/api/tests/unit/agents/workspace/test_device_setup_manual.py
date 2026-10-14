"""The device-setup manual topic GAIA reads to guide onboarding end to end."""

import pytest

from app.agents.workspace.operational_docs import ManualTopic, get_manual


@pytest.mark.unit
def test_device_setup_topic_is_registered_and_covers_the_flow():
    doc = get_manual("device-setup")
    assert doc is not None
    body = doc.body
    assert "gaia bridge login" in body
    assert "npm install -g @heygaia/cli" in body
    # names every supported OS so GAIA can answer per-platform
    for os_name in ("macOS", "Linux", "Windows"):
        assert os_name in body
    # Device MCP tools are discovered via retrieve_tools + subagent handoff
    # (not shelled out to); run_on_device is the separate shell/file path.
    assert "retrieve_tools" in body
    assert "run_on_device" in body
    assert "device://<device_id>/<server_key>" in body


@pytest.mark.unit
def test_device_setup_is_a_valid_manual_topic_literal():
    # ManualTopic and MANUAL_DOCS are guarded to stay in sync at import; this
    # pins that "device-setup" is a member the read_manual schema accepts.
    from typing import get_args

    assert "device-setup" in get_args(ManualTopic)
