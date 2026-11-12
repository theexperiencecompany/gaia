"""validate_program runs the real Node validator bundle built from the web artifact library."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.constants.openui_artifacts import ARTIFACT_VALIDATOR_BUNDLE, REPO_ROOT
from app.services.openui_artifacts.validate import ArtifactValidatorError, validate_program

FIXTURES = REPO_ROOT / "apps" / "web" / "src" / "features" / "artifacts" / "openui" / "__fixtures__"
SOURCE = (
    "Funnel: signed up 1,840; connected a calendar 1,210; made a first plan 754; "
    "saw the paywall 612; paid 96."
)
FUNNEL = (
    'funnel1 = Funnel("The paywall step loses the most people", "Week-one cohort", '
    '[["Signed up", 1840], ["Connected a calendar", 1210], ["Made a first plan", 754], '
    '["Saw the paywall", 612], ["Paid", 96]])'
)


@pytest.fixture(scope="module", autouse=True)
def validator_bundle() -> Path:
    if not ARTIFACT_VALIDATOR_BUNDLE.exists():
        node = shutil.which("node")
        assert node, "node is required to build the artifact validator bundle"
        subprocess.run(
            [node, str(REPO_ROOT / "tools" / "artifact-validate" / "build.mjs")], check=True
        )
    return ARTIFACT_VALIDATOR_BUNDLE


def _program(callout: str) -> str:
    return f'root = Artifact("Atlas launch", "Week one", [], [funnel1, callout1])\n{FUNNEL}\ncallout1 = {callout}\n'


async def test_grounded_program_validates_and_fills_its_slots() -> None:
    result = await validate_program(
        _program(
            'Callout("warn", "Biggest loss", "{funnel1.maxDrop} people left at {funnel1.maxDropStage}.")'
        ),
        SOURCE,
    )

    assert result.ok
    assert result.problems == []
    assert result.resolved["callout1"] == "630 people left at Signed up to Connected a calendar."
    assert result.components == 3


async def test_typed_figure_missing_from_the_brief_is_a_problem() -> None:
    result = await validate_program(
        _program('Callout("warn", "Biggest loss", "142 people did not see the paywall.")'), SOURCE
    )

    assert not result.ok
    assert result.problems == [
        "callout1.text: 142 is not in the source data; state it with a slot such as "
        "{funnel1.maxDrop}, {line1.avg~} for a rounded figure, or leave it out"
    ]


@pytest.mark.parametrize("doc", ["launch", "report"])
async def test_first_attempts_report_the_prototype_problems(doc: str) -> None:
    result = await validate_program(
        (FIXTURES / f"first-{doc}.oui").read_text(), (FIXTURES / f"brief-{doc}.txt").read_text()
    )

    assert result.problems == json.loads((FIXTURES / f"first-{doc}.problems.json").read_text())


async def test_missing_bundle_fails_loud(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.openui_artifacts.validate.ARTIFACT_VALIDATOR_BUNDLE", tmp_path / "absent.cjs"
    )

    with pytest.raises(ArtifactValidatorError):
        await validate_program('root = Artifact("a", "b", [], [])', "")
