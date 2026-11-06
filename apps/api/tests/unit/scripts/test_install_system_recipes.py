"""install_system_recipes: the backfill that stores shipped recipes on unedited live system workflows."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scripts import install_system_recipes as script
from app.services.system_workflows.definitions.calendar import PREVIOUSLY_SHIPPED_PROMPTS
from app.services.system_workflows.provisioner import SYSTEM_WORKFLOW_REGISTRY

MODULE = "app.scripts.install_system_recipes"
REMINDER = "calendar:meeting_reminder"


def _workflow(workflow_id: str, prompt: str) -> MagicMock:
    workflow = MagicMock(id=workflow_id, user_id="u1", prompt=prompt, steps=[])
    return workflow


async def _run(
    apply: bool, workflows: list[MagicMock], has_playbook: set[str]
) -> tuple[AsyncMock, MagicMock]:
    install = AsyncMock()
    repo = MagicMock()
    repo.find_live_system_workflows = AsyncMock(
        side_effect=lambda key: workflows if key == REMINDER else []
    )
    playbooks = MagicMock()
    playbooks.get_for_workflow = AsyncMock(
        side_effect=lambda workflow_id, _user: MagicMock() if workflow_id in has_playbook else None
    )
    with (
        patch(f"{MODULE}.workflow_repository", repo),
        patch(f"{MODULE}.playbook_repository", playbooks),
        patch(f"{MODULE}.install_recipe", install),
    ):
        await script._run(argparse.Namespace(apply=apply))
    return install, playbooks


@pytest.mark.unit
class TestInstallSystemRecipes:
    current = SYSTEM_WORKFLOW_REGISTRY[REMINDER]().prompt
    earlier = PREVIOUSLY_SHIPPED_PROMPTS[REMINDER][0]

    async def test_a_dry_run_writes_nothing_and_says_what_it_would(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        install, _ = await _run(False, [_workflow("wf_1", self.current)], set())

        install.assert_not_awaited()
        assert capsys.readouterr().out == (
            f"    1  {REMINDER}: recipe to install\n"
            "\ndry run: nothing written. Re-run with --apply to install the recipes.\n"
        )

    async def test_apply_installs_on_current_and_earlier_shipped_prompts_only(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        workflows = [
            _workflow("wf_edited", "Remind me in French."),
            _workflow("wf_has_one", self.current),
            _workflow("wf_has_two", self.current),
            _workflow("wf_current", self.current),
            _workflow("wf_earlier", self.earlier),
            _workflow("wf_edited_too", "Remind me in Hindi."),
        ]

        install, playbooks = await _run(True, workflows, {"wf_has_one", "wf_has_two"})

        assert [call.args[1] for call in install.await_args_list] == ["wf_current", "wf_earlier"]
        assert install.await_args_list[0].args == (REMINDER, "wf_current", "u1", self.current, [])
        assert playbooks.get_for_workflow.await_args_list[0].args == ("wf_has_one", "u1")
        assert capsys.readouterr().out == (
            f"    2  {REMINDER}: already has a playbook\n"
            f"    2  {REMINDER}: edited by the user, left alone\n"
            f"    2  {REMINDER}: recipe installed\n"
        )
