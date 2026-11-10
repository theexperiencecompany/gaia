#!/usr/bin/env python3
"""Store the shipped recipe on every existing system workflow that has no playbook yet.

New system workflows get their recipe when they are provisioned; this is for
the live ones provisioned before recipes shipped. A workflow qualifies when it has
no playbook and its prompt is one GAIA shipped (the current definition's, or an
earlier release's listed in PREVIOUSLY_SHIPPED_PROMPTS): an edited workflow is
the user's own and is left to author its playbook itself.

Dry run by default. Nothing is written without --apply.

Usage::

    cd apps/api
    uv run python -m app.scripts.install_system_recipes            # report only
    uv run python -m app.scripts.install_system_recipes --apply
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflows import workflow_repository
from app.services.system_workflows.definitions import SYSTEM_RECIPES
from app.services.system_workflows.definitions.calendar import PREVIOUSLY_SHIPPED_PROMPTS
from app.services.system_workflows.provisioner import SYSTEM_WORKFLOW_REGISTRY
from app.services.system_workflows.recipes import install_recipe


def _shipped_prompts(key: str) -> frozenset[str]:
    return frozenset(
        {SYSTEM_WORKFLOW_REGISTRY[key]().prompt, *PREVIOUSLY_SHIPPED_PROMPTS.get(key, ())}
    )


async def _run(args: argparse.Namespace) -> None:
    tally: Counter[str] = Counter()
    for key in sorted(SYSTEM_RECIPES):
        shipped = _shipped_prompts(key)
        for workflow in await workflow_repository.find_live_system_workflows(key):
            if workflow.prompt not in shipped:
                tally[f"{key}: edited by the user, left alone"] += 1
                continue
            if await playbook_repository.get_for_workflow(workflow.id, workflow.user_id):
                tally[f"{key}: already has a playbook"] += 1
                continue
            tally[f"{key}: recipe {'installed' if args.apply else 'to install'}"] += 1
            if args.apply:
                await install_recipe(
                    key, workflow.id, workflow.user_id, workflow.prompt, workflow.steps
                )
    for line, count in sorted(tally.items()):
        print(f"{count:5d}  {line}")
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply to install the recipes.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the playbooks")
    asyncio.run(_run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
