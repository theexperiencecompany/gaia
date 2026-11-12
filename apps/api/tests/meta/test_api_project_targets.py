"""The API's nx targets build what the running API needs before it starts."""

import json
from pathlib import Path

import pytest

# Read from the checkout, not via app/: the mutation lane runs a relocated app/ with no repo around it.
API_PROJECT = Path(__file__).resolve().parents[2] / "project.json"


@pytest.mark.parametrize("target", ["dev", "worker"])
def test_running_the_api_natively_builds_the_validator_first(target: str) -> None:
    """Regression: on a fresh checkout every artifact failed until the bundle was built by hand."""
    project = json.loads(API_PROJECT.read_text())

    assert {"projects": ["artifact-validate"], "target": "build"} in project["targets"][target].get(
        "dependsOn", []
    )
