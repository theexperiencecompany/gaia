"""Store the playbook a system workflow ships with, so its first fire replays.

The recipe is stored like any written playbook: hashed against the workflow it
was stored for, so a user's edit retires it exactly as it retires one the agent
wrote, and the lifecycle (heal, discard, rewrite) is the same from then on.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.db.repositories.playbooks import playbook_repository
from app.models.playbook_models import PlaybookDocument
from app.models.workflow_models import WorkflowStep
from app.services.system_workflows.definitions import SYSTEM_RECIPES
from app.services.workflow.playbook.workflow_hash import workflow_hash
from shared.py.wide_events import log

#: authored_run of a stored recipe: no run wrote it, the definition did.
RECIPE_AUTHORED_RUN_PREFIX = "recipe:"


async def install_recipe(
    key: str, workflow_id: str, user_id: str, prompt: str, steps: Sequence[WorkflowStep]
) -> PlaybookDocument | None:
    """Store the recipe for key as this workflow's playbook; None when the key ships none."""
    recipe = SYSTEM_RECIPES.get(key)
    if recipe is None:
        return None
    body = recipe()
    now = datetime.now(UTC)
    stored = await playbook_repository.upsert_for_workflow(
        PlaybookDocument(
            workflow_id=workflow_id,
            user_id=user_id,
            workflow_hash=workflow_hash(prompt, steps),
            authored_run=f"{RECIPE_AUTHORED_RUN_PREFIX}{key}",
            created_at=now,
            updated_at=now,
            description=body.description,
            steps=body.steps,
            result_brief=body.result_brief,
        )
    )
    log.set_ns("system_workflow", recipe_installed=key, playbook_id=stored.playbook_id)
    return stored
